"""Session-local transcript data, names, edits, and reproducible exports."""
import html
import json
import math
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime

RAW = 'transcript.raw.json'
SUMMARY = 'meeting.summary.json'
PROOFREAD = 'transcript.agy.json'
DETAILS = 'recording.json'
AUTO_NAMES = 'speakers.auto.json'
AUTO_MARK = '（自动识别）'
VOICEPRINTS = 'voiceprints.json'
SCENES = {'meeting': '会议 · 保留全部发言', 'desk': 'Desk · 主要对话'}


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


def load_details(folder):
    data = read_json(Path(folder) / DETAILS, {})
    if not isinstance(data, dict):
        raise ValueError('录音备注格式无效')
    data = {'note': '', 'scene': 'meeting', 'focus_speakers': None, **data}
    if not isinstance(data['note'], str) or len(data['note']) > 2000 or not isinstance(data['scene'], str) or data['scene'] not in SCENES:
        raise ValueError('录音备注或场景无效（备注最多 2000 字）')
    focus = data['focus_speakers']
    if focus is not None and (not isinstance(focus, list) or any(
            not isinstance(s, str) or not re.fullmatch(r'speaker_\d+', s) for s in focus)):
        raise ValueError('主要说话人选择无效')
    return data


def save_details(folder, **changes):
    if set(changes) - {'note', 'scene', 'focus_speakers'}:
        raise ValueError('不支持的录音设置')
    data = {**load_details(folder), **changes}
    # Validate before replacing an existing annotation.
    if not isinstance(data['note'], str) or len(data['note']) > 2000 or not isinstance(data['scene'], str) or data['scene'] not in SCENES:
        raise ValueError('备注最多 2000 字，场景须为会议或 Desk')
    focus = data['focus_speakers']
    if focus is not None:
        result = load_result(folder)
        if not isinstance(focus, list) or any(s not in speaker_ids(result) for s in focus):
            raise ValueError('请选择当前录音中的说话人')
    atomic_text(Path(folder) / DETAILS, json_text(data))
    return data


def list_recordings(root):
    root = Path(root)
    if not root.is_dir():
        return []
    rows = []
    for folder in root.iterdir():
        if not folder.is_dir() or not (folder / 'session.json').exists():
            continue
        try:
            session = read_json(folder / 'session.json')
            details = load_details(folder)
            seconds = float(session.get('duration_seconds', 0))
            seconds = seconds if math.isfinite(seconds) and seconds >= 0 else 0
            state = session.get('status', 'unknown')
            summary = read_json(folder / 'transcription.status.json', {})
            warning = summary.get('audio_warning', '') if isinstance(summary, dict) else ''
        except (OSError, ValueError, TypeError, AttributeError):
            details = {'note': '信息无法读取，请打开文件夹查看', 'scene': 'meeting'}
            seconds, state, warning = 0, 'unreadable', ''
        try:
            date = datetime.strptime(folder.name[:17], '%Y-%m-%d_%H%M%S').strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            date = folder.name
        rows.append(dict(folder=folder, date=date, seconds=seconds, state=state,
                         transcribed=(folder / RAW).exists(), audio_warning=warning,
                         note=details['note'], scene=details['scene']))
    return sorted(rows, key=lambda row: row['date'], reverse=True)


def focused_result(folder, data):
    details = load_details(folder)
    ids = speaker_ids(data)
    if details['scene'] == 'meeting':
        return data, [], ids
    chosen = details['focus_speakers']
    if chosen is None:
        durations = {s: sum(t['end'] - t['start'] for t in data['segments'] if t['speaker'] == s) for s in ids}
        stats = data.get('speaker_stats', {})
        def score(speaker):
            item = stats.get(speaker, {}) if isinstance(stats, dict) else {}
            db = item.get('rms_db', 0) if isinstance(item, dict) else 0
            db = db if isinstance(db, (float, int)) and math.isfinite(db) else 0
            # shortcut: loudness and duration suggest foreground voices; user can correct the selection.
            return math.sqrt(max(durations[speaker], 0)) * 10 ** (max(-120, min(0, db)) / 20)
        chosen = sorted(ids, key=score, reverse=True)[:2]
        owner = owner_speaker(folder, data)
        if owner and owner not in chosen:
            chosen = [owner] + chosen[:1]
    if any(s not in ids for s in chosen):
        raise ValueError('主要说话人不属于当前转录，请重新选择')
    # Uncertain speech may be the quiet colleague; only known, unselected identities are excluded.
    kept = [s for s in data['segments'] if s['speaker'] in chosen or s['speaker'] in ('unknown', 'overlap')]
    excluded = [s for s in data['segments'] if s['speaker'].startswith('speaker_') and s['speaker'] not in chosen]
    return {**data, 'segments': kept}, excluded, chosen


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


