"""Cross-meeting voiceprints derived only from user-confirmed speaker names; stays on this machine."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

from transcript_store import AUTO_NAMES, RAW, atomic_text, json_text, load_result, read_json

EMBEDDINGS = 'speaker.embeddings.json'
EMBED_MODEL = 'embedding-wespeaker-resnet34-lm.onnx'
# shortcut: thresholds come from three real recordings (2026-10-22); recalibrate as confirmed samples grow.
MIN_RECORDINGS, MIN_SECONDS, MIN_SIMILARITY, MIN_LEAD = 3, 120., .85, .05


def load_embeddings(folder):
    folder = Path(folder)
    value = (read_json(folder / RAW, {}) or {}).get('speaker_embeddings') or read_json(folder / EMBEDDINGS, {}) or {}
    return {k: v for k, v in value.items() if isinstance(v, dict) and isinstance(v.get('vector'), list)
            and isinstance(v.get('seconds'), (int, float))}


def library(root, exclude=None):
    """Confirmed samples per person: {name: [(recording, {'seconds', 'vector'})]}."""
    people = {}
    for folder in Path(root).iterdir():
        if folder == exclude or not (folder / RAW).is_file():
            continue
        try:
            names, vectors = read_json(folder / 'speakers.json', {}), load_embeddings(folder)
        except (OSError, ValueError):
            continue
        for speaker, name in names.items() if isinstance(names, dict) else ():
            if isinstance(name, str) and name.strip() and speaker in vectors:
                people.setdefault(name.strip(), []).append((folder.name, vectors[speaker]))
    return people


def ready(samples):
    return len({folder for folder, _ in samples}) >= MIN_RECORDINGS and sum(i['seconds'] for _, i in samples) >= MIN_SECONDS


def centroid(samples):
    vectors = np.asarray([i['vector'] for _, i in samples], dtype=np.float64)
    mean = np.average(vectors, axis=0, weights=[i['seconds'] for _, i in samples])
    return mean / np.linalg.norm(mean)


def match(vectors, people):
    """One speaker per person and one person per speaker; ambiguous matches stay unnamed."""
    if not vectors:
        return {}
    speakers = list(vectors)
    x = np.asarray([vectors[s]['vector'] for s in speakers], dtype=np.float64)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    claims = {}
    for name, samples in people.items():
        if not ready(samples):
            continue
        scores = x @ centroid(samples)
        order = np.argsort(-scores)
        best = scores[order[0]]
        if best >= MIN_SIMILARITY and (len(order) == 1 or best - scores[order[1]] >= MIN_LEAD):
            claims.setdefault(speakers[order[0]], []).append((float(best), name))
    result = {}
    for speaker, options in claims.items():
        options.sort(reverse=True)
        if len(options) == 1 or options[0][0] - options[1][0] >= MIN_LEAD:
            result[speaker] = options[0][1]
    return result


def apply(folder):
    """Write automatic names for a newly transcribed recording; confirmed names always win."""
    folder = Path(folder)
    confirmed = read_json(folder / 'speakers.json', {}) or {}
    names = {s: n for s, n in match(load_embeddings(folder), library(folder.parent, folder)).items() if s not in confirmed}
    if names:
        atomic_text(folder / AUTO_NAMES, json_text(names))
    return names


def backfill(folder, models):
    """Compute voiceprints for a recording transcribed before they were stored."""
    from faster_whisper.audio import decode_audio
    from speaker_diarization import speaker_embeddings
    folder = Path(folder)
    data = load_result(folder)
    path = folder / data.get('audio_file', 'mixed.flac')
    # Identical source tracks are removed after processing; mixed.flac holds the same audio.
    audio = decode_audio(str(path if path.is_file() else folder / 'mixed.flac'), sampling_rate=16000)
    value = speaker_embeddings(audio, data['segments'], Path(models) / EMBED_MODEL)
    atomic_text(folder / EMBEDDINGS, json_text(value))
    return value


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Store voiceprints for already transcribed recordings')
    parser.add_argument('--models', type=Path, required=True)
    parser.add_argument('folders', nargs='+', type=Path)
    args = parser.parse_args()
    for item in args.folders:
        print(json.dumps({item.name: {k: v['seconds'] for k, v in backfill(item, args.models).items()}}, ensure_ascii=False))
