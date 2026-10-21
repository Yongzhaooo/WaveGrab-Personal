"""Local pyannote segmentation + WeSpeaker embeddings + spectral clustering.

Spectral recipe: wenet-e2e/wespeaker, wespeaker/diar/spectral_clusterer.py
Copyright (c) 2022 Xu Xiang; Apache-2.0, see licenses/WeSpeaker-Apache-2.0.txt.
"""
import numpy as np


def cluster_embeddings(embeddings, speakers=0):
    """WeSpeaker's nearest-neighbor graph/eigengap recipe, deterministic k-means."""
    from scipy.linalg import eigh
    from scipy.cluster.vq import kmeans2

    x = np.asarray(embeddings, dtype=np.float64)
    if x.ndim != 2 or not len(x) or not np.isfinite(x).all():
        raise ValueError('没有有效的声纹特征')
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    if np.any(norms == 0) or not 0 <= speakers <= len(x):
        raise ValueError('声纹无效或指定人数超过有效语音片段数')
    x = x / norms
    if len(x) <= 2 and not speakers:
        return np.zeros(len(x), dtype=int)
    if len(x) < 50 and not speakers:
        from scipy.cluster.hierarchy import linkage, fcluster
        # Ten neighbors swamp minority voices in short clips; keep distinct voices for later selection.
        return fcluster(linkage(x, method='average', metric='cosine'), .3, criterion='distance') - 1
    similarity = x @ x.T
    graph = np.zeros_like(similarity)
    neighbors = np.argsort(similarity, axis=1)[:, -min(10, len(x)):]
    np.put_along_axis(graph, neighbors, 1, axis=1)
    graph = (graph + graph.T) / 2
    np.fill_diagonal(graph, 0)
    values, vectors = eigh(np.diag(graph.sum(axis=1)) - graph)
    count = speakers or int(np.argmax(np.diff(values[:min(21, len(values))])) + 1)
    if count == 1:
        return np.zeros(len(x), dtype=int)
    coords = vectors[:, :count]
    best = None
    for seed in range(10):
        centers, labels = kmeans2(coords, count, minit='++', seed=seed, iter=30)
        error = np.sum((coords - centers[labels]) ** 2)
        if best is None or error < best[0]:
            best = error, labels
    return best[1]


def assign_embeddings(embeddings, centers):
    """Reject weak/ambiguous matches instead of inventing additional people."""
    x = np.asarray(embeddings, dtype=np.float64)
    centers = np.asarray(centers, dtype=np.float64)
    x = x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
    centers = centers / np.maximum(np.linalg.norm(centers, axis=1, keepdims=True), 1e-12)
    distances = 1 - x @ centers.T
    labels = np.argmin(distances, axis=1)
    nearest = distances[np.arange(len(x)), labels]
    accepted = np.isfinite(x).all(axis=1) & (nearest <= .45)
    if len(centers) > 1:
        ordered = np.sort(distances, axis=1)
        accepted &= ordered[:, 1] - ordered[:, 0] >= .05
    return np.where(accepted, labels, -1)


def frame_turns(labels, step, offset, duration):
    turns = []
    for speaker in range(labels.shape[1]):
        active = labels[:, speaker]
        boundaries = np.flatnonzero(np.diff(np.r_[False, active, False]))
        for a, b in zip(boundaries[::2], boundaries[1::2]):
            start, end = min(duration, a * step + offset), min(duration, b * step + offset)
            if end - start >= .1:
                turns.append(dict(start=start, end=end,
                                  speaker='unknown' if speaker == labels.shape[1] - 1 else speaker))
    return sorted(turns, key=lambda t: t['start'])


