# WaveGrab Personal

Windows 双路录音小工具。基于 [WaveGrab](https://github.com/francescoscalzo/WaveGrab)（MIT）修改。

## 使用

运行 `dist/WaveGrab-Personal.exe`，或双击 `Start-WaveGrab.cmd`。
EXE 旁边的 `_internal` 文件夹是运行所需组件，移动程序时请一起保留。

1. 默认选择 Windows 当前的系统声音和麦克风，也可以手动换设备。
2. 填录音主题，点击 **开始录音**；需要时暂停或切换 Mini 窗口。
3. 点击 **停止保存**。
4. 点击 **打开录音文件夹**，或 **复制交接说明**，粘贴给 Codex、agy 或其他工具。

默认保存在用户的 `Music/WaveGrab` 文件夹，可在界面中修改。
默认勾选 **会议室模式 · 只录麦克风**：用笔记本麦克风收录现场声音和会议室音响，
不打开系统声音回环、不播放音频、不改变 Teams 的静音或 No audio 设置。
取消勾选即可恢复系统声音与麦克风双路录制；模式会在下次启动时保留。
如果麦克风被硬件或 Windows 禁用/静音，需要用户自行处理；程序不会自动启用或解除静音。
“检查输入”只显示输入音量，不会通过扬声器回放。

每次录音单独建文件夹，包含：

- `mixed.flac`：合成的无损音频，优先用于转录。
- `system.flac`、`mic.flac`：所选设备的独立音轨。
- `HANDOFF.md`：通用转录和清洗要求。
- `session.json`：设备、录制时长和完成状态。

会议室模式只生成 `mic.flac` 和 `mixed.flac`，不生成系统音轨。

音轨按录制音量保存；独立来源不等同于说话人分离。暂停期间不保存声音。
FLAC 无需 FFmpeg；应用不内置转录模型，也不会启动 AI 工具或上传录音。
下游工具需要有读取音频或调用转录工具的能力。

## 从源码运行或打包

Windows 10/11、Python 3.12 或更新版本：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe src/main_gui.py
.\build.bat
```

离线小检查：`.\.venv\Scripts\python.exe selfcheck.py`。
它用合成音频覆盖混音、独立音轨和 UTF-8 交接文件，不开启麦克风。

许可证与原作者声明见 [LICENSE](LICENSE)。
