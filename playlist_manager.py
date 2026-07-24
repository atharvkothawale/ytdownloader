from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("yt_downloader_pro.playlist_manager")


@dataclass
class PlaylistItem:
    index: int  # 1-based index in playlist
    video_id: str
    title: str
    url: str
    duration_sec: float | None
    duration_str: str
    uploader: str | None
    thumbnail_url: str | None
    resolution: str | None = "Best"
    upload_date: str | None = None
    is_selected: bool = True


@dataclass
class PlaylistMetadata:
    title: str
    uploader: str
    thumbnail_url: str | None
    total_videos: int
    items: list[PlaylistItem] = field(default_factory=list)


class PlaylistManager:
    """Handles playlist metadata parsing, item selection, and filtering options."""

    @staticmethod
    def parse_playlist(info_dict: dict[str, Any]) -> PlaylistMetadata:
        """Parses flat playlist info from yt-dlp into a structured PlaylistMetadata object."""
        title = info_dict.get("title") or "Unknown Playlist"
        uploader = info_dict.get("uploader") or info_dict.get("channel") or "Unknown Owner"
        
        # Thumbnail Extraction
        thumbnails = info_dict.get("thumbnails", [])
        thumbnail_url = info_dict.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
        
        entries = info_dict.get("entries", [])
        playlist_count = info_dict.get("playlist_count")
        total_videos = playlist_count if playlist_count is not None else len(entries)
        
        items: list[PlaylistItem] = []
        for i, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                continue
                
            entry_title = entry.get("title") or f"Video #{i}"
            entry_id = entry.get("id") or entry.get("url") or str(i)
            entry_url = entry.get("url") or entry.get("webpage_url") or ""
            if entry_url and not entry_url.startswith("http"):
                entry_url = f"https://www.youtube.com/watch?v={entry_id}"
                
            # Parse Duration
            dur_sec = entry.get("duration")
            dur_str = "N/A"
            if isinstance(dur_sec, (int, float)):
                dur_sec = float(dur_sec)
                hours, remainder = divmod(int(dur_sec), 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours > 0:
                    dur_str = f"{hours}:{minutes:02d}:{seconds:02d}"
                else:
                    dur_str = f"{minutes}:{seconds:02d}"
            else:
                dur_sec = None
                
            # Parse Thumbnail
            entry_thumbnails = entry.get("thumbnails", [])
            entry_thumb = entry.get("thumbnail") or (entry_thumbnails[-1].get("url") if entry_thumbnails else None)
            
            items.append(
                PlaylistItem(
                    index=i,
                    video_id=entry_id,
                    title=entry_title,
                    url=entry_url,
                    duration_sec=dur_sec,
                    duration_str=dur_str,
                    uploader=entry.get("uploader") or entry.get("channel"),
                    thumbnail_url=entry_thumb,
                    upload_date=entry.get("upload_date"),
                )
            )
            
        return PlaylistMetadata(
            title=title,
            uploader=uploader,
            thumbnail_url=thumbnail_url,
            total_videos=total_videos,
            items=items,
        )

    @staticmethod
    def get_filtered_items(
        items: list[PlaylistItem],
        title_contains: str | None = None,
        min_duration: float | None = None,
        max_duration: float | None = None,
        upload_date_after: str | None = None,
        upload_date_before: str | None = None,
        index_start: int | None = None,
        index_end: int | None = None,
    ) -> list[PlaylistItem]:
        """Filters a list of PlaylistItem entries based on title, duration, dates, and indices."""
        filtered = []
        for item in items:
            # Title filter
            if title_contains and title_contains.lower() not in item.title.lower():
                continue
                
            # Duration filter
            if item.duration_sec is not None:
                if min_duration is not None and item.duration_sec < min_duration:
                    continue
                if max_duration is not None and item.duration_sec > max_duration:
                    continue
                    
            # Index filter (1-based index)
            if index_start is not None and item.index < index_start:
                continue
            if index_end is not None and item.index > index_end:
                continue
                
            # Upload date filter (expected format YYYYMMDD)
            if item.upload_date:
                date_str = item.upload_date.replace("-", "")
                if upload_date_after:
                    after_str = upload_date_after.replace("-", "").replace("/", "")
                    if date_str < after_str:
                        continue
                if upload_date_before:
                    before_str = upload_date_before.replace("-", "").replace("/", "")
                    if date_str > before_str:
                        continue
                        
            filtered.append(item)
        return filtered

    @staticmethod
    def select_all(items: list[PlaylistItem]) -> None:
        for item in items:
            item.is_selected = True

    @staticmethod
    def deselect_all(items: list[PlaylistItem]) -> None:
        for item in items:
            item.is_selected = False

    @staticmethod
    def invert_selection(items: list[PlaylistItem]) -> None:
        for item in items:
            item.is_selected = not item.is_selected
