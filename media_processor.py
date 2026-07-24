from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("yt_downloader_pro.media_processor")


class MediaProcessor:
    """Handles post-download operations like chapters processing."""

    @staticmethod
    def export_chapters_to_file(info_dict: dict[str, Any], output_path: Path) -> None:
        """Parses chapters from info_dict and saves them to a text file next to the video."""
        chapters = info_dict.get("chapters", [])
        if not chapters:
            logger.info("No chapters found in metadata to export.")
            return

        chapters_file = output_path.with_suffix(".chapters.txt")
        try:
            with open(chapters_file, "w", encoding="utf-8") as f:
                f.write(f"Chapters for: {info_dict.get('title')}\n")
                f.write("-" * 40 + "\n")
                for ch in chapters:
                    start = ch.get("start_time", 0.0)
                    end = ch.get("end_time", 0.0)
                    title = ch.get("title", "Chapter")
                    f.write(f"{MediaProcessor._format_seconds(start)} - {MediaProcessor._format_seconds(end)} : {title}\n")
            logger.info(f"Successfully exported chapters to: {chapters_file}")
        except Exception as e:
            logger.error(f"Failed to export chapters to file: {e}")

    @staticmethod
    def _format_seconds(sec: float) -> str:
        h, r = divmod(int(sec), 3600)
        m, s = divmod(r, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
