"""Small offline check: real mixer, independent tracks, UTF-8 handoff export."""
import sys
import tempfile
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import numpy as np
import soundfile as sf
from recorder import Recorder, StreamConfig
from writer import AudioWriter
from handoff import write_handoff, session_name, clipboard_prompt


def main():
    with tempfile.TemporaryDirectory(prefix='wavegrab-') as tmp:
        folder = Path(tmp) / session_name('中文会议')
        folder.mkdir()
        recorder = Recorder(StreamConfig(0, 2, 48000), StreamConfig(1, 1, 44100),
                            track_directory=folder)

        class Capture:
            error = ''
            def __init__(self, samples, last=False):
                self.samples, self.last = samples, last
            def get_chunk_blocking(self, timeout):
                if self.last:
                    recorder._running = False
                return self.samples

        recorder._loopback = Capture(np.full(1920 * 2, 1000, dtype=np.float32))
        recorder._mic = Capture(np.full(1764, 3000, dtype=np.float32), last=True)
        for name, rate, channels in [('system', 48000, 2), ('mic', 44100, 1)]:
            writer = AudioWriter(folder, rate, channels, format='FLAC')
            writer.start(name + '.flac')
            recorder._track_writers[name] = writer
        recorder._running = True
        recorder._mix_loop()
        mixed = recorder.get_mixed_chunk()
        assert mixed.size == 3840 and np.all(mixed == 2000)
        writer = AudioWriter(folder, 48000, 2, format='FLAC')
        writer.start('mixed.flac')
        writer.write(mixed)
        writer.stop()
        for track in recorder._track_writers.values():
            track.stop()
        write_handoff(folder, '中文会议', {}, .04)
        data = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        assert set(data['audio_files']) == {'mixed.flac', 'system.flac', 'mic.flac'}
        assert sf.info(folder / 'mic.flac').frames == 1764
        assert 'transcript.clean.md' in (folder / 'HANDOFF.md').read_text(encoding='utf-8')
        assert str(folder) in clipboard_prompt(folder)
        assert session_name('会议') != session_name('会议')

        # A never-written SoundFile has false truthiness but must still close.
        empty = AudioWriter(folder, format='FLAC')
        empty_path = empty.start('empty.flac')
        handle = empty._file
        empty.stop()
        assert handle.closed and not empty.is_open

        # Silent loopback still occupies the same 40 ms as the microphone.
        recorder.source_frames = {'system': 0, 'mic': 0}
        recorder._track_writers = {}
        recorder._loopback = Capture(None)
        recorder._mic = Capture(np.full(1764, 3000, dtype=np.float32), last=True)
        recorder._running = True
        recorder._mix_loop()
        mixed = recorder.get_mixed_chunk()
        assert mixed.size == 3840 and np.all(mixed == 1500)
        assert '系统声音' in recorder.missing_source_error()

        # Controller must not publish a successful session for a missing source.
        from gui.controller import RecordingController, RecordingState
        controller = RecordingController()
        controller.last_session = folder
        controller._state = RecordingState.RECORDING
        class MissingSource:
            error = ''
            def stop(self): pass
            def missing_source_error(self): return '系统声音未收到音频采样'
        controller._recorder = MissingSource()
        controller.stop_recording()
        metadata = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        assert metadata['status'] == 'incomplete' and '系统声音' in metadata['error']

        # Room mode must ignore even a previously selected loopback device.
        from devices import AudioDevice
        speaker = AudioDevice(10, 'Test output', 2, 48000, True)
        microphone = AudioDevice(11, 'Test mic', 1, 48000, False)
        controller = RecordingController()
        controller.set_loopback_device(speaker)
        controller.set_mic_device(microphone)
        assert controller.room_mode
        selected = controller._make_recorder()
        assert selected.loopback_config is None and selected.mic_config.device_index == 11
        controller.set_room_mode(False)
        assert controller._make_recorder().loopback_config.device_index == 10
        muted = Recorder(mic_config=StreamConfig(11, 1, 48000))
        muted.source_frames['mic'] = 1920
        assert '全为零' in muted.missing_source_error()

        # Exercise UI selection without accessing any real audio devices.
        from unittest.mock import patch
        from config import AppConfig
        from gui.app import AudioRecorderApp
        with patch('gui.app.get_devices', return_value=[speaker, microphone]), \
             patch('gui.app.get_default_devices', return_value=(10, 11)), \
             patch('gui.app.load_config', return_value=AppConfig(auto_mode=False)):
            app = AudioRecorderApp()
            app.root.withdraw()
            try:
                assert str(app.loopback_combo['state']) == 'disabled'
                assert app.controller._make_recorder().loopback_config is None
                app.room_mode_var.set(False)
                app._on_room_mode_change()
                assert str(app.loopback_combo['state']) == 'readonly'
                assert app.controller._make_recorder().loopback_config.device_index == 10
                assert not AppConfig.from_dict(AppConfig(room_mode=False).to_dict()).room_mode
            finally:
                app.root.destroy()
    print('OK: mixing, silent-source timing, empty FLAC close, incomplete status, UTF-8 handoff')


if __name__ == '__main__':
    main()
