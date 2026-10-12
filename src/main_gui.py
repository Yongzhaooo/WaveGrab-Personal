"""Entry point GUI per WASAPI Audio Recorder."""

import sys
from pathlib import Path

# Aggiungi src al path per gli import
sys.path.insert(0, str(Path(__file__).parent))

def main() -> int:
    """Entry point principale."""
    try:
        from gui import AudioRecorderApp
        app = AudioRecorderApp()
        app.run()
        return 0
    except Exception as e:
        import traceback
        from paths import get_exe_dir
        log_path = get_exe_dir() / 'startup.log'
        log_path.write_text(traceback.format_exc(), encoding='utf-8')
        if sys.stderr:
            traceback.print_exc()
        from tkinter import messagebox
        messagebox.showerror('WaveGrab 启动失败', f'{e}\n\n详情：{log_path}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
