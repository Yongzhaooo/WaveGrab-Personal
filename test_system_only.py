import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from config import AppConfig
from devices import AudioDevice
from gui.controller import RecordingController, RecordingCallbacks, RecordingState


class SystemOnlyTests(unittest.TestCase):
    def setUp(self):
        self.speaker = AudioDevice(30, 'Headphones [Loopback]', 2, 48000, True)
        self.mic = AudioDevice(26, 'Bluetooth microphone', 1, 16000, False)
        self.controller = RecordingController()
        self.controller.set_loopback_device(self.speaker)
        self.controller.set_mic_device(self.mic)
        self.controller.set_system_only(True)

    def test_record_and_input_check_never_open_microphone(self):
        recorder = self.controller._make_recorder()
        self.assertIsNone(recorder.mic_config)
        api = Mock()
        with patch('recorder.pyaudio.PyAudio', return_value=api), \
             patch('recorder.get_devices', return_value=[self.speaker, self.mic]), \
             patch('recorder.threading.Thread'):
            recorder.start()
            self.assertEqual(api.open.call_count, 1)
            self.assertEqual(api.open.call_args.kwargs['input_device_index'], self.speaker.index)
            recorder.stop()
        with patch.object(self.controller, '_make_recorder', return_value=Mock(error='')) as factory, \
             patch('gui.controller.threading.Thread'):
            self.assertTrue(self.controller.start_monitoring())
            factory.assert_called_once_with(None)
            self.assertIsNone(self.controller._capture_devices()['mic'])
            self.controller.stop_monitoring()

    def test_missing_output_fails_instead_of_using_selected_mic(self):
        errors = Mock()
        self.controller.callbacks = RecordingCallbacks(on_error=errors)
        self.controller.set_loopback_device(None)
        with patch.object(self.controller, '_make_recorder') as factory:
            self.assertFalse(self.controller.start_monitoring())
            factory.assert_not_called()
        self.assertIn('仅系统声音', errors.call_args.args[0])

    def test_session_metadata_excludes_mic_and_mode_cannot_change_while_recording(self):
        with tempfile.TemporaryDirectory(prefix='wavegrab-system-only-') as tmp:
            self.controller.set_output_folder(tmp)
            with patch('gui.controller.AudioWriter'), patch.object(self.controller, '_make_recorder', return_value=Mock()), \
                 patch('gui.controller.threading.Thread'), patch('gui.controller.VisualTimeline'):
                self.assertTrue(self.controller.start_recording())
                data = json.loads((self.controller.last_session / 'session.json').read_text(encoding='utf-8'))
                self.assertIsNone(data['devices']['mic'])
                self.assertEqual(data['devices']['system']['name'], self.speaker.name)
                self.assertFalse(self.controller.set_system_only(False))
                self.assertTrue(self.controller.system_only)

    def test_ui_mode_persists_and_preserves_mic_for_switching_back(self):
        from gui.app import AudioRecorderApp
        config = AppConfig(system_only=True, mic_device=self.mic.name, loopback_device=self.speaker.name)
        with patch('gui.app.get_devices', return_value=[self.mic, self.speaker]), \
             patch('gui.app.load_config', return_value=config):
            app = AudioRecorderApp()
        app.root.withdraw()
        try:
            self.assertTrue(app.controller.system_only)
            self.assertFalse(app.auto_mode_var.get())
            self.assertFalse(app.room_mode_var.get())
            self.assertEqual(str(app.mic_combo['state']), 'disabled')
            self.assertEqual(str(app.loopback_combo['state']), 'readonly')
            with patch('gui.app.save_config') as save:
                app._save_config()
                restored = AppConfig.from_dict(save.call_args.args[0].to_dict())
                self.assertTrue(restored.system_only)
                self.assertEqual(restored.mic_device, self.mic.name)
            app._update_ui_state(RecordingState.IDLE)
            self.assertEqual(str(app.mic_combo['state']), 'disabled')
            app.system_only_var.set(False)
            app._on_room_mode_change()
            self.assertEqual(app.controller._make_recorder().mic_config.device_name, self.mic.name)
        finally:
            app.root.destroy()


if __name__ == '__main__':
    unittest.main()