def diarize(audio, segmentation, embedding, speakers=0, progress=print):
    import onnxruntime as ort
    import sherpa_onnx

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 2
    opts.inter_op_num_threads = 1
    model = ort.InferenceSession(str(segmentation), sess_options=opts, providers=['CPUExecutionProvider'])
    meta = model.get_modelmeta().custom_metadata_map
    rate = int(meta['sample_rate'])
    size = int(meta['window_size'])
    frame_step = int(meta['receptive_field_shift']) / rate
    offset = int(meta['receptive_field_size']) / (2 * rate)
    if meta['model_type'] != 'pyannote-segmentation-3.0' or rate != 16000:
        raise ValueError('不支持的说话人分段模型')
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=2, provider='cpu'))
    powerset = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1],
                         [1, 1, 0], [1, 0, 1], [0, 1, 1]], dtype=bool)
    chunks, vectors, train = [], [], []
    hop = size // 2
    starts = list(range(0, max(1, len(audio) - hop), hop))
    for index, start in enumerate(starts):
        samples = audio[start:start + size]
        padded = np.pad(samples, (0, size - len(samples))).astype(np.float32)
        logits = model.run(None, {model.get_inputs()[0].name: padded[None, None, :]})[0][0]
        masks = powerset[np.argmax(logits, axis=1)]
        valid_frames = (np.arange(len(masks)) * frame_step + offset) < len(samples) / rate
        masks[~valid_frames] = False
        single = masks.sum(axis=1) == 1
        # Use only non-overlapping speech to establish a person's voice.
        sample_frames = np.clip(((np.arange(len(samples)) / rate - offset) / frame_step).round().astype(int), 0, len(masks) - 1)
        vector_ids = []
        for person in range(3):
            clean = samples[(masks[:, person] & single)[sample_frames]]
            vector_id = None
            if len(clean) >= rate * .5:
                stream = extractor.create_stream()
                stream.accept_waveform(rate, clean)
                stream.input_finished()
                if extractor.is_ready(stream):
                    vector = np.asarray(extractor.compute(stream))
                    if np.isfinite(vector).all() and np.linalg.norm(vector) > 0:
                        vector_id = len(vectors)
                        vectors.append(vector / np.linalg.norm(vector))
                        train.append(len(clean) >= rate * 1.5)
            vector_ids.append(vector_id)
        chunks.append((round(start / rate / frame_step), masks, vector_ids))
        if index % 20 == 0:
            progress(f'声纹分析 {index + 1} / {len(starts)}')
    del model, extractor
    if not any(train):
        # Very short recordings cannot establish identities reliably.
        centers = np.empty((0, 0))
        assignments = np.full(len(vectors), -1)
    else:
        vectors = np.asarray(vectors)
        training = vectors[np.asarray(train)]
        labels = cluster_embeddings(training, speakers)
        centers = np.stack([training[labels == label].mean(axis=0) for label in np.unique(labels)])
        assignments = assign_embeddings(vectors, centers)
    count = len(centers)
    frames = int(np.ceil(len(audio) / rate / frame_step)) + 1
    votes = np.zeros((frames, count + 1), dtype=np.float32)
    observations = np.zeros(frames)
    totals = np.zeros(frames)
    for start, masks, vector_ids in chunks:
        length = min(len(masks), frames - start)
        local = np.zeros((length, count + 1), dtype=bool)
        for person, vector_id in enumerate(vector_ids):
            label = assignments[vector_id] if vector_id is not None else -1
            local[:, label if label >= 0 else count] |= masks[:length, person]
        votes[start:start + length] += local
        totals[start:start + length] += local.sum(axis=1)
        observations[start:start + length] += 1
    active_count = np.floor(totals / np.maximum(observations, 1) + .5).astype(int)
    ranks = np.argsort(-votes, axis=1)
    active = np.zeros_like(votes, dtype=bool)
    for rank in range(count + 1):
        rows = np.flatnonzero(active_count > rank)
        active[rows, ranks[rows, rank]] = votes[rows, ranks[rows, rank]] > 0
    progress(f'找到 {count} 个主要声纹组；不确定片段保留为未知')
    return frame_turns(active, frame_step, offset, len(audio) / rate)
