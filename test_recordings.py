import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from transcript_store import (RAW, export_result, focused_result, install_result, list_recordings,
                              load_details, load_result, rename_speaker, save_details)

SAMPLE = {'schema_version': 1, 'segments': [
    {'id': 'seg_00001', 'start': 0., 'end': 8., 'speaker': 'speaker_1', 'text': 'Main person one'},
    {'id': 'seg_00002', 'start': 8., 'end': 15., 'speaker': 'speaker_2', 'text': 'Quiet colleague'},
    {'id': 'seg_00003', 'start': 15., 'end': 35., 'speaker': 'speaker_3', 'text': 'Background conversation'},
    {'id': 'seg_00004', 'start': 35., 'end': 36., 'speaker': 'unknown', 'text': 'Uncertain speech'},
    {'id': 'seg_00005', 'start': 36., 'end': 37., 'speaker': 'overlap', 'text': 'Overlapping speech'},
], 'speaker_stats': {'speaker_1': {'rms_db': -15}, 'speaker_2': {'rms_db': -22}, 'speaker_3': {'rms_db': -45}}}


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wavegrab-library-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / '2026-10-21_095843_000000_recording'
        self.folder.mkdir()
        self.session = {'duration_seconds': 67.28, 'status': 'complete', 'created_at': '2026-10-21T09:59:52+02:00'}
        (self.folder / 'session.json').write_text(json.dumps(self.session), encoding='utf-8')
        install_result(self.folder, copy.deepcopy(SAMPLE))

    def test_date_note_scene_persist_without_touching_originals(self):
        raw = (self.folder / RAW).read_bytes()
        session = (self.folder / 'session.json').read_bytes()
        save_details(self.folder, note='与同事讨论\n保留主要对话', scene='desk')
        rows = list_recordings(self.root)
        self.assertEqual(rows[0]['date'], '2026-10-21 09:58:43')
        self.assertEqual(rows[0]['scene'], 'desk')
        self.assertIn('同事', rows[0]['note'])
        self.assertEqual((self.folder / RAW).read_bytes(), raw)
        self.assertEqual((self.folder / 'session.json').read_bytes(), session)
        before = (self.folder / 'recording.json').read_bytes()
        with self.assertRaises(ValueError):
            save_details(self.folder, note='x' * 2001)
        self.assertEqual((self.folder / 'recording.json').read_bytes(), before)

    def test_desk_filter_keeps_uncertainty_and_is_reversible(self):
        raw = (self.folder / RAW).read_bytes()
        save_details(self.folder, scene='desk')
        data, _, _ = export_result(self.folder)
        view, excluded, chosen = focused_result(self.folder, data)
        self.assertEqual(chosen, ['speaker_1', 'speaker_2'])
        self.assertEqual([s['speaker'] for s in excluded], ['speaker_3'])
        self.assertIn('unknown', [s['speaker'] for s in view['segments']])
        self.assertIn('overlap', [s['speaker'] for s in view['segments']])
        self.assertNotIn('Background conversation', (self.folder / 'exports/transcript.md').read_text(encoding='utf-8'))
        self.assertIn('Background conversation', (self.folder / 'exports/transcript.full.md').read_text(encoding='utf-8'))
        self.assertIn('Uncertain speech', (self.folder / 'exports/transcript.review.md').read_text(encoding='utf-8'))
        save_details(self.folder, focus_speakers=['speaker_1', 'speaker_3'])
        rename_speaker(self.folder, 'speaker_3', '实际同事')
        self.assertIn('实际同事', (self.folder / 'exports/transcript.md').read_text(encoding='utf-8'))
        save_details(self.folder, scene='meeting')
        export_result(self.folder)
        self.assertIn('Quiet colleague', (self.folder / 'exports/transcript.md').read_text(encoding='utf-8'))
        self.assertEqual((self.folder / RAW).read_bytes(), raw)

    def test_library_and_transcript_ui_share_selection(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        with patch('gui.app.get_devices', return_value=[]), patch('gui.app.load_config', return_value=AppConfig(output_folder=str(self.root))):
            app = AudioRecorderApp()
        app.root.withdraw()
        try:
            panel = app.recordings_panel
            panel.refresh()
            self.assertEqual(panel.folder, self.folder)
            audio = self.folder / 'mixed.flac'
            audio.write_bytes(b'fixture')
            panel.update_files()
            self.assertEqual(str(panel.audio_btn['state']), 'normal')
            self.assertEqual(str(panel.clean_btn['state']), 'disabled')
            with patch('gui.recordings.subprocess.Popen') as reveal:
                panel.open_audio()
                reveal.assert_called_once_with(['explorer.exe', '/select,', str(audio)])
            (self.folder / 'exports/transcript.clean.md').write_text('clean', encoding='utf-8')
            panel.update_files()
            self.assertEqual(str(panel.clean_btn['state']), 'normal')
            with patch('gui.recordings.subprocess.Popen') as reveal:
                panel.open_clean()
                self.assertEqual(reveal.call_args.args[0][-1], str(self.folder / 'exports/transcript.clean.md'))
            panel.note.insert('1.0', 'Desk note')
            panel.scene.set('Desk · 主要对话')
            panel.save()
            panel.open_selected()
            self.assertEqual(app.result_panel.folder, self.folder.resolve())
            self.assertNotIn('seg_00003', app.result_panel.tree.get_children())
            app.result_panel.show_all.set(True)
            app.result_panel.reload()
            self.assertIn('seg_00003', app.result_panel.tree.get_children())
            self.assertEqual(load_details(self.folder)['note'], 'Desk note')
            empty = self.root / 'empty'
            empty.mkdir()
            app.output_folder_var.set(str(empty))
            panel.refresh()
            self.assertIsNone(panel.folder)
            self.assertEqual(panel.note.get('1.0', 'end-1c'), '')
        finally:
            app.root.destroy()

    def test_quantization_noise_is_not_reported_as_usable_microphone(self):
        from recorder import Recorder, StreamConfig
        recorder = Recorder(None, StreamConfig(1, 2, 48000, 1.0))
        recorder.source_frames['mic'] = 48000
        recorder.source_peaks['mic'] = 1
        self.assertIn('量化底噪', recorder.missing_source_error())
        recorder.source_peaks['mic'] = 200
        self.assertEqual(recorder.missing_source_error(), '')


if __name__ == '__main__':
    unittest.main()
