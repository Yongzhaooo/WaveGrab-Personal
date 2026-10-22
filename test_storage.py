import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from storage import ARCHIVE, tidy
from transcript_store import focused_result, install_result, load_names, load_result, rename_speaker, save_details
import voiceprints
from test_recordings import SAMPLE


def vec(*values):
    return {'seconds': 60., 'vector': list(values)}


class StorageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='wavegrab-storage-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_tidy_removes_duplicate_track_and_archives_process_files(self):
        folder = self.root / 'rec'
        (folder / 'cleanup-runs/run-1').mkdir(parents=True)
        (folder / 'cleanup-runs/run-1/prompt.txt').write_text('evidence', encoding='utf-8')
        (folder / 'exports').mkdir()
        (folder / 'mixed.flac').write_bytes(b'same')
        (folder / 'mic.flac').write_bytes(b'same')
        (folder / 'system.flac').write_bytes(b'different')
        (folder / 'cleanup.log').write_text('log', encoding='utf-8')
        (folder / 'session.json').write_text(json.dumps(
            {'status': 'complete', 'audio_files': ['mic.flac', 'mixed.flac', 'system.flac']}), encoding='utf-8')
        self.assertEqual(sorted(tidy(folder)), ['cleanup-runs', 'cleanup.log', 'mic.flac'])
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([ARCHIVE, 'exports', 'mixed.flac', 'session.json', 'system.flac']))
        with zipfile.ZipFile(folder / ARCHIVE) as zipped:
            self.assertEqual(zipped.read('cleanup-runs/run-1/prompt.txt'), b'evidence')
        self.assertEqual(json.loads((folder / 'session.json').read_text(encoding='utf-8'))['audio_files'],
                         ['mixed.flac', 'system.flac'])
        # A second run with a clashing name keeps both copies.
        (folder / 'cleanup-runs/run-1').mkdir(parents=True)
        (folder / 'cleanup-runs/run-1/prompt.txt').write_text('newer', encoding='utf-8')
        tidy(folder)
        with zipfile.ZipFile(folder / ARCHIVE) as zipped:
            self.assertEqual(len(zipped.namelist()), 3)

    def test_tidy_skips_live_recording_and_linked_directories(self):
        folder = self.root / 'rec'
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('x', encoding='utf-8')
        folder.mkdir()
        (folder / 'session.json').write_text('{"status": "recording"}', encoding='utf-8')
        (folder / 'scratch').mkdir()
        self.assertEqual(tidy(folder), [])
        (folder / 'session.json').write_text('{"status": "complete"}', encoding='utf-8')
        try:
            os.symlink(outside, folder / 'link', target_is_directory=True)
        except OSError:
            # Junctions need no privilege on Windows and are the common link type there.
            import subprocess
            if subprocess.run(['cmd', '/c', 'mklink', '/J', str(folder / 'link'), str(outside)],
                              capture_output=True).returncode:
                self.skipTest('links unavailable')
        tidy(folder)
        self.assertTrue((outside / 'keep.txt').exists())
        self.assertTrue((folder / 'link').exists())


class VoiceprintTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='wavegrab-voice-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def recording(self, name, vectors, names=None):
        folder = self.root / name
        install_result(folder, SAMPLE)
        (folder / voiceprints.EMBEDDINGS).write_text(json.dumps(vectors), encoding='utf-8')
        for speaker, person in (names or {}).items():
            rename_speaker(folder, speaker, person)
        return folder

    def test_confirmed_samples_name_new_recording_and_owner_leads_desk(self):
        for i in range(3):
            self.recording(f'old{i}', {'speaker_1': vec(1, 0, 0), 'speaker_2': vec(0, 1, 0)},
                           {'speaker_1': 'Me', 'speaker_2': ''})
        (self.root / 'voiceprints.json').write_text('{"owner": "Me"}', encoding='utf-8')
        folder = self.root / 'new'
        folder.mkdir()
        (folder / voiceprints.EMBEDDINGS).write_text(json.dumps(
            {'speaker_1': vec(0, 1, 0), 'speaker_3': vec(.99, .1, 0)}), encoding='utf-8')
        install_result(folder, SAMPLE)
        data = load_result(folder)
        self.assertEqual(load_names(folder, data), {'speaker_3': 'Me（自动识别）'})
        save_details(folder, scene='desk')
        self.assertIn('speaker_3', focused_result(folder, data)[2])
        rename_speaker(folder, 'speaker_3', 'Someone else')
        self.assertEqual(load_names(folder, data)['speaker_3'], 'Someone else')
        self.assertNotIn('（自动识别）', json.loads((folder / 'speakers.json').read_text(encoding='utf-8'))['speaker_3'])

    def test_too_few_samples_or_ambiguous_match_stays_unnamed(self):
        people = {'Me': [('a', vec(1, 0)), ('b', vec(1, 0))]}
        self.assertEqual(voiceprints.match({'speaker_1': vec(1, 0)}, people), {})
        people = {'Me': [(f'r{i}', vec(1, 0)) for i in range(3)]}
        self.assertEqual(voiceprints.match({'speaker_1': vec(1, 0), 'speaker_2': vec(.99, .05)}, people), {})
        self.assertEqual(voiceprints.match({'speaker_1': vec(1, 0), 'speaker_2': vec(0, 1)}, people), {'speaker_1': 'Me'})


if __name__ == '__main__':
    unittest.main()
