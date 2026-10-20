"""Scene decisions and feedback without opening microphones or a live meeting."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from meeting import MeetingScene, cable_render_name, is_meeting_controls, _virtual_route_active
from visuals import WindowTarget


class MeetingTests(unittest.TestCase):
    def test_chat_and_prejoin_are_not_meeting_windows(self):
        controls = [('Leave (Ctrl+Shift+H)', 'hangup-button'), ('Mic (Ctrl+Shift+M)', ''), ('Camera', '')]
        self.assertTrue(is_meeting_controls('Project call | Microsoft Teams', controls))
        self.assertFalse(is_meeting_controls('Chat | Colleague | Microsoft Teams', controls))
        self.assertFalse(is_meeting_controls('Project call | Microsoft Teams', [('Join now', ''), ('Mic', ''), ('Camera', '')]))
        self.assertFalse(is_meeting_controls('Microsoft Teams', [('Leave channel', '')]))
        self.assertTrue(is_meeting_controls('项目会议', [('离开', ''), ('麦克风', ''), ('摄像头', '')]))

    def test_only_supported_virtual_input_and_one_window_can_auto_select(self):
        self.assertEqual(cable_render_name('CABLE Output (VB-Audio Virtual Cable)'), 'CABLE Input (VB-Audio Virtual Cable)')
        self.assertIsNone(cable_render_name('Speakers (Realtek) [Loopback]'))
        a, b = WindowTarget(1, 2, 'one'), WindowTarget(3, 4, 'two')
        self.assertEqual(MeetingScene([a], True).target, a)
        self.assertIsNone(MeetingScene([a, b], True).target)

    def test_virtual_route_requires_active_teams_audio_on_the_matching_endpoint(self):
        device = Mock(FriendlyName='CABLE Input (VB-Audio Virtual Cable)')
        sessions = device.AudioSessionManager.GetSessionEnumerator.return_value
        sessions.GetCount.return_value = 1
        process = Mock(pid=42)
        session = Mock(State=1, Process=process)
        with patch('pycaw.utils.AudioUtilities.GetAllDevices', return_value=[device]) as devices, \
             patch('pycaw.utils.AudioSession', return_value=session):
            self.assertTrue(_virtual_route_active(device.FriendlyName, {42}))
            devices.assert_called_with(data_flow=0, device_state=1)
            session.State = 0
            self.assertFalse(_virtual_route_active(device.FriendlyName, {42}))
            session.State = 1
            process.name.return_value = 'music.exe'
            process.parent.return_value = None
            self.assertFalse(_virtual_route_active(device.FriendlyName, set()))
            self.assertFalse(_virtual_route_active('Speakers (Realtek)', {42}))

    def setUp(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        with patch('gui.app.get_devices', return_value=[]), patch('gui.app.load_config', return_value=AppConfig()):
            self.app = AudioRecorderApp()
        self.app.root.withdraw()
        self.app.indicator = Mock()
        self.addCleanup(self.app.root.destroy)

    def test_no_teams_starts_room_recording_even_with_screenshots_enabled(self):
        app = self.app
        with patch.object(app, '_scan_scene', side_effect=lambda done: done(MeetingScene())), \
             patch.object(app.controller, 'start_recording', return_value=True) as start, patch.object(app, '_save_config'):
            app._on_rec()
        start.assert_called_once()
        self.assertTrue(app.controller.room_mode)
        self.assertIsNone(app.controller.screen_target)
        app.indicator.update.assert_called_with('准备中')

    def test_verified_virtual_call_binds_only_the_meeting_handle(self):
        app = self.app
        target = WindowTarget(123, 456, 'Actual call')
        with patch.object(app, '_scan_scene', side_effect=lambda done: done(MeetingScene([target], True))), \
             patch('gui.app.window_status', return_value=''), \
             patch.object(app.controller, 'start_recording', return_value=True) as start, patch.object(app, '_save_config'):
            app._on_rec()
        start.assert_called_once()
        self.assertFalse(app.controller.room_mode)
        self.assertEqual(app.controller.screen_target, target)

    def test_cancel_and_timeout_ignore_late_scene_results(self):
        app = self.app
        callbacks = []
        with patch.object(app, '_scan_scene', side_effect=callbacks.append), \
             patch.object(app.controller, 'start_recording', return_value=True) as start, patch.object(app, '_save_config'):
            app._on_rec()
            app._toggle_recording()
            callbacks.pop()(MeetingScene([WindowTarget(1, 1, 'Call')], True))
            start.assert_not_called()
            app._on_rec()
            token = app._start_pending
            app._finish_auto_start(token, MeetingScene(detail='timeout'))
            callbacks.pop()(MeetingScene([WindowTarget(1, 1, 'Call')], True))
            start.assert_called_once()
            self.assertTrue(app.controller.room_mode)
            self.assertIsNone(app.controller.screen_target)

    def test_marker_feedback_requires_a_saved_marker(self):
        with patch.object(self.app.controller, 'add_marker', return_value={'label': '标记 1', 'seconds': 12}):
            self.app._add_marker()
            self.app.indicator.flash.assert_called_with('marker')
        with patch.object(self.app.controller, 'add_marker', return_value=None):
            self.app._add_marker()
            self.app.indicator.flash.assert_called_with('error')
            self.assertIn('开始后', self.app.status_var.get())

    def test_native_indicator_preserves_focus_and_allows_clicks_through(self):
        import ctypes
        from desktop import RecordingIndicator
        indicator = RecordingIndicator(self.app.root)
        try:
            user = ctypes.windll.user32
            user.GetForegroundWindow.restype = ctypes.c_void_p
            foreground = user.GetForegroundWindow()
            indicator.update('录音中')
            indicator.flash('marker')
            self.app.root.update()
            self.assertEqual(user.GetForegroundWindow(), foreground)
            style = user.GetWindowLongPtrW(indicator.hwnd, -20)
            self.assertEqual(style & 0x080000A0, 0x080000A0)
        finally:
            indicator.close()

    def test_changed_window_identity_suspends_capture(self):
        from visuals import window_status
        api = Mock()
        api.GetWindowThreadProcessId.side_effect = lambda hwnd, pid: setattr(pid._obj, 'value', 456)
        api.IsWindow.return_value = True
        api.GetWindowTextW.side_effect = lambda hwnd, text, length: setattr(text, 'value', 'Chat | Microsoft Teams')
        with patch('visuals.ctypes.windll.user32', api):
            self.assertIn('标题已变化', window_status(WindowTarget(123, 456, 'Actual meeting')))


if __name__ == '__main__':
    unittest.main()
