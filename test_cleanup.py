import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import cleanup
from transcript_store import (RAW, SUMMARY, edit_segment, install_result, load_edits, load_result,
                              read_json, rename_speaker, save_details)
from test_recordings import SAMPLE


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wavegrab-cleanup-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        install_result(self.folder, copy.deepcopy(SAMPLE))
        skill = self.folder / 'humanizer.md'
        skill.write_text('HUMANIZER_FIXTURE: write natural prose.', encoding='utf-8')
        self.config = {'model': 'test-model', 'humanizer_skill': str(skill)}
        transcript_skill = self.folder / 'transcript-processing.md'
        transcript_skill.write_text('TRANSCRIPT_FIXTURE: preserve discussion logic.', encoding='utf-8')
        self.config['transcript_processing_skill'] = str(transcript_skill)

    def response(self, config, prompt, schema, work, evidence):
        if 'queries' in schema['properties']:
            return {'queries': ['BLQ']}
        segments = json.loads(prompt.split('SOURCE:\n', 1)[1].split('\nKNOWLEDGE:', 1)[0])
        self.assertIn('HUMANIZER_FIXTURE', prompt)
        self.assertIn('TRANSCRIPT_FIXTURE', prompt)
        self.assertIn('notes 模式', prompt)
        return {'markdown': '# 讨论总结\n\n{{speaker_1}} 讨论了主要事项。',
                'source_ids': [s['id'] for s in segments], 'notes': '保留疑点。'}

    def test_cleanup_preserves_originals_desk_scope_and_manual_priority(self):
        raw = (self.folder / RAW).read_bytes()
        save_details(self.folder, scene='desk')
        edit_segment(self.folder, 'seg_00002', '人工核对的同事发言')
        search = Mock(return_value=[{'warning': 'unreviewed', 'source': 'test'}])
        cleanup.clean(self.folder, self.config, call=self.response, search=search)
        search.assert_called_once_with(self.config, ['BLQ'])
        auto = read_json(self.folder / SUMMARY)['source_ids']
        self.assertNotIn('seg_00003', auto)
        self.assertIn('seg_00004', auto)
        self.assertEqual((self.folder / RAW).read_bytes(), raw)
        self.assertEqual(load_edits(self.folder, load_result(self.folder))['seg_00002'], '人工核对的同事发言')
        edit_segment(self.folder, 'seg_00001', '新的人工校正')
        self.assertEqual(set(read_json(self.folder / 'transcript.edits.json')), {'seg_00001', 'seg_00002'})
        rename_speaker(self.folder, 'speaker_1', '同事甲')
        text = (self.folder / 'exports/summary.md').read_text(encoding='utf-8')
        self.assertIn('同事甲', text)
        self.assertNotIn('00:00:', text)
        self.assertFalse((self.folder / 'transcript.agy.json').exists())
        self.assertEqual(cleanup.cleanup_status(self.folder)['state'], 'complete')

    def test_invalid_summary_rejected_without_replacing_previous_draft(self):
        cleanup.clean(self.folder, self.config, call=self.response, search=lambda *_: [])
        before = (self.folder / SUMMARY).read_bytes()
        def bad(*args):
            answer = self.response(*args)
            if 'markdown' in answer:
                answer['source_ids'] = ['invented_id']
            return answer
        with self.assertRaisesRegex(ValueError, '不存在'):
            cleanup.clean(self.folder, self.config, call=bad, search=lambda *_: [])
        self.assertEqual((self.folder / SUMMARY).read_bytes(), before)
        self.assertEqual(cleanup.cleanup_status(self.folder)['state'], 'failed')

    def test_no_text_never_calls_agy_and_duplicate_worker_is_blocked(self):
        empty = self.folder / 'empty'
        install_result(empty, {'schema_version': 1, 'segments': []})
        call = Mock()
        cleanup.clean(empty, self.config, call=call)
        call.assert_not_called()
        self.assertEqual(cleanup.cleanup_status(empty)['state'], 'skipped')
        with cleanup.session_lock(self.folder):
            cleanup.set_status(self.folder, 'running', 'busy')
            self.assertEqual(cleanup.cleanup_status(self.folder)['state'], 'running')
            with self.assertRaises(OSError):
                cleanup.clean(self.folder, self.config, call=call)
        self.assertEqual(cleanup.cleanup_status(self.folder)['state'], 'interrupted')

    def test_retrieval_keeps_scope_and_failure_is_visible(self):
        with patch('cleanup.run_json', return_value={'warnings': ['stale'], 'results': []}) as run:
            result = cleanup.retrieve({'knowledge_root': str(self.folder), 'knowledge_python': sys.executable}, ['BLQ'])
        command = run.call_args.args[0]
        for token in ('current-work', 'exact_fts', 'company_sensitive_allowed'):
            self.assertIn(token, command)
        self.assertEqual(result[0]['result']['warnings'], ['stale'])
        with self.assertRaisesRegex(RuntimeError, 'KB unavailable'):
            cleanup.clean(self.folder, self.config, call=self.response, search=Mock(side_effect=RuntimeError('KB unavailable')))
        self.assertEqual(cleanup.cleanup_status(self.folder)['state'], 'failed')
        self.assertFalse((self.folder / SUMMARY).exists())

    def test_long_meeting_merges_batches_into_one_summary(self):
        calls = []
        def call(config, prompt, schema, work, evidence):
            calls.append(evidence.name)
            if evidence.name == 'merged-summary':
                self.assertIn('HUMANIZER_FIXTURE', prompt)
                self.assertIn('TRANSCRIPT_FIXTURE', prompt)
                self.assertIn('seg_00001', prompt)
                self.assertIn('seg_00005', prompt)
                return {'markdown': '# 整场总结\n\n两个话题合并后的结论。',
                        'source_ids': ['seg_00001', 'seg_00005'], 'notes': ''}
            return self.response(config, prompt, schema, work, evidence)
        with patch('cleanup.batches', return_value=[SAMPLE['segments'][:2], SAMPLE['segments'][2:]]):
            # Each fixture batch must use an attribution present in that batch.
            def respond(*args):
                result = call(*args)
                if 'markdown' in result:
                    result['markdown'] = result['markdown'].replace('{{speaker_1}}', '现场人员')
                return result
            cleanup.clean(self.folder, self.config, call=respond, search=lambda *_: [])
        self.assertEqual(calls[-1], 'merged-summary')
        self.assertIn('两个话题合并后的结论', (self.folder / 'exports/summary.md').read_text(encoding='utf-8'))

    def test_streamed_cli_requires_success_and_uses_stdin(self):
        good = {'status': 'SUCCESS', 'structured_output': {'queries': []}}
        response = subprocess.CompletedProcess([], 0, json.dumps({'event': 'init'}) + '\n' +
                                               json.dumps({'event': 'result', 'result': good}), '')
        config = {'agy': 'agy.exe', 'model': 'test'}
        with patch('cleanup.subprocess.run', return_value=response) as run:
            answer = cleanup.ask_agy(config, '测试正文', {}, self.folder, self.folder / 'test')
        self.assertEqual(answer, {'queries': []})
        self.assertNotIn('测试正文', ' '.join(run.call_args.args[0]))
        self.assertIn('测试正文', run.call_args.kwargs['input'])
        self.assertNotIn('--dangerously-skip-permissions', run.call_args.args[0])
        response.stdout = json.dumps({'event': 'result', 'result': {'status': 'ERROR'}})
        with patch('cleanup.subprocess.run', return_value=response), self.assertRaisesRegex(RuntimeError, '未返回成功'):
            cleanup.ask_agy(config, '测试正文', {}, self.folder, self.folder / 'bad')


if __name__ == '__main__':
    unittest.main()
