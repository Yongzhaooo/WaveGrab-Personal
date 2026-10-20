"""Run with dist/.runtime/Scripts/python.exe; no microphone or model download."""
from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from speaker_diarization import cluster_embeddings, assign_embeddings, frame_turns


class DiarizationTests(unittest.TestCase):
    def test_recurring_voices_cluster_globally_without_forcing_a_count(self):
        rng = np.random.default_rng(23)
        voices = np.eye(3)
        expected = np.tile(np.arange(3), 25)
        vectors = voices[expected] + rng.normal(0, .025, (75, 3))
        labels = cluster_embeddings(vectors)
        self.assertEqual(len(set(labels)), 3)
        for person in range(3):
            self.assertEqual(len(set(labels[expected == person])), 1)
        np.testing.assert_array_equal(labels, cluster_embeddings(vectors))
        self.assertEqual(len(set(cluster_embeddings(vectors, 2))), 2)

    def test_insufficient_or_invalid_features(self):
        np.testing.assert_array_equal(cluster_embeddings([[1., 0.]]), [0])
        for vectors in ([], [[0., 0.]], [[float('nan'), 1.]]):
            with self.assertRaises(ValueError):
                cluster_embeddings(vectors)
        with self.assertRaises(ValueError):
            cluster_embeddings([[1., 0.]], 2)

    def test_ambiguous_or_unrelated_voice_stays_unknown(self):
        centers = [[1., 0., 0.], [0., 1., 0.]]
        labels = assign_embeddings([[1., .05, 0.], [.05, 1., 0.], [1., 1., 0.],
                                    [0., 0., 1.], [0., 0., 0.]], centers)
        np.testing.assert_array_equal(labels, [0, 1, -1, -1, -1])

    def test_turns_preserve_silence_overlap_and_unknown(self):
        frames = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0],
                           [0, 0, 0], [0, 0, 1], [0, 0, 1]], dtype=bool)
        turns = frame_turns(frames, .5, .03, 2.8)
        self.assertEqual([t['speaker'] for t in turns], [0, 1, 'unknown'])
        self.assertEqual(turns[0]['end'], 1.03)
        self.assertEqual(turns[1]['start'], .53)
        self.assertEqual(turns[-1]['end'], 2.8)
        self.assertTrue(all(not (t['start'] < 2 and t['end'] > 1.53) for t in turns))


if __name__ == '__main__':
    unittest.main()
