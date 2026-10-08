"""Small offline check: real mixer, independent tracks, UTF-8 handoff export."""
import sys
import tempfile
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent / 'src'))
import numpy as np
import soundfile as sf
from recorder import Recorder, StreamConfig
from writer import AudioWriter
from handoff import write_handoff, session_name, clipboard_prompt


def main():
    with tempfile.TemporaryDirectory(prefix='wavegrab-') as tmp:
        folder = Path(tmp) / session_name('中文会议')
        folder.mkdir()
        recorder = Recorder(StreamConfig(0, 2, 48000), StreamConfig(1, 1, 44100),
                            track_directory=folder)

        class Capture:
            error = ''
            def __init__(self, samples, last=False):
                self.samples, self.last = samples, last
            def get_chunk_blocking(self, timeout):
                if self.last:
                    recorder._running = False
                return self.samples

        recorder._loopback = Capture(np.full(1920 * 2, 1000, dtype=np.float32))
        recorder._mic = Capture(np.full(1764, 3000, dtype=np.float32), last=True)
        for name, rate, channels in [('system', 48000, 2), ('mic', 44100, 1)]:
            writer = AudioWriter(folder, rate, channels, format='FLAC')
            writer.start(name + '.flac')
            recorder._track_writers[name] = writer
        recorder._running = True
        recorder._mix_loop()
        mixed = recorder.get_mixed_chunk()
        assert mixed.size == 3840 and np.all(mixed == 2000)
        writer = AudioWriter(folder, 48000, 2, format='FLAC')
        writer.start('mixed.flac')
        writer.write(mixed)
        writer.stop()
        for track in recorder._track_writers.values():
            track.stop()
        write_handoff(folder, '中文会议', {}, .04)
        data = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        assert set(data['audio_files']) == {'mixed.flac', 'system.flac', 'mic.flac'}
        assert sf.info(folder / 'mic.flac').frames == 1764
        assert 'transcript.clean.md' in (folder / 'HANDOFF.md').read_text(encoding='utf-8')
        assert str(folder) in clipboard_prompt(folder)
        assert session_name('会议') != session_name('会议')
    print('OK: mixed audio, source tracks, UTF-8 handoff, unique session folders')


if __name__ == '__main__':
    main()
