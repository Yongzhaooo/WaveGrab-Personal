"""Audio conversion from WAV to MP3 using pydub and ffmpeg."""

import shutil
from pathlib import Path

from pydub import AudioSegment

from paths import get_base_path


def get_ffmpeg_path() -> Path | None:
    """Return bundled ffmpeg path if it exists."""
    ffmpeg_path = get_base_path() / "bin" / "ffmpeg.exe"
    if ffmpeg_path.exists():
        return ffmpeg_path
    return None


def setup_ffmpeg() -> None:
    """Configure pydub to use bundled ffmpeg."""
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        AudioSegment.converter = str(ffmpeg_path)
        AudioSegment.ffmpeg = str(ffmpeg_path)
        AudioSegment.ffprobe = str(ffmpeg_path.parent / "ffprobe.exe")


def convert_wav_to_mp3(
    wav_path: Path | str,
    mp3_path: Path | str | None = None,
    bitrate: str = "192k",
    delete_wav: bool = True
) -> Path:
    """Convert WAV file to MP3.

    Args:
        wav_path: Source WAV file path
        mp3_path: Destination MP3 file path (optional, derived from wav_path)
        bitrate: MP3 bitrate (default: 192k)
        delete_wav: If True, delete WAV file after conversion

    Returns:
        Path to created MP3 file
    """
    setup_ffmpeg()

    wav_path = Path(wav_path)
    if mp3_path is None:
        mp3_path = wav_path.with_suffix(".mp3")
    else:
        mp3_path = Path(mp3_path)

    # Load and convert
    audio = AudioSegment.from_wav(str(wav_path))
    audio.export(str(mp3_path), format="mp3", bitrate=bitrate)

    # Delete WAV if requested
    if delete_wav and wav_path.exists():
        wav_path.unlink()

    return mp3_path


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available (bundled or in PATH)."""
    setup_ffmpeg()

    # Check if bundled ffmpeg exists
    if get_ffmpeg_path():
        return True

    # Otherwise check if ffmpeg is in PATH
    return shutil.which("ffmpeg") is not None
