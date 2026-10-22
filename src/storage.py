"""After processing, keep one audio copy and one process archive per recording."""
from datetime import datetime
import filecmp
from pathlib import Path
import shutil
import zipfile

from transcript_store import atomic_text, json_text, read_json

ARCHIVE = 'process-archive.zip'
KEEP_DIRS = {'exports', 'screenshots'}
LOGS = ('cleanup.log', 'transcription.log')


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def tidy(folder):
    """Caller holds the session lock. Returns the names removed from the recording top level."""
    folder = Path(folder)
    session = read_json(folder / 'session.json', {})
    if session.get('status') == 'recording':
        return []
    removed = []
    mixed = folder / 'mixed.flac'
    for name in ('mic.flac', 'system.flac'):
        track = folder / name
        if mixed.is_file() and track.is_file() and filecmp.cmp(mixed, track, shallow=False):
            track.unlink()
            removed.append(name)
    if removed and isinstance(session.get('audio_files'), list):
        session['audio_files'] = [f for f in session['audio_files'] if f not in removed]
        atomic_text(folder / 'session.json', json_text(session))
    # Links may point outside the recording; never archive or delete through them.
    items = [p for p in folder.iterdir() if not _linked(p) and (
        (p.is_dir() and p.name not in KEEP_DIRS) or (p.is_file() and p.name in LOGS))]
    files = [(f, f.relative_to(folder).as_posix()) for item in items
             for f in ([item] if item.is_file() else sorted(item.rglob('*'))) if f.is_file() and not _linked(f)]
    if files:
        archive = folder / ARCHIVE
        with zipfile.ZipFile(archive, 'a', zipfile.ZIP_DEFLATED) as zipped:
            prefix = datetime.now().strftime('%Y%m%d-%H%M%S/') if {a for _, a in files} & set(zipped.namelist()) else ''
            for path, name in files:
                zipped.write(path, prefix + name)
        with zipfile.ZipFile(archive) as zipped:
            sizes = {info.filename: info.file_size for info in zipped.infolist()}
            # Delete originals only after the archive reads back intact and complete.
            if zipped.testzip() is not None or any(sizes.get(prefix + a) != p.stat().st_size for p, a in files):
                raise OSError('过程归档校验失败，原文件保留')
    for item in items:
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink(missing_ok=True)
        removed.append(item.name)
    return removed