def _names(path, data):
    names = read_json(path, {})
    if not isinstance(names, dict) or any(k not in speaker_ids(data) or not isinstance(v, str)
                                          or len(v) > 80 or any(ord(c) < 32 for c in v)
                                          for k, v in names.items()):
        raise ValueError(f'{path.name} 的名称映射无效')
    return names


def load_names(folder, data):
    """Display names: confirmed names win; voiceprint suggestions stay visibly automatic."""
    auto = {k: v + AUTO_MARK for k, v in _names(Path(folder) / AUTO_NAMES, data).items()}
    return {**auto, **_names(Path(folder) / 'speakers.json', data)}


def owner_speaker(folder, data):
    owner = (read_json(Path(folder).parent / VOICEPRINTS, {}) or {}).get('owner', '')
    if not isinstance(owner, str) or not owner.strip():
        return None
    names = {**_names(Path(folder) / AUTO_NAMES, data), **_names(Path(folder) / 'speakers.json', data)}
    return next((s for s in speaker_ids(data) if names.get(s, '').strip() == owner.strip()), None)


def load_edits(folder, data):
    auto = read_json(Path(folder) / PROOFREAD, {})
    manual = read_json(Path(folder) / 'transcript.edits.json', {})
    if not isinstance(auto, dict) or not isinstance(auto.get('edits', {}), dict) or not isinstance(manual, dict):
        raise ValueError('清洗结果格式无效')
    edits = {**auto.get('edits', {}), **manual}
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
        count = sum(s['id'] in edits for s in data['segments'])
        lines[1] = f'已清洗 {count} / {len(data["segments"])} 个片段；其余保留识别原文。'
    for item in data['segments']:
        name = names.get(item['speaker']) or default_name(item['speaker'])
        lines.extend([f'### [{timestamp(item["start"])}–{timestamp(item["end"])}] {md(name)}',
                      f'<!-- {item["id"]} / {item["speaker"]} -->', '',
                      md(edits.get(item['id'], item['text'])), ''])
    return '\n'.join(lines)


def validate_summary(summary, segments):
    ids = {s['id'] for s in segments}
    speakers = {s['speaker'] for s in segments}
    if (not isinstance(summary, dict) or not isinstance(summary.get('markdown'), str)
            or not summary['markdown'].strip() or not isinstance(summary.get('notes'), str)
            or not isinstance(summary.get('source_ids'), list) or not summary['source_ids']
            or any(not isinstance(ident, str) or ident not in ids for ident in summary['source_ids'])):
        raise ValueError('总结为空或引用了不存在的片段；原稿保留')
    if any(s not in speakers for s in re.findall(r'\{\{([^{}]+)\}\}', summary['markdown'] + summary['notes'])):
        raise ValueError('总结引用了不存在的说话人')
    return summary


