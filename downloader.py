from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yt_dlp


class Downloader:
    """Encapsulates yt-dlp download behavior for the app."""

    def build_options(self, output_dir: str, mode: str, quality: str) -> dict[str, Any]:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(path / "%(title)s.%(ext)s"),
            "noplaylist": True,
            "paths": {"home": str(path)},
        }

        if mode == "Audio (MP3)":
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}]
        else:
            options["format"] = "bestvideo+bestaudio/best"

        return options

    def download(
        self,
        url: str,
        output_dir: str,
        mode: str,
        quality: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        options = self.build_options(output_dir, mode, quality)
        options["progress_hooks"] = [self._make_progress_hook(progress_callback)]

        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        return {
            "title": info.get("title") if isinstance(info, dict) else url,
            "mode": mode,
            "quality": quality,
            "output_dir": output_dir,
        }

    def _make_progress_hook(self, progress_callback: Callable[[dict[str, Any]], None] | None) -> Callable[[dict[str, Any]], None]:
        def hook(data: dict[str, Any]) -> None:
            if progress_callback is None:
                return
            progress_callback(data)

        return hook
