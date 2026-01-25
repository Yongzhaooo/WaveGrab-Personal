"""Controller for managing recording logic."""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Callable

import numpy as np
import pyaudiowpatch as pyaudio

from paths import get_src_path
import sys
sys.path.insert(0, str(get_src_path()))

from devices import AudioDevice
from recorder import Recorder, StreamConfig, AudioCapture
from writer import AudioWriter
from mp3_converter import convert_wav_to_mp3, is_ffmpeg_available


class RecordingState(Enum):
    """Possible recording states."""
    IDLE = auto()
    MONITORING = auto()
    RECORDING = auto()
    PAUSED = auto()
    CONVERTING = auto()


@dataclass
class RecordingCallbacks:
    """Callbacks for updating the GUI."""
    on_state_change: Callable[[RecordingState], None] | None = None
    on_time_update: Callable[[float], None] | None = None
    on_audio_chunk: Callable[[np.ndarray | None], None] | None = None
    on_loopback_level: Callable[[np.ndarray | None], None] | None = None
    on_mic_level: Callable[[np.ndarray | None], None] | None = None
    on_error: Callable[[str], None] | None = None
    on_conversion_complete: Callable[[Path], None] | None = None


class RecordingController:
    """Manages recording logic between GUI and Recorder."""

    def __init__(self, callbacks: RecordingCallbacks | None = None):
        self.callbacks = callbacks or RecordingCallbacks()

        self._recorder: Recorder | None = None
        self._writer: AudioWriter | None = None
        self._state = RecordingState.IDLE

        self._loopback_device: AudioDevice | None = None
        self._mic_device: AudioDevice | None = None
        self._loopback_volume = 1.0
        self._mic_volume = 1.0

        self._output_folder = Path.cwd()
        self._filename_prefix = ""

        self._record_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_time: float = 0
        self._pause_start: float = 0
        self._total_paused: float = 0

        # Monitoring
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop_event = threading.Event()
        self._loopback_capture: AudioCapture | None = None
        self._mic_capture: AudioCapture | None = None
        self._monitor_pyaudio = None

    @property
    def state(self) -> RecordingState:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state in (RecordingState.RECORDING, RecordingState.PAUSED)

    @property
    def elapsed_time(self) -> float:
        """Elapsed time in seconds (excluding pauses)."""
        if self._state == RecordingState.IDLE:
            return 0.0

        if self._state == RecordingState.PAUSED:
            return self._pause_start - self._start_time - self._total_paused

        current = time.time()
        return current - self._start_time - self._total_paused

    def _set_state(self, state: RecordingState) -> None:
        """Set state and notify."""
        self._state = state
        if self.callbacks.on_state_change:
            self.callbacks.on_state_change(state)

    def set_loopback_device(self, device: AudioDevice | None) -> None:
        """Set loopback device."""
        self._loopback_device = device

    def set_mic_device(self, device: AudioDevice | None) -> None:
        """Set microphone device."""
        self._mic_device = device

    def set_loopback_volume(self, volume: float) -> None:
        """Set loopback volume (0.0-1.0)."""
        self._loopback_volume = max(0.0, min(1.0, volume))
        if self._recorder:
            self._recorder.set_loopback_volume(self._loopback_volume)

    def set_mic_volume(self, volume: float) -> None:
        """Set microphone volume (0.0-1.0)."""
        self._mic_volume = max(0.0, min(1.0, volume))
        if self._recorder:
            self._recorder.set_mic_volume(self._mic_volume)

    def set_output_folder(self, folder: Path | str) -> None:
        """Set output folder."""
        self._output_folder = Path(folder)

    def set_filename_prefix(self, prefix: str) -> None:
        """Set filename prefix."""
        self._filename_prefix = prefix

    # === MONITORING ===

    def start_monitoring(self) -> bool:
        """Start device monitoring to view levels."""
        if self._state not in (RecordingState.IDLE, RecordingState.MONITORING):
            return False

        if self._loopback_device is None and self._mic_device is None:
            return False

        # Stop existing monitoring
        self.stop_monitoring()

        self._monitor_pyaudio = pyaudio.PyAudio()
        self._monitor_stop_event.clear()

        # Start loopback capture
        if self._loopback_device:
            config = StreamConfig(
                device_index=self._loopback_device.index,
                channels=self._loopback_device.channels,
                sample_rate=self._loopback_device.sample_rate,
                volume=self._loopback_volume
            )
            self._loopback_capture = AudioCapture(config)
            self._loopback_capture.start(self._monitor_pyaudio)

        # Start mic capture
        if self._mic_device:
            config = StreamConfig(
                device_index=self._mic_device.index,
                channels=self._mic_device.channels,
                sample_rate=self._mic_device.sample_rate,
                volume=self._mic_volume
            )
            self._mic_capture = AudioCapture(config)
            self._mic_capture.start(self._monitor_pyaudio)

        # Start monitoring thread
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        self._set_state(RecordingState.MONITORING)
        return True

    def stop_monitoring(self) -> None:
        """Stop monitoring."""
        self._monitor_stop_event.set()

        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
            self._monitor_thread = None

        if self._loopback_capture:
            self._loopback_capture.stop()
            self._loopback_capture = None

        if self._mic_capture:
            self._mic_capture.stop()
            self._mic_capture = None

        if self._monitor_pyaudio:
            self._monitor_pyaudio.terminate()
            self._monitor_pyaudio = None

        if self._state == RecordingState.MONITORING:
            self._set_state(RecordingState.IDLE)

    def _monitor_loop(self) -> None:
        """Monitoring loop to display levels."""
        while not self._monitor_stop_event.is_set():
            # Read loopback
            if self._loopback_capture:
                chunk = self._loopback_capture.get_chunk()
                if self.callbacks.on_loopback_level:
                    self.callbacks.on_loopback_level(chunk)

            # Read mic
            if self._mic_capture:
                chunk = self._mic_capture.get_chunk()
                if self.callbacks.on_mic_level:
                    self.callbacks.on_mic_level(chunk)

            time.sleep(0.05)  # ~20 FPS

    def get_output_filename(self) -> str:
        """Generate output filename."""
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        prefix = self._filename_prefix.strip() if self._filename_prefix else "recording"
        # Sanitize filename
        prefix = "".join(c for c in prefix if c.isalnum() or c in "._- ")
        return f"{timestamp}_{prefix}.mp3"

    def start_recording(self) -> bool:
        """Start recording."""
        if self._state not in (RecordingState.IDLE, RecordingState.MONITORING):
            return False

        # Stop monitoring if active
        self.stop_monitoring()

        if self._loopback_device is None and self._mic_device is None:
            if self.callbacks.on_error:
                self.callbacks.on_error("Select at least one device")
            return False

        # Determine target sample rate
        target_rate = 48000
        if self._loopback_device:
            target_rate = max(target_rate, self._loopback_device.sample_rate)
        if self._mic_device:
            target_rate = max(target_rate, self._mic_device.sample_rate)

        # Create configurations
        loopback_config = None
        mic_config = None

        if self._loopback_device:
            loopback_config = StreamConfig(
                device_index=self._loopback_device.index,
                channels=self._loopback_device.channels,
                sample_rate=self._loopback_device.sample_rate,
                volume=self._loopback_volume
            )

        if self._mic_device:
            mic_config = StreamConfig(
                device_index=self._mic_device.index,
                channels=self._mic_device.channels,
                sample_rate=self._mic_device.sample_rate,
                volume=self._mic_volume
            )

        # Create recorder and writer
        self._recorder = Recorder(
            loopback_config=loopback_config,
            mic_config=mic_config,
            target_sample_rate=target_rate
        )

        # Create folder if it doesn't exist
        self._output_folder.mkdir(parents=True, exist_ok=True)

        # Generate temporary WAV filename
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        prefix = self._filename_prefix.strip() if self._filename_prefix else "recording"
        prefix = "".join(c for c in prefix if c.isalnum() or c in "._- ")
        wav_filename = f"{timestamp}_{prefix}.wav"

        self._writer = AudioWriter(
            output_dir=self._output_folder,
            sample_rate=target_rate,
            channels=2
        )

        try:
            self._writer.start(wav_filename)
            self._recorder.start()
        except Exception as e:
            if self.callbacks.on_error:
                self.callbacks.on_error(f"Start error: {e}")
            return False

        # Start recording thread
        self._stop_event.clear()
        self._start_time = time.time()
        self._total_paused = 0
        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()

        self._set_state(RecordingState.RECORDING)
        return True

    def pause_recording(self) -> None:
        """Pause recording."""
        if self._state != RecordingState.RECORDING:
            return

        if self._recorder:
            self._recorder.pause()

        self._pause_start = time.time()
        self._set_state(RecordingState.PAUSED)

    def resume_recording(self) -> None:
        """Resume recording."""
        if self._state != RecordingState.PAUSED:
            return

        if self._recorder:
            self._recorder.resume()

        self._total_paused += time.time() - self._pause_start
        self._set_state(RecordingState.RECORDING)

    def stop_recording(self) -> None:
        """Stop recording and convert to MP3."""
        if self._state == RecordingState.IDLE:
            return

        self._stop_event.set()

        if self._record_thread:
            self._record_thread.join(timeout=3.0)
            self._record_thread = None

        if self._recorder:
            self._recorder.stop()
            self._recorder = None

        wav_path = None
        if self._writer:
            wav_path = self._writer.stop()
            self._writer = None

        # Convert to MP3
        if wav_path and wav_path.exists():
            self._set_state(RecordingState.CONVERTING)

            def convert():
                try:
                    if is_ffmpeg_available():
                        mp3_path = convert_wav_to_mp3(wav_path, delete_wav=True)
                        if self.callbacks.on_conversion_complete:
                            self.callbacks.on_conversion_complete(mp3_path)
                    else:
                        # FFmpeg not available, keep WAV
                        if self.callbacks.on_error:
                            self.callbacks.on_error("FFmpeg not found. File saved as WAV.")
                        if self.callbacks.on_conversion_complete:
                            self.callbacks.on_conversion_complete(wav_path)
                except Exception as e:
                    if self.callbacks.on_error:
                        self.callbacks.on_error(f"Conversion error: {e}")
                    if self.callbacks.on_conversion_complete:
                        self.callbacks.on_conversion_complete(wav_path)
                finally:
                    self._set_state(RecordingState.IDLE)

            threading.Thread(target=convert, daemon=True).start()
        else:
            self._set_state(RecordingState.IDLE)

    def _record_loop(self) -> None:
        """Recording loop running in separate thread."""
        last_time_update = 0.0

        while not self._stop_event.is_set():
            recorder = self._recorder
            writer = self._writer

            if recorder and writer:
                chunk = recorder.get_mixed_chunk(timeout=0.05)

                if chunk is not None and self._state == RecordingState.RECORDING:
                    writer.write(chunk)

                    # Notify audio chunk for waveform
                    if self.callbacks.on_audio_chunk:
                        self.callbacks.on_audio_chunk(chunk)

                # Update individual levels for meters
                if self.callbacks.on_loopback_level:
                    loopback_chunk = recorder.get_loopback_level_chunk()
                    self.callbacks.on_loopback_level(loopback_chunk)

                if self.callbacks.on_mic_level:
                    mic_chunk = recorder.get_mic_level_chunk()
                    self.callbacks.on_mic_level(mic_chunk)

            # Update time every 100ms
            now = time.time()
            if now - last_time_update > 0.1:
                if self.callbacks.on_time_update:
                    self.callbacks.on_time_update(self.elapsed_time)
                last_time_update = now

    def cleanup(self) -> None:
        """Cleanup resources."""
        self.stop_monitoring()
        self.stop_recording()
