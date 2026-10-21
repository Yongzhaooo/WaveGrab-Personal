"""Offline regression checks for real storage/exports and GUI; never opens audio devices."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from transcript_store import (RAW, edit_segment, export_result, install_result, load_names,
                              load_result, rename_speaker, validate_result)
from transcribe_worker import align_words

SAMPLE = {'schema_version': 1, 'segments': [
    {'id': 'seg_00001', 'start': 0.0, 'end': 1.2, 'speaker': 'speaker_1', 'text': 'Speaker 1 is a label.'},
    {'id': 'seg_00002', 'start': 1.3, 'end': 2.5, 'speaker': 'speaker_2', 'text': '这是另一位。'},
    {'id': 'seg_00003', 'start': 2.6, 'end': 4.0, 'speaker': 'speaker_1', 'text': 'I am back.'},
]}


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wavegrab-transcripts-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / '会议'
        install_result(self.folder, copy.deepcopy(SAMPLE))

    def test_global_rename_preserves_raw_and_other_people(self):
        raw = (self.folder / RAW).read_bytes()
        raw_md = (self.folder / 'transcript.raw.md').read_bytes()
        edit_segment(self.folder, 'seg_00003', '校正后的文字，不改变说话人。')
        rename_speaker(self.folder, 'speaker_1', '现场甲')
        for name in ['transcript.md', 'transcript.srt', 'transcript.clean.md']:
            text = (self.folder / 'exports' / name).read_text(encoding='utf-8')
            self.assertEqual(text.count('现场甲'), 2)
            self.assertIn('Speaker 2', text)
        self.assertIn('Speaker 1 is a label.', (self.folder / 'exports/transcript.md').read_text(encoding='utf-8'))
        self.assertEqual((self.folder / RAW).read_bytes(), raw)
        self.assertEqual((self.folder / 'transcript.raw.md').read_bytes(), raw_md)
        self.assertEqual(load_names(self.folder, load_result(self.folder))['speaker_1'], '现场甲')
        other = Path(self.temp.name) / '另一场'
        install_result(other, copy.deepcopy(SAMPLE))
        self.assertEqual(load_names(other, load_result(other)), {})

    def test_existing_results_are_not_overwritten(self):
        before = (self.folder / RAW).read_bytes()
        with self.assertRaises(FileExistsError):
            install_result(self.folder, {'schema_version': 1, 'segments': []})
        self.assertEqual((self.folder / RAW).read_bytes(), before)

    def test_successful_worker_starts_cleanup_only_after_install(self):
        from gui.transcripts import TranscriptPanel
        import threading
        folder = self.folder / 'new-recording'
        folder.mkdir()
        panel = Mock()
        panel.cancelled = threading.Event()
        def launch(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_text(json.dumps(SAMPLE), encoding='utf-8')
            process = Mock(stdout=[])
            process.wait.return_value = 0
            return process
        def clean(target):
            self.assertEqual(load_result(target), SAMPLE)
        with patch('gui.transcripts.subprocess.Popen', side_effect=launch), patch('gui.transcripts.start_cleanup', side_effect=clean) as cleanup:
            TranscriptPanel._run(panel, Path(sys.executable), Path('worker.py'), folder, folder, folder / 'mixed.flac', 0)
        cleanup.assert_called_once_with(folder)
        self.assertIsNone(panel.process)

    def test_imported_cleaning_updates_named_exports(self):
        (self.folder / 'transcript.edits.json').write_text(json.dumps({'seg_00002': '清洗后的中文'}), encoding='utf-8')
        rename_speaker(self.folder, 'speaker_2', '远端乙')
        clean = (self.folder / 'exports/transcript.clean.md').read_text(encoding='utf-8')
        self.assertIn('清洗后的中文', clean)
        self.assertIn('远端乙', clean)
        self.assertIn('已清洗 1 / 3', clean)

    def test_invalid_external_data_is_rejected(self):
        bad = copy.deepcopy(SAMPLE)
        bad['segments'][0]['end'] = float('nan')
        with self.assertRaises(ValueError):
            validate_result(bad)
        with self.assertRaises(ValueError):
            rename_speaker(self.folder, 'speaker_1', 'bad\nname')
        (self.folder / 'transcript.edits.json').write_text('{"missing": "text"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            export_result(self.folder)

    def test_word_alignment_distinguishes_turn_changes_and_overlap(self):
        turns = [{'start': 0, 'end': 1, 'speaker': 5}, {'start': 1, 'end': 2, 'speaker': 9},
                 {'start': 3, 'end': 4, 'speaker': 5}]
        words = [{'start': .1, 'end': .5, 'text': 'First'}, {'start': 1.1, 'end': 1.7, 'text': ' Second'},
                 {'start': 3.1, 'end': 3.8, 'text': ' Again'}, {'start': 5, 'end': 6, 'text': ' Unknown'}]
        result = align_words(words, turns)
        self.assertEqual([r['speaker'] for r in result], ['speaker_1', 'speaker_2', 'speaker_1', 'unknown'])
        overlap = align_words([words[0]], [turns[0], {'start': .1, 'end': .7, 'speaker': 9}])
        self.assertEqual(overlap[0]['speaker'], 'overlap')
        boundary = align_words([{'start': .8, 'end': 1.3, 'text': 'boundary'}], turns)
        self.assertEqual(boundary[0]['speaker'], 'speaker_2')

    def test_unknown_voice_is_not_renamed_as_a_person(self):
        words = [{'start': 0, 'end': 1, 'text': 'Uncertain'},
                 {'start': 2, 'end': 3, 'text': 'Known'}]
        turns = [{'start': 0, 'end': 1, 'speaker': 'unknown'},
                 {'start': 2, 'end': 3, 'speaker': 8}]
        self.assertEqual([s['speaker'] for s in align_words(words, turns)], ['unknown', 'speaker_1'])

    def test_gui_names_and_edits_refresh_all_rows_without_devices(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        with patch('gui.app.get_devices', return_value=[]), patch('gui.app.load_config', return_value=AppConfig()):
            app = AudioRecorderApp()
            app.root.withdraw()
            try:
                panel = app.result_panel
                panel.set_folder(self.folder)
                panel.speaker_var.set('Speaker 1')
                panel.name_var.set('会议室甲')
                panel.rename()
                self.assertEqual(panel.tree.item('seg_00001')['values'][1], '会议室甲')
                self.assertEqual(panel.tree.item('seg_00003')['values'][1], '会议室甲')
                self.assertEqual(panel.tree.item('seg_00002')['values'][1], 'Speaker 2')
                self.assertEqual(str(app.loopback_combo['state']), 'readonly')
                self.assertTrue(app.controller.room_mode)
                self.assertFalse(app.controller.is_recording)
            finally:
                app.root.destroy()

    def test_existing_transcript_prioritizes_content_and_settings_remain_available(self):
        from config import AppConfig
        from gui.app import AudioRecorderApp
        with patch('gui.app.get_devices', return_value=[]), patch('gui.app.load_config', return_value=AppConfig()):
            app = AudioRecorderApp()
        try:
            panel = app.result_panel
            panel.set_folder(self.folder)
            app.tabs.select(panel)
            app.root.update_idletasks()
            self.assertFalse(panel.settings_visible)
            self.assertEqual(panel.settings.winfo_manager(), '')
            self.assertGreater(panel.body.winfo_height(), panel.winfo_height() * .7)
            self.assertIn('Speaker 1 is a label.', panel.detail.get('1.0', 'end'))
            panel.toggle_settings()
            app.root.update_idletasks()
            self.assertEqual(panel.settings.winfo_manager(), 'pack')
            self.assertTrue(panel.rename_btn.winfo_ismapped())
            self.assertTrue(panel.audio_combo.winfo_ismapped())
            panel.toggle_settings()
            panel.busy = True
            panel._controls()
            self.assertEqual(panel.cancel_btn.winfo_manager(), 'pack')
            panel.busy = False
        finally:
            app.root.destroy()

    def test_virtual_cable_is_available_as_system_source(self):
        from devices import AudioDevice, get_system_sources
        from gui.controller import RecordingController, RecordingCallbacks
        cable = AudioDevice(21, 'CABLE Output (VB-Audio Virtual Cable)', 2, 48000, False)
        duplicate = AudioDevice(22, 'CABLE Input (VB-Audio Virtual Cable) [Loopback]', 2, 48000, True)
        physical = AudioDevice(25, 'Speakers (Realtek) [Loopback]', 2, 48000, True)
        mic = AudioDevice(20, 'Microphone Array', 2, 48000, False)
        self.assertEqual(get_system_sources([mic, cable, duplicate, physical]), [cable, physical])
        errors = []
        controller = RecordingController(RecordingCallbacks(on_error=errors.append))
        controller.set_room_mode(False)
        controller.set_loopback_device(cable)
        controller.set_mic_device(mic)
        recorder = controller._make_recorder()
        self.assertEqual(recorder.loopback_config.device_index, 21)
        self.assertEqual(recorder.mic_config.device_index, 20)
        controller.set_mic_device(cable)
        self.assertFalse(controller.start_recording())
        self.assertIn('同一设备', errors[0])


if __name__ == '__main__':
    unittest.main()
