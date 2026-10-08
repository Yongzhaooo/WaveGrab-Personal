"""Persistent configuration management."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from paths import get_exe_dir


def _get_config_path() -> Path:
    """Return config file path (supports PyInstaller)."""
    return get_exe_dir() / "config.json"


CONFIG_FILE = _get_config_path()


@dataclass
class AppConfig:
    """Application configuration."""
    # Selected devices (by name)
    loopback_device: str = ""
    loopback_sample_rate: int = 0
    mic_device: str = ""
    mic_sample_rate: int = 0

    # Volumes (0.0-1.0)
    loopback_volume: float = 1.0
    mic_volume: float = 1.0

    # Output
    output_folder: str = ""
    last_filename: str = ""
    last_session: str = ""

    # Window
    window_geometry: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Create configuration from dictionary."""
        # Filter only valid fields
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def load_config() -> AppConfig:
    """Load configuration from JSON file."""
    config_file = _get_config_path()
    if not config_file.exists():
        return AppConfig()

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return AppConfig.from_dict(data)
    except (json.JSONDecodeError, IOError):
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Save configuration to JSON file."""
    config_file = _get_config_path()
    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
    except IOError:
        pass  # Ignore write errors
