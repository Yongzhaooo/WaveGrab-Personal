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

独立音轨保留各自设备采样率及录制音量；不是已分离的说话人。
暂停期间不保存声音。原音频请保留，不覆盖。

## 处理请求（适用于 Codex、agy 或其他工具）

1. 先转录音频，保留原语言、中英混说、术语及时间戳；无法听清标注时间点，不猜测。
2. 把原始转录保存为 `transcript.raw.md`。
3. 清理口头填充、无意义重复和明显识别错误，按话题分段，保存为 `transcript.clean.md`。
4. 保留事实、数字、否定、条件及不确定性；不要把推测改成结论，不凭空补人名或责任人。
5. 不覆盖原始转录。若工具不能读取音频，明确说明缺少的转录能力，不假装已听取。

本文件是普通文本入口，不会自动启动工具或上传录音。
'''
    path = folder / 'HANDOFF.md'
    path.write_text(note, encoding='utf-8')
    return path


def clipboard_prompt(folder: Path) -> str:
    return (f'请处理这个录音文件夹：{folder.resolve()}\n'
            '先阅读 HANDOFF.md，按其中要求转录音频、保留原始转录，再清洗为 Markdown。'
            '原始音频不要改动。')
