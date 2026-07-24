from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("yt_downloader_pro.settings_manager")


class SettingsManager:
    """Manages application configurations stored in config/settings.json."""

    DEFAULT_SETTINGS: dict[str, Any] = {
        "last_download_folder": "",
        "last_quality": "Best available",
        "last_output_format": "mp4",
        "last_download_type": "Video (MP4)",
        "last_window_size": "1220x860",
        "last_window_position": "+100+100",
        
        # Appearance
        "theme": "dark",  # "dark", "light", "system"
        "accent_color": "blue",  # "blue", "green", "dark-blue"
        "font_size": 11,

        # Downloads
        "auto_create_folders": True,
        "skip_existing_files": True,
        "auto_update_ytdlp": False,
        "auto_update_ffmpeg": False,
        "auto_open_folder": False,
        "delete_temp_files": True,

        # Performance
        "concurrent_downloads": 1,
        "retry_attempts": 3,
        "buffer_size": 1024,  # KB

        # Logging
        "logging_enabled": True,
        "log_location": "",
    }

    def __init__(self, config_dir: Path | None = None) -> None:
        if config_dir is None:
            self.config_dir = Path(__file__).resolve().parent / "config"
        else:
            self.config_dir = config_dir
            
        self.settings_file = self.config_dir / "settings.json"
        self.settings: dict[str, Any] = dict(self.DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        """Loads settings from config/settings.json or creates the file with default values."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            if self.settings_file.exists():
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    # Merge loaded keys to default values in case of updates
                    for k, v in loaded.items():
                        if k in self.settings:
                            self.settings[k] = v
                logger.info("Successfully loaded settings.json")
            else:
                self.save()
                logger.info("Created settings.json with default options")
        except Exception as e:
            logger.error(f"Failed to load settings.json: {e}")

    def save(self) -> None:
        """Saves current settings state back to settings.json."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            logger.info("Successfully saved settings.json")
        except Exception as e:
            logger.error(f"Failed to save settings.json: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Updates setting key value, automatically triggering file serialization."""
        self.settings[key] = value
        self.save()
