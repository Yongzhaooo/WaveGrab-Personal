import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import agent_cli
from cleanup import clean, session_lock
from transcript_store import RAW, SUMMARY, install_result, save_details
from test_recordings import SAMPLE


class AgentCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='wavegrab-agent-')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.root = self.home / 'recordings'
        self.folder = self.root / '2026-10-21_095843_000000_recording'
        install_result(self.folder, SAMPLE)
        (self.folder / 'session.json').write_text('{"status":"complete"}', encoding='utf-8')
        (self.home / 'config.json').write_text(json.dumps({'output_folder': str(self.root)}), encoding='utf-8')
        self.input = self.home / 'summary.json'
        self.input.write_text(json.dumps({'markdown': '讨论笔记', 'source_ids': ['seg_00001'], 'notes': ''}), encoding='utf-8')

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = agent_cli.main(['--home', str(self.home), *args])
        value = json.loads(output.getvalue())
        self.assertEqual(value['ok'], code == 0)
        return code, value

    def test_discover_and_context_use_selected_recording(self):
        _, listing = self.run_cli('list', '--date', '2026-10-21')
        self.assertEqual(listing['recordings'][0]['id'], self.folder.name)
        save_details(self.folder, scene='desk', note='同事讨论')
        code, value = self.run_cli('context', self.folder.name)
        self.assertEqual(code, 0)
        self.assertEqual(value['recording']['note'], '同事讨论')
        self.assertNotIn('seg_00003', [s['id'] for s in value['segments']])
        self.assertIn('seg_00004', [s['id'] for s in value['segments']])

    def test_import_preserves_original_and_requires_explicit_replace(self):
        before = (self.folder / RAW).read_bytes()
        code, value = self.run_cli('import-summary', self.folder.name, '--file', str(self.input))
        self.assertEqual(code, 0)
        self.assertTrue(Path(value['paths']['exports/summary.md']).is_file())
        saved = (self.folder / SUMMARY).read_bytes()
        self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input))[0], 1)
        self.input.write_text('{"markdown":"bad","source_ids":["fake"],"notes":""}', encoding='utf-8')
        self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input), '--replace')[0], 1)
        self.assertEqual((self.folder / RAW).read_bytes(), before)
        self.assertEqual((self.folder / SUMMARY).read_bytes(), saved)
        with self.assertRaisesRegex(ValueError, '--replace'):
            clean(self.folder, {}, replace=False)

    def test_imported_notes_render_speaker_names_and_origin(self):
        (self.folder / 'speakers.json').write_text('{"speaker_2": "Alice"}', encoding='utf-8')
        self.input.write_text(json.dumps({'markdown': '{{speaker_2}} 会合并', 'source_ids': ['seg_00001'],
                                          'notes': '归属：{{speaker_2}}'}), encoding='utf-8')
        self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input))[0], 0)
        notes = (self.folder / 'exports/summary-notes.md').read_text(encoding='utf-8')
        self.assertIn('外部 agent 导入', notes)
        self.assertNotIn('AGY', notes)
        self.assertIn('归属：Alice', notes)
        self.assertIn('Alice 会合并', (self.folder / 'exports/summary.md').read_text(encoding='utf-8'))
        self.input.write_text(json.dumps({'markdown': '笔记', 'source_ids': ['seg_00001'],
                                          'notes': '{{speaker_9}}'}), encoding='utf-8')
        self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input), '--replace')[0], 1)

    def test_busy_recording_lock_and_path_escape_are_rejected(self):
        with session_lock(self.folder):
            self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input))[0], 1)
        (self.folder / 'session.json').write_text('{"status":"recording"}', encoding='utf-8')
        self.assertEqual(self.run_cli('import-summary', self.folder.name, '--file', str(self.input))[0], 1)
        self.assertEqual(self.run_cli('show', '../outside')[0], 1)
        self.assertFalse((self.folder / SUMMARY).exists())

    def test_clean_calls_existing_pipeline_and_reports_failures(self):
        (self.home / 'cleanup-config.json').write_text('{"enabled":true}', encoding='utf-8')
        with patch('agent_cli.clean') as job:
            self.assertEqual(self.run_cli('clean', self.folder.name, '--replace')[0], 0)
            job.assert_called_once_with(self.folder, {'enabled': True}, replace=True)
        with patch('agent_cli.clean', side_effect=RuntimeError('AGY unavailable')):
            code, value = self.run_cli('clean', self.folder.name)
            self.assertEqual(code, 1)
            self.assertEqual(value['error'], 'AGY unavailable')


if __name__ == '__main__':
    unittest.main()