def export_result(folder):
    folder = Path(folder)
    data = load_result(folder)
    names, edits = load_names(folder, data), load_edits(folder, data)
    view, excluded, _ = focused_result(folder, data)
    rendered = {'transcript.md': render_markdown(view, names), 'transcript.srt': render_srt(view, names, edits)}
    desk = load_details(folder)['scene'] == 'desk'
    if desk:
        rendered['transcript.full.md'] = render_markdown(data, names, edits)
        rendered['transcript.full.srt'] = render_srt(data, names, edits)
        review = sorted(excluded + [s for s in data['segments'] if s['speaker'] in ('unknown', 'overlap')], key=lambda s: s['start'])
        rendered['transcript.review.md'] = ('# 背景候选与待核对发言\n\n'
            '未选中的已知声纹已从正文排除；未知与重叠可能包含主要对话，仍保留在正文，并在这里列出待核对。\n\n' +
            render_markdown({**data, 'segments': review}, names, edits))
    if edits:
        rendered['transcript.clean.md'] = render_markdown(view, names, edits)
    proofread = read_json(folder / PROOFREAD)
    if proofread is not None:
        if edits:
            rendered['transcript.clean.md'] = '> AGY 基础校对稿，待核对。原始转录保留；改动与疑点见 proofread-notes.md。\n\n' + rendered['transcript.clean.md']
        rendered['proofread-notes.md'] = ('# 校对说明\n\nAGY 按 subtitle-cleaning 提出、经程序核对原文后采用；人工校正优先。\n\n'
                                          + ('\n'.join(proofread.get('notes', [])) or '没有需要修改的识别错误。') + '\n')
    summary = read_json(folder / SUMMARY)
    if summary is not None:
        validate_summary(summary, data['segments'])
        speaker = lambda text: re.sub(r'\{\{([^{}]+)\}\}', lambda m: md(names.get(m[1]) or default_name(m[1])), text)
        rendered['summary.md'] = speaker(summary['markdown']).strip() + '\n'
        origin = ('外部 agent 导入，原始转录保留。' if summary.get('generator') == 'external-agent'
                  else 'AGY 生成，原始转录保留；本次技能与依据见 process-archive.zip 中的 cleanup-runs。')
        rendered['summary-notes.md'] = f'# 总结核对说明\n\n{origin}\n\n' + speaker(summary['notes']) + '\n'
    for name, content in rendered.items():
        atomic_text(folder / 'exports' / name, content)
    stale = ([] if edits else ['transcript.clean.md']) + ([] if proofread is not None else ['proofread-notes.md'])
    if not desk:
        stale += ['transcript.full.md', 'transcript.full.srt', 'transcript.review.md']
    for name in stale:
        (folder / 'exports' / name).unlink(missing_ok=True)
    return data, names, edits


def render_srt(data, names, edits):
    captions = []
    for i, item in enumerate(data['segments'], 1):
        name = names.get(item['speaker']) or default_name(item['speaker'])
        text = edits.get(item['id'], item['text']).replace('\n', ' ').replace('\r', ' ')
        captions.append(f'{i}\n{timestamp(item["start"], True)} --> {timestamp(item["end"], True)}\n{name}: {text}\n')
    return '\n'.join(captions)


def install_result(folder, data):
    folder = Path(folder)
    validate_result(data)
    folder.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects a previous run and its speaker identities.
    with (folder / RAW).open('x', encoding='utf-8') as file:
        file.write(json_text(data))
    with (folder / 'transcript.raw.md').open('x', encoding='utf-8') as file:
        file.write(render_markdown(data, {}))
    atomic_text(folder / 'transcription.status.json', json_text({
        'segments': len(data['segments']), 'audio_warning': data.get('audio_warning', '')}))
    try:
        from voiceprints import apply
        apply(folder)
    except Exception:  # Suggestions must never block a finished transcription.
        pass
    export_result(folder)


def rename_speaker(folder, speaker, name):
    data = load_result(folder)
    if speaker not in speaker_ids(data):
        raise ValueError('请选择可命名的说话人')
    name = name.strip()
    if len(name) > 80 or any(ord(c) < 32 for c in name):
        raise ValueError('名称最长 80 个字符，不能包含换行或控制字符')
    names = _names(Path(folder) / 'speakers.json', data)
    names[speaker] = name
    atomic_text(Path(folder) / 'speakers.json', json_text(names))
    return export_result(folder)


def edit_segment(folder, ident, text):
    data = load_result(folder)
    if ident not in {s['id'] for s in data['segments']}:
        raise ValueError('找不到发言片段')
    load_edits(folder, data)
    edits = read_json(Path(folder) / 'transcript.edits.json', {})
    edits[ident] = text.strip()
    atomic_text(Path(folder) / 'transcript.edits.json', json_text(edits))
    return export_result(folder)
