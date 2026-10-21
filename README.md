# WaveGrab Personal

本地 Windows 会议录音与说话人转录工具，基于 [WaveGrab](https://github.com/francescoscalzo/WaveGrab)（MIT）修改。

## 使用

运行 `dist/WaveGrab-Personal.exe` 或双击 `Start-WaveGrab.cmd`。

程序默认驻留系统托盘（灰蓝色麦克风图标）；双击图标或右键“打开 WaveGrab”显示设置。关闭主窗口只是隐藏，录音继续；托盘“退出”会保存当前录音并退出。录音时仅显示小红点，暂停或有异常时显示小黄点；鼠标悬停可查看状态及最近标记。不发消息气泡、不弹状态通知，也不自动弹出主窗口；异常在界面内显示。截图请求关闭 Windows 捕获边框，以托盘状态作为录制提示。

- **Alt+R**：全局开始／停止并保存录音。
- **Alt+M**：给当前录音打一个带时间的标记。
- 快捷键被其他软件占用时会提示，可使用托盘菜单完成同样操作。

**会议截图**：刷新并选择 Teams 会议窗口，开启“Teams 截图”。录音时约 3 秒保存一张压缩 JPEG，保持比例缩小到 1280×720 内，完全重复画面不另存。只捕获选定窗口，包括其中共享的画面和参会者，不捕获它外面的桌面或其他应用。窗口可以放在其他窗口后面；真正最小化后暂停截图、录音继续，恢复后继续截图。窗口关闭后不自动切换目标；下次启动程序需重新选会议窗口。

**快速回看**：停止保存后点击“回看画面与标记”，或使用托盘菜单。也可双击会话中的 `review.html`，点击标记跳转音频与对应截图，拖动时间轴查看画面。音频不会自动播放；截图缺失时明确显示上一张的采集时间。暂停时音频与截图一起暂停，标记时间扣除暂停时长。

**录音**：默认会议室模式，只读取所选麦克风。它收录现场人员及房间音响，不播放声音，不修改 Teams 的静音或 No audio 设置。取消会议室模式可录系统声音和麦克风两路。录音前可点“检查输入”，暂停和 Mini 窗口仍可使用。

**Teams 无外放录音**：单独安装 [VB-CABLE](https://vb-audio.com/Cable/) 后，按以下方式配置：

1. Teams 麦克风保持静音；扬声器选择 `CABLE Input (VB-Audio Virtual Cable)`，允许声音输出到这条虚拟线路。
2. WaveGrab 取消“会议室模式”，系统声音选择 `CABLE Output (VB-Audio Virtual Cable)`，麦克风选择实际麦克风。
3. 不启用虚拟线路的“侦听此设备”或其他声音监听；物理扬声器与耳机保持静音、音量 0。

Teams 把远端声音送进虚拟线路，WaveGrab 从线路另一端录制；本地麦克风由 WaveGrab 独立读取，不通过 Teams 发送。Teams 扬声器静音或 No audio 会阻断远端声音，不能同时保持该状态并录到远端。2026-10-19 的实际会议试录已保存 15 秒远端与本地双轨，远端可转录为英语，用户确认没有实际播放声音。

VB-CABLE 是单独安装的非开源 donationware 驱动，不随本项目打包。WaveGrab 不自动调整 Teams 或 Windows 音频路由；更换设备或重新入会时需确认 Teams 仍指向虚拟线路。

**转录与说话人**：录音保存后进入此页，也可打开已有音频文件夹。选择音频，人数填 0 自动判断，或填写已知人数，然后点“转录并区分说话人”。处理期间可以取消，原音频保留。

**录音记录**：按日期浏览录音、写备注、选择“会议 / Desk”文字场景，再直接查看或转录。会议保留全部发言；Desk 自动建议两个主要声纹，也可手动改选。正文排除其他已知声纹，完整稿和背景候选/待核对稿另存；未知和重叠仍保留正文，避免误删主要对话。勾选“显示全部”可检查全部内容。此设置不改变录音设备。

默认启用“自动识别 Teams 会议”：按 Alt+R 后，确认单个会议窗口及 Teams 的 VB-CABLE 输出会话时自动录双路并选择会议窗口；否则使用会议室模式。没有截图目标也能录音。可取消自动识别后手动选择模式。程序不改变 Teams 或系统声音设置。

后台录音时，屏幕右下角任务栏上方有小红点；Alt+M 成功打标后短暂变成绿色空心点。暂停为琥珀色空心，保存完成后小点消失。小点不抢焦点或拦截鼠标；未录音时按 Alt+M 短闪琥珀色。

录音和处理可并行：旧会议正在转录时可以录新会议，只禁止转录仍在写入的那一场。停止录音会先保存音频并恢复就绪，截图收尾和回看页生成在后台进行。退出时回看页若未生成，下次点击“回看画面与标记”可重新生成；原音频与时间轴不依赖回看页。

**命名和校正**：选择 Speaker 1 等标签，输入名称，点“整场统一改名”。名称只作用于这次会议，所有相关段落与本地导出同步更新。选中一段可查看完整文字、双击校正；原始识别输出不被覆盖。

**清洗交接**：复制交接说明给 Codex、agy 或其他工具。已有转录时，工具按片段 ID 把清洗文字写入 `transcript.edits.json`；点“刷新结果”生成清洗稿。应用本身不调用远程大模型做语义清洗。

默认录音目录为用户的 `Music/WaveGrab`，可以修改。每次录音一个文件夹：

| 文件 | 含义 |
| --- | --- |
| `mixed.flac`、`mic.flac`、`system.flac` | 无损合成音频及所选来源；会议室模式没有系统音轨 |
| `session.json`、`HANDOFF.md` | 录音状态、设备及通用交接 |
| `screenshots/*.jpg`、`timeline.jsonl` | 所选窗口的压缩截图、录音时间、标记及采集状态 |
| `review.html` | 不联网的画面与音频回看页，标记可点击定位 |
| `transcript.raw.json`、`transcript.raw.md` | 一次识别的原始结果，包含稳定片段和 speaker ID，不覆盖 |
| `speakers.json` | 当前会议的显示名映射 |
| `transcript.edits.json` | 清洗或校正文字，格式如 `{"seg_00001": "校正后的内容"}` |
| `exports/transcript.md`、`exports/transcript.srt` | 按当前名称重新生成的导出；SRT 在有编辑时使用校正文字 |
| `exports/transcript.clean.md` | 有编辑时生成的清洗稿，标明已编辑片段数量 |
| `transcription.log` | 最近一次处理的进度或错误 |

`exports/` 可重新生成，不要把唯一的手工修改只放在这里。原始 JSON 不要手改 ID；需要重新识别时使用另一个音频文件夹，避免旧名称被错误套到新 speaker ID。

## 本地转录环境

当前使用 faster-whisper small 多语言模型（CPU int8），以及 pyannote 分段、WeSpeaker ResNet34-LM 声纹与谱聚类。人数默认自动估计，短促或无法可靠归类的发言保留为未知。无需付费 API 或账户；首次下载模型需要网络，音频处理在本机进行。较长会议在 CPU 上可能较慢。

从源码安装：运行 `Setup-Transcription.cmd`。它在 `dist/.runtime` 安装独立 Python 环境，在 `dist/models` 下载模型。需要本机 Python 3.12 或 3.13。录音 EXE 旁边的 `_internal` 是必需组件；本地转录还需要 `.runtime` 与 `models`。Python 虚拟环境不应直接搬到另一台电脑，换电脑请从源码重新运行安装脚本。

模型来源：[sherpa-onnx segmentation](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models)、[WeSpeaker embedding](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)、[faster-whisper small](https://huggingface.co/Systran/faster-whisper-small)。谱聚类参考 [WeSpeaker recipe](https://github.com/wenet-e2e/wespeaker/blob/master/wespeaker/diar/spectral_clusterer.py)，许可见 [Apache-2.0](licenses/WeSpeaker-Apache-2.0.txt)。模型缓存与录音不提交 Git。已有安装升级时重新运行 `Setup-Transcription.cmd`，补充 SciPy 与新版声纹模型；原模型缓存不覆盖。

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
.\.venv\Scripts\python.exe -m unittest test_visuals -v
.\.venv\Scripts\python.exe -m unittest test_meeting -v
.\.venv\Scripts\python.exe -m unittest test_recordings -v
.\dist\.runtime\Scripts\python.exe -m unittest test_diarization -v
```

这些检查覆盖录音保存、会议室模式、转录结果保护、改名/清洗导出、截图边界与压缩、标记和托盘 UI 状态，不开启麦克风或实际捕获桌面。

实际混合会议、回声和多人抢话的质量待真实样本验证；未知或明确重叠的片段会单独标记。程序不会启用被 Windows 禁用的设备或解除硬件静音。截图使用 Windows Graphics Capture；本机 Windows 11 已完成 Teams 窗口采集验证，最小化时不保证会议应用继续渲染新画面。

产品要求见 [docs/product.md](docs/product.md)，结构与取舍见 [docs/architecture.md](docs/architecture.md)。原作者声明与源码许可证见 [LICENSE](LICENSE)。
