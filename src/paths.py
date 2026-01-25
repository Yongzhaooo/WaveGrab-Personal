"""Path utilities with PyInstaller support."""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True if running as PyInstaller bundle."""
    return getattr(sys, 'frozen', False)


def get_base_path() -> Path:
    """Return base path (supports PyInstaller)."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent


def get_src_path() -> Path:
    """Return src folder path."""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_exe_dir() -> Path:
    """Return directory containing the executable (for writable files)."""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).parent.parent
