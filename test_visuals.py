"""Offline screenshot, bookmark and tray behavior; no audio or desktop capture."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from visuals import VisualTimeline, WindowSnapshots, WindowTarget


class VisualTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wavegrab-visual-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.seconds = 0
        self.timeline = VisualTimeline(self.folder, lambda: self.seconds)
        self.addCleanup(self.timeline.finish)

    def events(self):
        return [json.loads(line) for line in (self.folder / 'timeline.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_compressed_bounded_deduplicated_and_bookmarked(self):
        source = Image.new('RGB', (3840, 2160), 'navy')
        self.timeline.snapshot(source, 1.25)
        self.timeline.snapshot(source, 4.25)
        self.seconds = 7.5
        self.assertEqual(self.timeline.mark()['seconds'], 7.5)
        self.timeline.note('</script><script>alert(1)</script>')
        self.timeline.finish()
        frames = [e for e in self.events() if e['type'] == 'frame']
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]['seconds'], 1.25)
        with Image.open(self.folder / frames[0]['file']) as image:
            self.assertEqual(image.size, (1280, 720))
            self.assertEqual(image.format, 'JPEG')
        self.assertLess((self.folder / frames[0]['file']).stat().st_size, 20000)
        html = (self.folder / 'review.html').read_text(encoding='utf-8')
        self.assertIn('audio.currentTime=t', html)
        self.assertIn('标记 1', html)
        self.assertNotIn('</script><script>alert', html)
        self.assertIsNone(self.timeline.mark())

    def test_window_only_paused_minimized_and_cadence(self):
        active = True
        screen = WindowSnapshots(WindowTarget(123, 1, 'meeting'), self.timeline, lambda: active, Mock())
        frame = SimpleNamespace(frame_buffer=np.zeros((90, 160, 4), dtype=np.uint8))
        with patch('visuals.window_status', return_value=''), patch('visuals.time.monotonic', return_value=10):
            screen._frame(frame, Mock())
            frame.frame_buffer[:] = 200
            screen._frame(frame, Mock())
        self.assertEqual(self.timeline.frames, 1)
        with patch('visuals.window_status', return_value='窗口已最小化'), patch('visuals.time.monotonic', return_value=14):
            screen._frame(frame, Mock())
        self.assertEqual(self.timeline.frames, 1)
        active = False
        with patch('visuals.window_status', return_value=''), patch('visuals.time.monotonic', return_value=14):
            screen._frame(frame, Mock())
        self.assertEqual(self.timeline.frames, 1)
        active = True
        with patch('visuals.window_status', return_value=''), patch('visuals.time.monotonic', return_value=15):
            screen._frame(frame, Mock())
        self.assertEqual(self.timeline.frames, 2)

    def test_exact_window_handle_and_no_desktop_fallback(self):
        screen = WindowSnapshots(WindowTarget(123, 1, 'meeting'), self.timeline, lambda: True, Mock())
        with patch('visuals.window_status', return_value=''), patch('windows_capture.WindowsCapture') as capture:
            screen.start()
            capture.assert_called_once_with(window_hwnd=123, cursor_capture=False, draw_border=False,
                secondary_window=False, minimum_update_interval=3000)
            screen.stop()
            capture.return_value.start_free_threaded.return_value.stop.assert_called_once()
        with patch('visuals.window_status', return_value='窗口已关闭'), patch('windows_capture.WindowsCapture') as capture:
            with self.assertRaises(ValueError):
                screen.start()
            capture.assert_not_called()

    def test_recording_lifecycle_markers_follow_pause_clock(self):
        from devices import AudioDevice
        from gui.controller import RecordingController
        controller = RecordingController()
        controller.set_output_folder(self.folder)
        controller.set_mic_device(AudioDevice(1, 'fake', 1, 48000, False))
        recorder = Mock(error='')
        recorder.get_mixed_chunk.side_effect = lambda **_: (time.sleep(.01) or None)
        recorder.missing_source_error.return_value = ''
        with patch.object(controller, '_make_recorder', return_value=recorder):
            self.assertTrue(controller.start_recording())
            controller.pause_recording()
            a = controller.add_marker()
            time.sleep(.03)
            b = controller.add_marker()
            self.assertEqual(a['seconds'], b['seconds'])
            controller.resume_recording()
            controller.stop_recording()
        self.assertIsNone(controller.add_marker())
        self.assertTrue((controller.last_session / 'review.html').exists())
        session = json.loads((controller.last_session / 'session.json').read_text(encoding='utf-8'))
        self.assertIn('timeline.jsonl', session['visual_files'])

    def test_hotkeys_use_alt_and_unregister(self):
        from desktop import DesktopControls
        controls = DesktopControls.__new__(DesktopControls)
        controls.post = Mock()
        controls.report = Mock()
        controls.toggle, controls.mark = Mock(), Mock()
        controls.hotkey_ready = threading.Event()
        api = Mock()
        api.user32.RegisterHotKey.return_value = True
        api.user32.GetMessageW.return_value = 0
        with patch('desktop.ctypes.windll', api):
            controls._hotkeys()
        self.assertEqual([c.args for c in api.user32.RegisterHotKey.call_args_list],
                         [(None, 1, 0x4001, ord('R')), (None, 2, 0x4001, ord('M'))])
        self.assertEqual(api.user32.UnregisterHotKey.call_count, 2)

    def test_status_and_markers_use_tooltip_without_notifications(self):
        from desktop import DesktopControls
        controls = DesktopControls.__new__(DesktopControls)
        controls.state = '就绪'
        controls.icon = Mock()
        controls.update('录音中')
        controls.set_detail('标记 1 · 00:12')
        self.assertIn('录音中 · 标记 1', controls.icon.title)
        controls.set_detail('请重新选择会议窗口', error=True)
        self.assertIn('请重新选择会议窗口', controls.icon.title)
        controls.icon.notify.assert_not_called()
        idle = controls._image('就绪')
        recording = controls._image('录音中')
        self.assertEqual(idle.getpixel((12, 32)), recording.getpixel((12, 32)))
        self.assertNotEqual(idle.getpixel((52, 52)), recording.getpixel((52, 52)))

    def test_close_hides_without_stopping_and_hotkey_routes(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        from gui.controller import RecordingState
        with patch('gui.app.get_devices', return_value=[]), patch('gui.app.load_config', return_value=AppConfig()):
            app = AudioRecorderApp()
        try:
            app.room_mode_var.set(False)
            app._on_room_mode_change()
            app.root.update_idletasks()
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            for button in descendants(app.root):
                if 'text' in button.keys() and button.cget('text') in ('开始录音', '回看画面与标记'):
                    self.assertLessEqual(button.winfo_rooty() + button.winfo_height(),
                                         app.root.winfo_rooty() + app.root.winfo_height())
            app.desktop = Mock()
            app.desktop.ready.is_set.return_value = True
            with patch.object(app, '_save_config'), patch.object(app.controller, 'cleanup') as cleanup:
                app._on_close()
                self.assertEqual(app.root.state(), 'withdrawn')
                cleanup.assert_not_called()
                app._report_error('窗口已关闭，截图停止')
                self.assertEqual(app.root.state(), 'withdrawn')
                self.assertIn('窗口已关闭', app.status_var.get())
                app.desktop.set_detail.assert_called_with('窗口已关闭，截图停止', error=True)
                app._show_completion(self.folder)
                self.assertIn('窗口已关闭', app.status_var.get())
            with patch.object(app, '_on_rec') as start, patch.object(app, '_on_stop') as stop:
                app._toggle_recording()
                start.assert_called_once()
                app.controller._state = RecordingState.RECORDING
                app._toggle_recording()
                stop.assert_called_once()
            app._show_window()
            self.assertEqual(app.root.state(), 'normal')
        finally:
            app.root.destroy()


if __name__ == '__main__':
    unittest.main()
