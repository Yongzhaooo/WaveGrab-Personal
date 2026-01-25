"""Audio file writing utilities."""

import threading
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf


class AudioWriter:
    """Writes audio data to file in a separate thread."""

    def __init__(
        self,
        output_dir: Path | str = ".",
        sample_rate: int = 48000,
        channels: int = 2,
        format: str = "WAV",
        subtype: str = "PCM_16"
    ):
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.subtype = subtype

        self._file: sf.SoundFile | None = None
        self._filepath: Path | None = None
        self._lock = threading.Lock()
        self._frames_written = 0

    def _generate_filename(self) -> str:
        """Generate filename with timestamp."""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        ext = "wav" if self.format.upper() == "WAV" else "flac"
        return f"recording_{timestamp}.{ext}"

    def start(self, filename: str | None = None) -> Path:
        """Open file for writing."""
        if filename is None:
            filename = self._generate_filename()

        self._filepath = self.output_dir / filename
        self._filepath.parent.mkdir(parents=True, exist_ok=True)

        self._file = sf.SoundFile(
            str(self._filepath),
            mode='w',
            samplerate=self.sample_rate,
            channels=self.channels,
            format=self.format,
            subtype=self.subtype
        )
        self._frames_written = 0

        return self._filepath

    def write(self, data: np.ndarray) -> None:
        """Write audio data to file."""
        if self._file is None:
            return

        with self._lock:
            # Reshape for channels if needed
            if self.channels > 1 and data.ndim == 1:
                data = data.reshape(-1, self.channels)

            self._file.write(data)
            self._frames_written += len(data) if data.ndim == 1 else data.shape[0]

    def stop(self) -> Path | None:
        """Close file and return path."""
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None

        return self._filepath

    @property
    def filepath(self) -> Path | None:
        return self._filepath

    @property
    def duration_seconds(self) -> float:
        """Recording duration in seconds."""
        return self._frames_written / self.sample_rate

    @property
    def is_open(self) -> bool:
        return self._file is not None
