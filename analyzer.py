from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs
from typing import Any

import yt_dlp

logger = logging.getLogger("yt_downloader_pro.analyzer")


class AnalysisError(Exception):
    """Base exception for URL analysis errors."""
    pass


class InvalidURLError(AnalysisError):
    """Raised when the URL is invalid or unsupported."""
    pass


class VideoUnavailableError(AnalysisError):
    """Raised when a video is private, removed, or unavailable."""
    pass


class AgeRestrictedError(AnalysisError):
    """Raised when a video has age restrictions."""
    pass


class NetworkError(AnalysisError):
    """Raised when there is a network error fetching metadata."""
    pass


@dataclass
class MediaMetadata:
    url: str
    is_playlist: bool
    title: str
    uploader: str
    thumbnail_url: str | None
    
    # Video-specific fields (None for playlists)
    duration: str | None = None
    upload_date: str | None = None
    view_count: str | None = None
    formats: list[str] = field(default_factory=list)
    
    # Playlist-specific fields (None for single videos)
    total_videos: int | None = None


def validate_and_detect_url(url: str) -> tuple[str, bool]:
    """Validates the YouTube URL.
    Returns a tuple of (normalized_url, is_playlist).
    Raises InvalidURLError if the URL is invalid."""
    if not url:
        raise InvalidURLError("URL cannot be empty.")
        
    stripped = url.strip()
    parsed = urlparse(stripped)
    netloc = parsed.netloc.lower()
    path = parsed.path
    query = parse_qs(parsed.query)
    
    # Validate domain
    is_valid_domain = any(
        domain in netloc
        for domain in ["youtube.com", "youtu.be", "youtube-nocookie.com"]
    )
    if not is_valid_domain:
        raise InvalidURLError("Not a valid YouTube domain. Please enter a youtube.com or youtu.be link.")
        
    # Playlist check
    if "list" in query:
        # If it's a playlist URL or doesn't have a watch video ID
        if "playlist" in path or "v" not in query:
            return stripped, True
            
    # Video check
    if "v" in query or "shorts" in path or "embed" in path or "v" in path.split("/") or "youtu.be" in netloc:
        return stripped, False
        
    # If list is in query and v is in query (like watch?v=...&list=...), we treat it as video by default
    if "list" in query and "v" in query:
        return stripped, False
        
    raise InvalidURLError("Invalid YouTube URL. Please enter a valid video or playlist link.")


def analyze_url(url: str) -> MediaMetadata:
    """Analyzes a YouTube URL using yt-dlp.
    Returns a MediaMetadata object.
    Raises appropriate AnalysisError subclasses on failure."""
    normalized_url, is_playlist = validate_and_detect_url(url)
    
    # Options for yt-dlp
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    
    if is_playlist:
        opts["extract_flat"] = True
    else:
        opts["extract_flat"] = False

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(normalized_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        logger.error(f"yt-dlp extract_info error: {msg}")
        if "confirm your age" in msg or "age-restricted" in msg or "Sign in to confirm your age" in msg:
            raise AgeRestrictedError("This video is age-restricted and requires signing in or cookies.") from e
        elif "private" in msg:
            raise VideoUnavailableError("This video/playlist is private and cannot be accessed.") from e
        elif "removed" in msg or "deleted" in msg or "not found" in msg or "does not exist" in msg:
            raise VideoUnavailableError("This video/playlist has been removed or does not exist.") from e
        elif "Unable to download API page" in msg or "HTTP Error" in msg or "Connection" in msg or "urlopen" in msg:
            raise NetworkError("A network error occurred while connecting to YouTube. Please check your internet connection.") from e
        else:
            raise AnalysisError(f"Failed to analyze URL: {msg}") from e
    except Exception as e:
        logger.exception("Unexpected error during yt-dlp metadata extraction")
        raise AnalysisError(f"An unexpected error occurred: {str(e)}") from e

    if not isinstance(info, dict):
        raise AnalysisError("Failed to extract valid metadata from YouTube.")

    # Check if yt-dlp extracted it as a playlist
    extracted_as_playlist = info.get("_type") == "playlist" or "entries" in info
    
    if extracted_as_playlist:
        title = info.get("title") or "Unknown Playlist"
        uploader = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Unknown Owner"
        
        # Extract total videos count
        playlist_count = info.get("playlist_count")
        entries = info.get("entries", [])
        total_videos = playlist_count if playlist_count is not None else len(entries)
        
        # Thumbnail URL
        thumbnails = info.get("thumbnails", [])
        thumbnail_url = info.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
        
        return MediaMetadata(
            url=normalized_url,
            is_playlist=True,
            title=str(title),
            uploader=str(uploader),
            thumbnail_url=thumbnail_url,
            total_videos=total_videos
        )
    else:
        title = info.get("title") or "Unknown Video"
        uploader = info.get("uploader") or info.get("channel") or "Unknown Channel"
        duration_sec = info.get("duration")
        upload_date_raw = info.get("upload_date")
        view_count_raw = info.get("view_count")
        
        # Thumbnail URL
        thumbnails = info.get("thumbnails", [])
        thumbnail_url = info.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
        
        # Format fields
        duration = _format_duration(duration_sec)
        upload_date = _format_upload_date(upload_date_raw)
        view_count = _format_view_count(view_count_raw)
        formats = _extract_formats(info)
        
        return MediaMetadata(
            url=normalized_url,
            is_playlist=False,
            title=str(title),
            uploader=str(uploader),
            thumbnail_url=thumbnail_url,
            duration=duration,
            upload_date=upload_date,
            view_count=view_count,
            formats=formats
        )


def _format_duration(duration_seconds: Any) -> str:
    if not isinstance(duration_seconds, (int, float)):
        return "N/A"
    seconds = int(duration_seconds)
    if seconds <= 0:
        return "0:00"
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _format_upload_date(raw_date: Any) -> str:
    if isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    return str(raw_date) if raw_date else "Unknown"


def _format_view_count(views: Any) -> str:
    if isinstance(views, (int, float)):
        return f"{int(views):,}"
    return str(views) if views else "0"


def _extract_formats(info: Any) -> list[str]:
    if not isinstance(info, dict):
        return ["Best available"]

    formats = info.get("formats")
    if not isinstance(formats, list):
        return ["Best available"]

    labels: list[str] = []
    for entry in formats:
        if not isinstance(entry, dict):
            continue
        resolution = entry.get("resolution") or entry.get("format_note") or ""
        ext = entry.get("ext") or ""
        if resolution:
            labels.append(f"{resolution} ({ext})")
        elif ext:
            labels.append(ext)

    unique_labels = []
    seen: set[str] = set()
    for label in labels:
        if label not in seen:
            unique_labels.append(label)
            seen.add(label)

    return unique_labels[:8] or ["Best available"]


class Analyzer:
    """Legacy wrapper for backward compatibility."""
    def analyze(self, url: str) -> MediaMetadata:
        return analyze_url(url)
