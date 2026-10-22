"""CPU-only offline inference. Run with the companion runtime, never the GUI interpreter."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
import tarfile
import urllib.request

SEGMENT_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
               'speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2')
EMBED_URL = ('https://github.com/k2-fsa/sherpa-onnx/releases/download/'
             'speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx')
EMBED_NAME = 'embedding-wespeaker-resnet34-lm.onnx'


def progress(message):
    print(message, flush=True)


def download(url, destination):
    tmp = destination.with_suffix('.download')
    with urllib.request.urlopen(url, timeout=60) as response, tmp.open('wb') as file:
        while chunk := response.read(1024 * 1024):
            file.write(chunk)
    tmp.replace(destination)


def prepare_models(folder):
    folder.mkdir(parents=True, exist_ok=True)
    segmentation = folder / 'segmentation.onnx'
    embedding = folder / EMBED_NAME
    if not segmentation.exists():
        progress('下载说话人分段模型…')
        archive = folder / 'segmentation.tar.bz2'
        download(SEGMENT_URL, archive)
        with tarfile.open(archive) as tar:
            member = next(m for m in tar.getmembers() if m.name.endswith('/model.onnx') and m.isfile())
            with tar.extractfile(member) as source, segmentation.with_suffix('.download').open('wb') as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        segmentation.with_suffix('.download').replace(segmentation)
        archive.unlink()
    if not embedding.exists():
        progress('下载声纹特征模型…')
        download(EMBED_URL, embedding)
    from huggingface_hub import snapshot_download
    asr = folder / 'whisper-small'
    if not (asr / 'model.bin').exists():
        progress('下载多语言转录模型（仅首次，约 460 MB）…')
        snapshot_download('Systran/faster-whisper-small', local_dir=asr,
                          allow_patterns=['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*'],
                          token=False)
    return segmentation, embedding, asr


def speaker_for_interval(start, end, turns):
    scores = defaultdict(float)
    active = []
    for turn in turns:
        overlap = min(end, turn['end']) - max(start, turn['start'])
        if overlap > 0:
            scores[turn['speaker']] += overlap
            active.append(turn)
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if a['speaker'] != b['speaker'] and min(end, a['end'], b['end']) - max(start, a['start'], b['start']) > .03:
                return 'overlap'
    return max(scores, key=scores.get) if scores else 'unknown'


def align_words(words, turns):
    # shortcut: scan turns per word; use an interval index if multi-hour meetings make this material.
    mapping = {speaker: f'speaker_{i + 1}' for i, speaker in
               enumerate(dict.fromkeys(t['speaker'] for t in sorted(turns, key=lambda x: x['start'])
                                       if t['speaker'] not in ('unknown', 'overlap')))}
    output = []
    for word in words:
        speaker = speaker_for_interval(word['start'], word['end'], turns)
        speaker = mapping.get(speaker, speaker)
        if output and output[-1]['speaker'] == speaker and word['start'] - output[-1]['end'] < 1.0:
            output[-1]['end'] = word['end']
            output[-1]['text'] += word['text']
        else:
            output.append({'id': f'seg_{len(output) + 1:05}', 'start': word['start'],
                           'end': word['end'], 'speaker': speaker, 'text': word['text']})
    for item in output:
        item['text'] = item['text'].strip()
    return output


def speaker_statistics(audio, segments, rate=16000):
    import numpy as np
    totals = {}
    for segment in segments:
        speaker = segment['speaker']
        if not speaker.startswith('speaker_'):
            continue
        samples = audio[int(segment['start'] * rate):int(segment['end'] * rate)]
        if not len(samples):
            continue
        energy, count = totals.get(speaker, (0., 0))
        totals[speaker] = (energy + float(np.dot(samples.astype('float64'), samples)), count + len(samples))
    return {speaker: {'speech_seconds': count / rate,
                      'rms_db': float(10 * np.log10(max(energy / count, 1e-12)))}
            for speaker, (energy, count) in totals.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', required=True, type=Path)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--speakers', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.speakers <= 50:
        parser.error('人数应为 0（自动）到 50')
    for key in ('HF_HUB_DISABLE_TELEMETRY', 'HF_HUB_DISABLE_IMPLICIT_TOKEN', 'DO_NOT_TRACK'):
        os.environ[key] = '1'
    segmentation, embedding, asr = prepare_models(args.models)
    if not args.audio:
        progress('本地模型已准备好')
        return
    if not args.output or args.output.exists():
        raise ValueError('输出路径缺失或已经存在')
    from speaker_diarization import diarize
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(args.audio), sampling_rate=16000)
    if not len(audio):
        raise ValueError('音频没有可读取的采样')
    progress('正在区分说话人…')
    turns = diarize(audio, segmentation, embedding, args.speakers, progress)
    progress('正在转录文字…')
    model = WhisperModel(str(asr), device='cpu', compute_type='int8', cpu_threads=4)
    segments, info = model.transcribe(audio, word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
    words = []
    for segment in segments:
        words.extend({'start': w.start, 'end': w.end, 'text': w.word} for w in (segment.words or []))
        if not segment.words and segment.text.strip():
            words.append({'start': segment.start, 'end': segment.end, 'text': segment.text})
        progress(f'已转录 {segment.end:.0f} / {len(audio) / 16000:.0f} 秒')
    aligned = align_words(words, turns)
    progress('正在保存声纹特征…')
    try:
        from speaker_diarization import speaker_embeddings
        voiceprints = speaker_embeddings(audio, aligned, embedding)
    except Exception as exc:  # Voiceprints are optional; the transcript is still useful.
        progress('声纹特征未保存：' + str(exc))
        voiceprints = {}
    import numpy as np
    peak = float(np.max(np.abs(audio)))
    warning = ('音频接近数字静音，没有可用语音；请检查录音来源。' if peak <= 1 / 32768 else
               '未识别到语音，请检查原始录音。') if not aligned else ''
    result = {'schema_version': 1, 'audio_file': args.audio.name, 'language': info.language,
              'engine': 'faster-whisper small int8 + pyannote/WeSpeaker ResNet34-LM spectral',
              'speaker_count_requested': args.speakers, 'turns': turns,
              'words': words,
              'segments': aligned, 'speaker_stats': speaker_statistics(audio, aligned),
              'speaker_embeddings': voiceprints,
              'audio_warning': warning}
    with args.output.open('x', encoding='utf-8') as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    progress('转录完成')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import sys
        progress('处理失败：' + str(exc))
        sys.exit(1)
