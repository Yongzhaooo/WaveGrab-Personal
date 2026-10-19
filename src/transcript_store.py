"""Session-local transcript data, names, edits, and reproducible exports."""
import html
import json
import math
import os
from pathlib import Path
import re
import tempfile

RAW = 'transcript.raw.json'


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as file:
            file.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def json_text(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


def validate_result(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1:
        raise ValueError('不支持的转录格式')
    segments = data.get('segments')
    if not isinstance(segments, list):
        raise ValueError('转录缺少 segments')
    ids = set()
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError('发言片段必须是对象')
        ident, speaker = item.get('id'), item.get('speaker')
        if not isinstance(ident, str) or not re.fullmatch(r'seg_\d+', ident) or ident in ids:
            raise ValueError('发言片段 ID 无效或重复')
        ids.add(ident)
        if not isinstance(speaker, str) or not re.fullmatch(r'speaker_\d+|unknown|overlap', speaker):
            raise ValueError('说话人 ID 无效')
        start, end = item.get('start'), item.get('end')
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in (start, end)):
            raise ValueError('发言时间无效')
        if not 0 <= start <= end or not isinstance(item.get('text'), str):
            raise ValueError('发言时间或正文无效')
    return data


def load_result(folder):
    data = read_json(Path(folder) / RAW)
    if data is None:
        raise FileNotFoundError('这个文件夹还没有转录结果')
    return validate_result(data)


def speaker_ids(data):
    return list(dict.fromkeys(s['speaker'] for s in data['segments'] if s['speaker'].startswith('speaker_')))


def default_name(speaker):
    if speaker == 'unknown':
        return '未知说话人'
    if speaker == 'overlap':
        return '重叠发言'
    return 'Speaker ' + speaker.split('_')[-1]


def load_names(folder, data):
    names = read_json(Path(folder) / 'speakers.json', {})
    if not isinstance(names, dict) or any(k not in speaker_ids(data) or not isinstance(v, str)
                                          or len(v) > 80 or any(ord(c) < 32 for c in v)
                                          for k, v in names.items()):
        raise ValueError('speakers.json 的名称映射无效')
    return names


def load_edits(folder, data):
    edits = read_json(Path(folder) / 'transcript.edits.json', {})
    ids = {s['id'] for s in data['segments']}
    if not isinstance(edits, dict) or any(k not in ids or not isinstance(v, str) for k, v in edits.items()):
        raise ValueError('transcript.edits.json 必须将现有片段 ID 映射到清洗后的文字')
    return edits


def timestamp(seconds, srt=False):
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    sec, ms = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{sec:02}' + (f',{ms:03}' if srt else '')


def md(text):
    text = html.escape(text, quote=False)
    return re.sub(r'([\\`*_\[\]#])', r'\\\1', text)


def render_markdown(data, names, edits=None):
    edits = edits or {}
    lines = ['# 会议转录', '', '']
    if edits:
        lines[1] = f'已清洗 {len(edits)} / {len(data["segments"])} 个片段；其余保留识别原文。'
    for item in data['segments']:
        name = names.get(item['speaker']) or default_name(item['speaker'])
        lines.extend([f'### [{timestamp(item["start"])}–{timestamp(item["end"])}] {md(name)}',
                      f'<!-- {item["id"]} / {item["speaker"]} -->', '',
                      md(edits.get(item['id'], item['text'])), ''])
    return '\n'.join(lines)


def export_result(folder):
    folder = Path(folder)
    data = load_result(folder)
    names, edits = load_names(folder, data), load_edits(folder, data)
    rendered = {'transcript.md': render_markdown(data, names)}
    captions = []
    for i, item in enumerate(data['segments'], 1):
        name = names.get(item['speaker']) or default_name(item['speaker'])
        text = edits.get(item['id'], item['text']).replace('\n', ' ').replace('\r', ' ')
        captions.append(f'{i}\n{timestamp(item["start"], True)} --> {timestamp(item["end"], True)}\n{name}: {text}\n')
    rendered['transcript.srt'] = '\n'.join(captions)
    if edits:
        rendered['transcript.clean.md'] = render_markdown(data, names, edits)
    for name, content in rendered.items():
        atomic_text(folder / 'exports' / name, content)
    if not edits:
        # This exact file is a derived export; never delete original transcripts.
        (folder / 'exports' / 'transcript.clean.md').unlink(missing_ok=True)
    return data, names, edits


def install_result(folder, data):
    folder = Path(folder)
    validate_result(data)
    folder.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects a previous run and its speaker identities.
    with (folder / RAW).open('x', encoding='utf-8') as file:
        file.write(json_text(data))
    with (folder / 'transcript.raw.md').open('x', encoding='utf-8') as file:
        file.write(render_markdown(data, {}))
    export_result(folder)


def rename_speaker(folder, speaker, name):
    data = load_result(folder)
    if speaker not in speaker_ids(data):
        raise ValueError('请选择可命名的说话人')
    name = name.strip()
    if len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('名称最长 80 个字符，不能包含换行或控制字符')
    names = load_names(folder, data)
    names[speaker] = name
    atomic_text(Path(folder) / 'speakers.json', json_text(names))
    return export_result(folder)


def edit_segment(folder, ident, text):
    data = load_result(folder)
    if ident not in {s['id'] for s in data['segments']}:
        raise ValueError('找不到发言片段')
    edits = load_edits(folder, data)
    edits[ident] = text.strip()
    atomic_text(Path(folder) / 'transcript.edits.json', json_text(edits))
    return export_result(folder)
