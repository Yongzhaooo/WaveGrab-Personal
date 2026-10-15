# WaveGrab Personal product spec

Last confirmed: not yet confirmed

Source: README.md (Chinese, UTF-8), src/, selfcheck.py. Items not stated in the README are marked `(proposed)`.

## Purpose
A personal Windows desktop recorder (fork of francescoscalzo/WaveGrab, MIT) that captures meeting/system audio and the microphone as separate tracks, then hands the recording folder to a local AI agent (Codex, agy, etc.) for transcription and notes. It runs offline; no API keys, uploads or CLI coupling.

## Expectations
### Recording
- One click starts a "meeting" recording: system loopback and microphone are captured together on Windows 10/11 via WASAPI. Stop ends it.
- A "room mode" records the microphone only, without changing the meeting-audio path.
- A silent source (e.g. Teams showing "No audio") does not abort the recording; the other track is kept.
- Output goes to `Music/WaveGrab` by default; the folder is configurable in the GUI.

### Output folder (agent handoff)
- Each session is one folder named `<timestamp>_<title>` containing `mixed.flac`, `system.flac`, `mic.flac`, `HANDOFF.md`, `session.json`.
- `session.json` records status, error, duration, devices and file list, in UTF-8; `HANDOFF.md` tells an agent what to do next.
- In room mode the agent is told to use `mic.flac` rather than `mixed.flac`.
- The GUI offers copying a ready prompt to the clipboard for the agent.
- A failed or partial session still writes a handoff with `status` and `error` (proposed).

### Distribution
- Run from source (`src/main_gui.py`) or as a PyInstaller folder build (`dist/WaveGrab-Personal.exe`, `Start-WaveGrab.cmd`); `_internal` must stay beside the exe.
- `selfcheck.py` passes offline: real mixer, independent tracks, UTF-8 handoff.

## Non-goals
- Cloud upload, built-in transcription or AI calls, API-key handling.
- macOS/Linux support (proposed).
- Multi-user or installer/auto-update distribution (proposed).
- Video capture, editing, or a library/search UI (proposed).

## Open questions
- Is the fork meant to be published/shared, or stay private? blocks: README language (currently Chinese only), release packaging, upstream sync policy.
- Which agents must the handoff prompt support beyond Codex and agy? blocks: HANDOFF.md wording.
- Is the MP3 converter (`src/mp3_converter.py`) still a supported feature? blocks: dependency list (pydub) and README accuracy.
- Should `config.json` (contains local device names and user path) be tracked? blocks: repo hygiene / sharing.
