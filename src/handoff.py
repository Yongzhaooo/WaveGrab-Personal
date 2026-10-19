"""Agent-neutral recording folders; no API keys, uploads, or CLI coupling."""

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path


def session_name(title: str) -> str:
    title = ''.join(c for c in title.strip() if c.isalnum() or c in ' _-')[:80]
    return datetime.now().strftime('%Y-%m-%d_%H%M%S_%f') + '_' + (title or 'recording')


def write_handoff(folder: Path, title: str, devices: dict, duration: float,
                  status: str = 'complete', error: str = '') -> Path:
    tracks = [p.name for p in folder.glob('*.flac')]
    metadata = {
        'title': title or 'recording', 'status': status, 'error': error,
        'duration_seconds': round(duration, 3),
        'audio_files': tracks,
        'visual_files': [name for name in ('timeline.jsonl', 'review.html', 'screenshots')
                         if (folder / name).exists()],
        'devices': {name: asdict(device) if device else None
                    for name, device in devices.items()},
        'created_at': datetime.now().astimezone().isoformat(),
    }
    (folder / 'session.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    note = f'''# 录音交接

主题：{title or '未命名录音'}
状态：{status}
时长：{duration:.1f} 秒（不含暂停）
{('录制提示：' + error) if error else ''}

## 音频

- `mixed.flac`：系统声音和麦克风合成音频，优先用来转录。
- `system.flac` / `mic.flac`：所选来源的独立无损音轨，可用于听辨重叠语音。
- `session.json`：设备、时长和文件信息。

若 session.json 中 system 为 null，此次没有采集系统声音；会议室模式由麦克风收录现场声音及房间音响。

独立音轨保留各自设备采样率及录制音量；不是已分离的说话人。
暂停期间不保存声音。原音频请保留，不覆盖。

## 画面与标记（如有）

`review.html` 是本地回看页，点击标记可定位音频与画面，不自动播放音频。
`timeline.jsonl` 逐行保存截图、标记和采集状态，`seconds` 对应不含暂停的录音时间。
`screenshots/` 只保存用户选定 Teams 窗口的压缩 JPEG，约 3 秒一张，重复画面不另存。
最小化、关闭窗口或录音暂停时没有新截图；旧画面不能当成该时间的新证据。
结合标记和画面理解发言，保留原截图与时间轴，不补造缺失画面。

## 处理请求（适用于 Codex、agy 或其他工具）

1. 先转录音频，保留原语言、中英混说、术语及时间戳；无法听清标注时间点，不猜测。
2. 把原始转录保存为 `transcript.raw.md`。
3. 清理口头填充、无意义重复和明显识别错误，按话题分段，保存为 `transcript.clean.md`。
4. 保留事实、数字、否定、条件及不确定性；不要把推测改成结论，不凭空补人名或责任人。
5. 不覆盖原始转录。若工具不能读取音频，明确说明缺少的转录能力，不假装已听取。

## 已有说话人转录时

若存在 `transcript.raw.json`，直接使用其中的稳定片段 ID、说话人 ID 和时间戳。
`speakers.json` 是本会议内的显示名映射，不跨会议推断人物。
清洗文字写入 `transcript.edits.json`，格式为片段 ID 到清洗文字的 JSON 对象，
例如 `{{"seg_00001": "清洗后的文字"}}`；保留未修改的已有编辑，不修改原始识别文件。
完成后在程序中点击“刷新结果”，统一生成 `exports/` 下的 Markdown、SRT 和清洗稿。
`exports/` 是可覆盖的生成内容；不要把唯一的人工修改只存放在这里。

本文件是普通文本入口，不会自动启动工具或上传录音。
'''
    path = folder / 'HANDOFF.md'
    path.write_text(note, encoding='utf-8')
    return path


def clipboard_prompt(folder: Path) -> str:
    return (f'请处理这个录音文件夹：{folder.resolve()}\n'
            '先阅读 HANDOFF.md（如果存在）。已有 transcript.raw.json 时复用其片段 ID、时间和说话人，'
            '参考 speakers.json 的会议内名称，将清洗后的文字写入 transcript.edits.json '
            '（片段 ID 到文字的 JSON 对象，保留已有编辑）。没有转录时先转录。'
            '不修改原始音频、原始识别结果或说话人归属；不编造听不清的内容。')
