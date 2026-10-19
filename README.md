# WaveGrab Personal

本地 Windows 会议录音与说话人转录工具，基于 [WaveGrab](https://github.com/francescoscalzo/WaveGrab)（MIT）修改。

## 使用

运行 `dist/WaveGrab-Personal.exe` 或双击 `Start-WaveGrab.cmd`。

**录音**：默认会议室模式，只读取所选麦克风。它收录现场人员及房间音响，不播放声音，不修改 Teams 的静音或 No audio 设置。取消会议室模式可录系统声音和麦克风两路。录音前可点“检查输入”，暂停和 Mini 窗口仍可使用。

**Teams 无外放录音**：单独安装 [VB-CABLE](https://vb-audio.com/Cable/) 后，按以下方式配置：

1. Teams 麦克风保持静音；扬声器选择 `CABLE Input (VB-Audio Virtual Cable)`，允许声音输出到这条虚拟线路。
2. WaveGrab 取消“会议室模式”，系统声音选择 `CABLE Output (VB-Audio Virtual Cable)`，麦克风选择实际麦克风。
3. 不启用虚拟线路的“侦听此设备”或其他声音监听；物理扬声器与耳机保持静音、音量 0。

Teams 把远端声音送进虚拟线路，WaveGrab 从线路另一端录制；本地麦克风由 WaveGrab 独立读取，不通过 Teams 发送。Teams 扬声器静音或 No audio 会阻断远端声音，不能同时保持该状态并录到远端。2026-10-19 的实际会议试录已保存 15 秒远端与本地双轨，远端可转录为英语，用户确认没有实际播放声音。

VB-CABLE 是单独安装的非开源 donationware 驱动，不随本项目打包。WaveGrab 不自动调整 Teams 或 Windows 音频路由；更换设备或重新入会时需确认 Teams 仍指向虚拟线路。

**转录与说话人**：录音保存后进入此页，也可打开已有音频文件夹。选择音频，人数填 0 自动判断，或填写已知人数，然后点“转录并区分说话人”。处理期间可以取消，原音频保留。

**命名和校正**：选择 Speaker 1 等标签，输入名称，点“整场统一改名”。名称只作用于这次会议，所有相关段落与本地导出同步更新。选中一段可查看完整文字、双击校正；原始识别输出不被覆盖。

**清洗交接**：复制交接说明给 Codex、agy 或其他工具。已有转录时，工具按片段 ID 把清洗文字写入 `transcript.edits.json`；点“刷新结果”生成清洗稿。应用本身不调用远程大模型做语义清洗。

默认录音目录为用户的 `Music/WaveGrab`，可以修改。每次录音一个文件夹：

| 文件 | 含义 |
| --- | --- |
| `mixed.flac`、`mic.flac`、`system.flac` | 无损合成音频及所选来源；会议室模式没有系统音轨 |
| `session.json`、`HANDOFF.md` | 录音状态、设备及通用交接 |
| `transcript.raw.json`、`transcript.raw.md` | 一次识别的原始结果，包含稳定片段和 speaker ID，不覆盖 |
| `speakers.json` | 当前会议的显示名映射 |
| `transcript.edits.json` | 清洗或校正文字，格式如 `{"seg_00001": "校正后的内容"}` |
| `exports/transcript.md`、`exports/transcript.srt` | 按当前名称重新生成的导出；SRT 在有编辑时使用校正文字 |
| `exports/transcript.clean.md` | 有编辑时生成的清洗稿，标明已编辑片段数量 |
| `transcription.log` | 最近一次处理的进度或错误 |

`exports/` 可重新生成，不要把唯一的手工修改只放在这里。原始 JSON 不要手改 ID；需要重新识别时使用另一个音频文件夹，避免旧名称被错误套到新 speaker ID。

## 本地转录环境

当前使用 faster-whisper small 多语言模型（CPU int8）和 sherpa-onnx 说话人分段。无需付费 API 或账户；首次下载模型需要网络，音频处理在本机进行。较长会议在 CPU 上可能较慢。

从源码安装：运行 `Setup-Transcription.cmd`。它在 `dist/.runtime` 安装独立 Python 环境，在 `dist/models` 下载模型。需要本机 Python 3.12 或 3.13。录音 EXE 旁边的 `_internal` 是必需组件；本地转录还需要 `.runtime` 与 `models`。Python 虚拟环境不应直接搬到另一台电脑，换电脑请从源码重新运行安装脚本。

模型来源：[sherpa-onnx segmentation](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models)、[3D-Speaker embedding](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)、[faster-whisper small](https://huggingface.co/Systran/faster-whisper-small)。模型缓存与录音不提交 Git。

## 从源码运行或打包

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe src/main_gui.py
.\build.bat
```

离线检查：

```powershell
.\.venv\Scripts\python.exe selfcheck.py
.\.venv\Scripts\python.exe -m unittest test_transcripts -v
```

这些检查覆盖录音保存、会议室模式、转录结果保护、改名/清洗导出和 UI 状态，不开启麦克风。

实际混合会议、回声和多人抢话的质量待真实样本验证；未知或明确重叠的片段会单独标记。程序不会启用被 Windows 禁用的设备或解除硬件静音。5 秒截图仍是后续需求。

产品要求见 [docs/product.md](docs/product.md)，结构与取舍见 [docs/architecture.md](docs/architecture.md)。原作者声明与源码许可证见 [LICENSE](LICENSE)。
