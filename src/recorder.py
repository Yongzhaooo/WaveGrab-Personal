"""WASAPI audio capture (loopback and microphone)."""

import logging
import threading
import queue
from dataclasses import dataclass, field

import numpy as np
import pyaudiowpatch as pyaudio


CHUNK_SIZE = 2048
FORMAT = pyaudio.paInt16
DTYPE = np.int16

logger = logging.getLogger(__name__)


@dataclass
class StreamConfig:
    """Configuration for an audio stream."""
    device_index: int
    channels: int
    sample_rate: int
    volume: float = 1.0


@dataclass
class AudioCapture:
    """Manages capture of an audio stream."""
    config: StreamConfig
    _stream: object = field(default=None, repr=False)
    _thread: threading.Thread = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)
    _queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=100), repr=False)
    _pyaudio: object = field(default=None, repr=False)

    def start(self, p: pyaudio.PyAudio) -> None:
        """Start audio capture."""
        self._pyaudio = p
        self._running = True

        self._stream = p.open(
            format=FORMAT,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            input_device_index=self.config.device_index,
            frames_per_buffer=CHUNK_SIZE
        )

        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop audio capture."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

    def _capture_loop(self) -> None:
        """Capture loop running in separate thread."""
        while self._running:
            try:
                data = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
                # Convert to numpy and apply volume
                audio = np.frombuffer(data, dtype=DTYPE).astype(np.float32)
                audio *= self.config.volume

                try:
                    self._queue.put_nowait(audio)
                except queue.Full:
                    # Discard oldest frame if queue is full
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(audio)
                    except queue.Empty:
                        pass
            except OSError as e:
                if self._running:
                    logger.warning(f"Audio capture error: {e}")
                    continue
                break
            except Exception as e:
                if self._running:
                    logger.error(f"Unexpected capture error: {e}")
                    continue
                break

    def get_chunk(self) -> np.ndarray | None:
        """Get chunk from queue. Returns None if empty."""
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return None

    def get_chunk_blocking(self, timeout: float = 0.1) -> np.ndarray | None:
        """Get chunk from queue, waiting if necessary."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class Recorder:
    """Manages simultaneous recording of loopback and microphone."""

    def __init__(
        self,
        loopback_config: StreamConfig | None = None,
        mic_config: StreamConfig | None = None,
        target_sample_rate: int = 48000
    ):
        self.loopback_config = loopback_config
        self.mic_config = mic_config
        self.target_sample_rate = target_sample_rate

        self._pyaudio: pyaudio.PyAudio | None = None
        self._loopback: AudioCapture | None = None
        self._mic: AudioCapture | None = None
        self._running = False
        self._paused = False
        self._record_thread: threading.Thread | None = None
        self._output_queue: queue.Queue = queue.Queue(maxsize=500)

        # Last chunks read (for level visualization)
        self._last_loopback_chunk: np.ndarray | None = None
        self._last_mic_chunk: np.ndarray | None = None

    def start(self) -> None:
        """Start recording."""
        if self._running:
            return

        self._pyaudio = pyaudio.PyAudio()
        self._running = True

        if self.loopback_config:
            self._loopback = AudioCapture(self.loopback_config)
            self._loopback.start(self._pyaudio)

        if self.mic_config:
            self._mic = AudioCapture(self.mic_config)
            self._mic.start(self._pyaudio)

        self._record_thread = threading.Thread(target=self._mix_loop, daemon=True)
        self._record_thread.start()

    def stop(self) -> None:
        """Stop recording."""
        self._running = False

        if self._loopback:
            self._loopback.stop()
            self._loopback = None

        if self._mic:
            self._mic.stop()
            self._mic = None

        if self._record_thread:
            self._record_thread.join(timeout=2.0)
            self._record_thread = None

        if self._pyaudio:
            self._pyaudio.terminate()
            self._pyaudio = None

    def pause(self) -> None:
        """Pause recording (discards data)."""
        self._paused = True

    def resume(self) -> None:
        """Resume recording."""
        self._paused = False

    @property
    def is_paused(self) -> bool:
        """Return True if recording is paused."""
        return self._paused

    def set_loopback_volume(self, volume: float) -> None:
        """Set loopback volume (0.0-1.0)."""
        if self.loopback_config:
            self.loopback_config.volume = max(0.0, min(1.0, volume))
            if self._loopback:
                self._loopback.config.volume = self.loopback_config.volume

    def set_mic_volume(self, volume: float) -> None:
        """Set microphone volume (0.0-1.0)."""
        if self.mic_config:
            self.mic_config.volume = max(0.0, min(1.0, volume))
            if self._mic:
                self._mic.config.volume = self.mic_config.volume

    def _resample(self, audio: np.ndarray, src_rate: int, dst_rate: int, channels: int) -> np.ndarray:
        """Simple resample using linear interpolation."""
        if src_rate == dst_rate:
            return audio

        ratio = dst_rate / src_rate

        if channels > 1:
            audio = audio.reshape(-1, channels)

        src_len = len(audio)
        dst_len = int(src_len * ratio)

        x_old = np.arange(src_len)
        x_new = np.linspace(0, src_len - 1, dst_len)

        if channels > 1:
            result = np.zeros((dst_len, channels), dtype=np.float32)
            for ch in range(channels):
                result[:, ch] = np.interp(x_new, x_old, audio[:, ch])
            return result.flatten()
        else:
            return np.interp(x_new, x_old, audio).astype(np.float32)

    def _to_stereo(self, audio: np.ndarray, src_channels: int) -> np.ndarray:
        """Convert to stereo if needed."""
        if src_channels == 2:
            return audio
        elif src_channels == 1:
            # Mono -> Stereo: duplicate channel
            mono = audio.reshape(-1, 1)
            return np.hstack([mono, mono]).flatten()
        else:
            # Multi-channel -> Stereo: take first two
            multi = audio.reshape(-1, src_channels)
            return multi[:, :2].flatten()

    def _mix_loop(self) -> None:
        """Mixing loop running in separate thread."""
        while self._running:
            loopback_chunk = None
            mic_chunk = None

            # Get chunks
            if self._loopback:
                loopback_chunk = self._loopback.get_chunk_blocking(timeout=0.05)
                if loopback_chunk is not None:
                    self._last_loopback_chunk = loopback_chunk.copy()
            if self._mic:
                mic_chunk = self._mic.get_chunk_blocking(timeout=0.05)
                if mic_chunk is not None:
                    self._last_mic_chunk = mic_chunk.copy()

            # If no data, continue
            if loopback_chunk is None and mic_chunk is None:
                continue

            # If paused, discard data
            if self._paused:
                continue

            # Process loopback
            if loopback_chunk is not None:
                loopback_chunk = self._resample(
                    loopback_chunk,
                    self.loopback_config.sample_rate,
                    self.target_sample_rate,
                    self.loopback_config.channels
                )
                loopback_chunk = self._to_stereo(loopback_chunk, self.loopback_config.channels)

            # Process mic
            if mic_chunk is not None:
                mic_chunk = self._resample(
                    mic_chunk,
                    self.mic_config.sample_rate,
                    self.target_sample_rate,
                    self.mic_config.channels
                )
                mic_chunk = self._to_stereo(mic_chunk, self.mic_config.channels)

            # Mix
            if loopback_chunk is not None and mic_chunk is not None:
                # Align lengths
                min_len = min(len(loopback_chunk), len(mic_chunk))
                loopback_chunk = loopback_chunk[:min_len]
                mic_chunk = mic_chunk[:min_len]
                # Mix: simple average
                mixed = (loopback_chunk + mic_chunk) * 0.5
            elif loopback_chunk is not None:
                mixed = loopback_chunk
            else:
                mixed = mic_chunk

            # Clip to int16 range
            mixed = np.clip(mixed, -32768, 32767).astype(DTYPE)

            try:
                self._output_queue.put_nowait(mixed)
            except queue.Full:
                try:
                    self._output_queue.get_nowait()
                    self._output_queue.put_nowait(mixed)
                except queue.Empty:
                    pass

    def get_mixed_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Get a mixed chunk."""
        try:
            return self._output_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def is_running(self) -> bool:
        return self._running

    def get_loopback_level_chunk(self) -> np.ndarray | None:
        """Return last loopback chunk for level visualization."""
        return self._last_loopback_chunk

    def get_mic_level_chunk(self) -> np.ndarray | None:
        """Return last mic chunk for level visualization."""
        return self._last_mic_chunk
