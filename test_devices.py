import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from devices import AudioDevice, get_devices
from recorder import Recorder, StreamConfig


class DeviceTests(unittest.TestCase):
    def test_enumeration_uses_capture_instance_without_terminating_it(self):
        api = Mock()
        api.get_host_api_info_by_type.return_value = {'index': 2}
        api.get_device_count.return_value = 2
        api.get_device_info_by_index.side_effect = [
            {'hostApi': 2, 'maxInputChannels': 1, 'defaultSampleRate': 16000,
             'name': 'Headset (Bluetooth)'},
            {'hostApi': 2, 'maxInputChannels': 2, 'defaultSampleRate': 48000,
             'name': 'Headphones (Bluetooth) [Loopback]', 'isLoopbackDevice': True}]
        devices = get_devices(api)
        self.assertEqual([(d.channels, d.sample_rate) for d in devices], [(1, 16000), (2, 48000)])
        api.terminate.assert_not_called()

    def test_capture_rebinds_stale_index_and_bluetooth_format_before_open(self):
        api = Mock()
        current = AudioDevice(26, 'Headset (Bluetooth)', 1, 16000, False)
        cfg = StreamConfig(20, 2, 48000, device_name=current.name)
        recorder = Recorder(mic_config=cfg)
        with patch('recorder.pyaudio.PyAudio', return_value=api), \
             patch('recorder.get_devices', return_value=[current]) as enumerate_devices, \
             patch('recorder.threading.Thread'):
            recorder.start()
            enumerate_devices.assert_called_once_with(api)
            self.assertEqual(api.open.call_args.kwargs['input_device_index'], 26)
            self.assertEqual(api.open.call_args.kwargs['channels'], 1)
            self.assertEqual(api.open.call_args.kwargs['rate'], 16000)
            recorder.stop()

    def test_disconnected_selection_does_not_capture_another_device_at_old_index(self):
        api = Mock()
        recorder = Recorder(mic_config=StreamConfig(20, 2, 48000, device_name='Bluetooth mic'))
        with patch('recorder.pyaudio.PyAudio', return_value=api), \
             patch('recorder.get_devices', return_value=[AudioDevice(20, 'Other mic', 2, 48000, False)]):
            with self.assertRaisesRegex(ValueError, 'Bluetooth mic'):
                recorder.start()
        api.open.assert_not_called()
        api.terminate.assert_called_once()

    def test_dropdown_refresh_discovers_bluetooth_and_preserves_selection(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        from gui.controller import RecordingState
        mic = AudioDevice(10, 'Internal mic', 2, 48000, False)
        output = AudioDevice(11, 'Speaker [Loopback]', 2, 48000, True)
        bluetooth = AudioDevice(26, 'Headset (Bluetooth)', 1, 16000, False)
        fresh = [AudioDevice(25, mic.name, 2, 48000, False), output, bluetooth,
                 AudioDevice(30, 'Headphones (Bluetooth) [Loopback]', 2, 48000, True)]
        config = AppConfig(mic_device=mic.name, loopback_device=output.name)
        with patch('gui.app.get_devices', return_value=[mic, output]) as enumerate_devices, \
             patch('gui.app.load_config', return_value=config):
            app = AudioRecorderApp()
            app.root.withdraw()
            try:
                enumerate_devices.return_value = fresh
                # Invoke the real combobox hook, as opening the dropdown does.
                app.mic_combo.tk.call(app.mic_combo.cget('postcommand'))
                self.assertIn('Headset (Bluetooth) [16000Hz]', app.mic_combo['values'])
                self.assertIn('Headphones (Bluetooth) [Loopback] [48000Hz]', app.loopback_combo['values'])
                self.assertEqual(app.controller._mic_device.index, 25)
                app.mic_combo.current(2)
                app._on_mic_change(None)
                enumerate_devices.return_value = [*fresh[:2], AudioDevice(40, bluetooth.name, 1, 32000, False)]
                self.assertTrue(app._refresh_devices())
                self.assertEqual(app.controller._make_recorder().mic_config.device_name, bluetooth.name)
                self.assertEqual(app.controller._mic_device.sample_rate, 32000)
                app.controller._state = RecordingState.RECORDING
                enumerate_devices.reset_mock()
                self.assertFalse(app._refresh_devices())
                enumerate_devices.assert_not_called()
                app.controller._state = RecordingState.IDLE
                enumerate_devices.return_value = fresh[:2]
                self.assertFalse(app._refresh_devices())
                self.assertIsNone(app.controller._mic_device)
                self.assertIn('设备已断开', app.status_var.get())
            finally:
                app.root.destroy()


if __name__ == '__main__':
    unittest.main()
