"""Recording orchestration and agent-neutral session export."""

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

import numpy as np

from devices import AudioDevice
from recorder import Recorder, StreamConfig
from writer import AudioWriter
from handoff import session_name, write_handoff


class RecordingState(Enum):
    IDLE = auto()
    MONITORING = auto()
    RECORDING = auto()
    PAUSED = auto()
    CONVERTING = auto()


@dataclass
class RecordingCallbacks:
    on_state_change: Callable | None = None
    on_time_update: Callable | None = None
    on_audio_chunk: Callable | None = None
    on_loopback_level: Callable | None = None
    on_mic_level: Callable | None = None
    on_error: Callable | None = None
    on_conversion_complete: Callable | None = None


class RecordingController:
    def __init__(self, callbacks=None):
        self.callbacks = callbacks or RecordingCallbacks()
        self._state = RecordingState.IDLE
        self._recorder = None
        self._writer = None
        self._loopback_device = None
        self._mic_device = None
        self._loopback_volume = self._mic_volume = 1.0
        self._output_folder = Path.home() / 'Music' / 'WaveGrab'
        self._filename_prefix = ''
        self._record_thread = None
        self._stop_event = threading.Event()
        self._stop_lock = threading.Lock()
        self._start_time = self._pause_start = self._total_paused = 0.0
        self.last_session = None
        self._error = ''
        self._session_devices = {}
        self._session_title = ''

    def _notify(self, name, value):
        callback = getattr(self.callbacks, name)
        if callback:
            callback(value)

    @property
    def state(self):
        return self._state

    @property
    def is_recording(self):
        return self._state in (RecordingState.RECORDING, RecordingState.PAUSED)

    @property
    def elapsed_time(self):
        if self._state == RecordingState.IDLE:
            return 0.0
        end = self._pause_start if self._state == RecordingState.PAUSED else time.monotonic()
        return max(0.0, end - self._start_time - self._total_paused)

    def _set_state(self, state):
        self._state = state
        self._notify('on_state_change', state)

    def set_loopback_device(self, device):
        self._loopback_device = device

    def set_mic_device(self, device):
        self._mic_device = device

    def set_loopback_volume(self, volume):
        self._loopback_volume = max(0.0, min(1.0, volume))
        if self._recorder:
            self._recorder.set_loopback_volume(self._loopback_volume)

    def set_mic_volume(self, volume):
        self._mic_volume = max(0.0, min(1.0, volume))
        if self._recorder:
            self._recorder.set_mic_volume(self._mic_volume)

    def set_output_folder(self, folder):
        self._output_folder = Path(folder).expanduser()

    def set_filename_prefix(self, prefix):
        self._filename_prefix = prefix

    def get_output_filename(self):
        return session_name(self._filename_prefix) + '/mixed.flac'

    def _make_recorder(self, folder=None):
        def config(device, volume):
            return StreamConfig(device.index, device.channels, device.sample_rate, volume) if device else None
        return Recorder(config(self._loopback_device, self._loopback_volume),
                        config(self._mic_device, self._mic_volume),
                        target_sample_rate=48000, track_directory=folder)

    def start_monitoring(self):
        return self._start(monitor=True)

    def start_recording(self):
        return self._start(monitor=False)

    def _start(self, monitor):
        if self._state not in (RecordingState.IDLE, RecordingState.MONITORING):
            return False
        self.stop_monitoring()
        if not self._loopback_device and not self._mic_device:
            self._notify('on_error', '请选择系统声音或麦克风设备。')
            return False
        self._error = ''
        folder = None
        try:
            if not monitor:
                folder = self._output_folder / session_name(self._filename_prefix)
                folder.mkdir(parents=True, exist_ok=False)
                self.last_session = folder
                self._session_title = self._filename_prefix
                self._session_devices = {'system': self._loopback_device, 'mic': self._mic_device}
                self._writer = AudioWriter(folder, 48000, 2, format='FLAC')
                self._writer.start('mixed.flac')
                write_handoff(folder, self._session_title, self._session_devices, 0, 'recording')
            self._recorder = self._make_recorder(folder)
            self._recorder.start()
        except Exception as exc:
            if self._recorder:
                self._recorder.stop()
                self._recorder = None
            if self._writer:
                self._writer.stop()
                self._writer = None
            if folder:
                write_handoff(folder, self._session_title, self._session_devices, 0, 'incomplete', str(exc))
            self._notify('on_error', f'无法开始录音：{exc}')
            return False
        self._stop_event.clear()
        self._start_time = time.monotonic()
        self._total_paused = 0
        self._set_state(RecordingState.MONITORING if monitor else RecordingState.RECORDING)
        self._record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._record_thread.start()
        return True

    def pause_recording(self):
        if self._state == RecordingState.RECORDING:
            self._recorder.pause()
            self._pause_start = time.monotonic()
            self._set_state(RecordingState.PAUSED)

    def resume_recording(self):
        if self._state == RecordingState.PAUSED:
            self._total_paused += time.monotonic() - self._pause_start
            self._recorder.resume()
            self._set_state(RecordingState.RECORDING)

    def stop_monitoring(self):
        if self._state == RecordingState.MONITORING:
            self.stop_recording()

    def stop_recording(self):
        with self._stop_lock:
            if self._state in (RecordingState.IDLE, RecordingState.CONVERTING):
                return
            monitor = self._state == RecordingState.MONITORING
            duration = self.elapsed_time
            self._set_state(RecordingState.CONVERTING)
            try:
                if self._recorder:
                    self._recorder.stop()
                    self._error = self._error or self._recorder.error
                self._stop_event.set()
                if self._record_thread:
                    self._record_thread.join()
                if self._writer:
                    duration = self._writer.duration_seconds
                    self._writer.stop()
                if not monitor and self.last_session:
                    write_handoff(self.last_session, self._session_title,
                                  self._session_devices, duration,
                                  'incomplete' if self._error else 'complete', self._error)
            except Exception as exc:
                self._error = self._error or str(exc)
            finally:
                self._recorder = self._writer = self._record_thread = None
                self._set_state(RecordingState.IDLE)
            if self._error:
                self._notify('on_error', '录音已停止，已录文件保留：' + self._error)
            if not monitor and self.last_session:
                self._notify('on_conversion_complete', self.last_session)

    def _record_loop(self):
        last_update = 0.0
        try:
            while True:
                recorder = self._recorder
                chunk = recorder.get_mixed_chunk(timeout=0.04)
                if chunk is not None and self._writer:
                    self._writer.write(chunk)
                if self._stop_event.is_set() and chunk is None:
                    break
                if recorder.error:
                    raise RuntimeError(recorder.error)
                now = time.monotonic()
                if now - last_update >= 0.05:
                    self._notify('on_audio_chunk', chunk)
                    self._notify('on_loopback_level', recorder.get_loopback_level_chunk())
                    self._notify('on_mic_level', recorder.get_mic_level_chunk())
                    self._notify('on_time_update', self.elapsed_time)
                    last_update = now
        except Exception as exc:
            self._error = str(exc)
            threading.Thread(target=self.stop_recording, daemon=True).start()

    def cleanup(self):
        self.stop_recording()
