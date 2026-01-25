"""Entry point GUI per WASAPI Audio Recorder."""

import sys
from pathlib import Path

# Aggiungi src al path per gli import
sys.path.insert(0, str(Path(__file__).parent))

from gui import AudioRecorderApp


def main() -> int:
    """Entry point principale."""
    try:
        app = AudioRecorderApp()
        app.run()
        return 0
    except Exception as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
