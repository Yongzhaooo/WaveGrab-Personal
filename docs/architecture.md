# WaveGrab Personal architecture

Last confirmed: not yet confirmed
Product spec: docs/product.md

Everything below is `(proposed)` unless a README states it. Current structure was read from `src/`.

## Target structure
Single-process Python 3.12 Windows desktop app; no network, no service.

- `src/devices.py`, `config.py`, `paths.py`: device enumeration (loopback/mic), persisted settings (`config.json`), path resolution for source vs frozen exe.
- `src/recorder.py`: WASAPI capture (PyAudioWPatch) per source in a thread with a bounded queue; mixer combines system and mic; owns capture errors and silent-source handling.
- `src/writer.py`: FLAC writing (soundfile) for `mixed`, `system`, `mic` tracks.
- `src/handoff.py`: writes `session.json` and `HANDOFF.md`, builds the clipboard prompt. Agent-neutral by design; the only contract with downstream agents.
- `src/gui/` (`app.py`, `controller.py`, `widgets.py`): UI; `controller` is the only layer calling recorder/handoff. `src/main.py` is the CLI entry (proposed to keep as dev tool), `main_gui.py` the GUI entry.
- `src/mp3_converter.py`: optional post-step (pydub); status unclear.
- Build: `build.spec` / `build.bat` (PyInstaller) -> `dist/`. Verification: `selfcheck.py`.

State ownership: settings in `config.json`; recordings in the session folder (the folder is the unit of truth; no database).

## Approach
One viable approach: keep the flat-file session folder as the integration contract instead of an API, since agents already read files and the README forbids upload/CLI coupling. Handoff schema changes must stay additive so older agent prompts keep working.

## Route
1. Today (2 commits unpushed to origin/main): dual-source, room mode, silent-source fix. Acceptance: `selfcheck.py` passes.
2. Housekeeping: stop tracking `config.json` per-user values and `__pycache__`/build outputs if tracked (check `.gitignore`). Acceptance: clean `git status` after a run.
3. Decide MP3 converter fate (remove or document). Acceptance: README and requirements agree.
4. Optional: add a `schema_version` field to `session.json` before any third consumer appears. Irreversible once agents depend on it; additive only.

## Open decisions
- Publish the 2 unpushed commits to origin (Yongzhaooo/WaveGrab-Personal)? blocks: Route 1 being safe from loss.
- Track `config.json`? blocks: Route 2.
- Keep MP3 converter? blocks: Route 3.
