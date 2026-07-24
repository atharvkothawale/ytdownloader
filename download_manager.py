import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable
import yt_dlp
from datetime import datetime

logger = logging.getLogger("yt_downloader_pro.download_manager")


class DownloadCancelledError(Exception):
    """Exception raised when the download is cancelled by the user."""
    pass


class DownloadManager:
    """Manages background download threads, yt-dlp configurations, progress hooks, and cancellation."""
    
    def __init__(
        self,
        url: str,
        output_dir: str,
        mode: str,
        quality_label: str,
        video_format_id: str | None = None,
        audio_format_id: str | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        completion_callback: Callable[[dict[str, Any] | None, Exception | None], None] | None = None,
    ) -> None:
        self.url = url
        self.output_dir = output_dir
        self.mode = mode
        self.quality_label = quality_label
        self.video_format_id = video_format_id
        self.audio_format_id = audio_format_id
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.completion_callback = completion_callback
        
        self._cancel_requested = False
        self._thread: threading.Thread | None = None
        self._start_time: float = 0.0

    def start(self) -> None:
        """Starts the download in a background worker thread."""
        self._start_time = time.time()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        """Flags the download to be cancelled."""
        self._cancel_requested = True

    def _run(self) -> None:
        error: Exception | None = None
        result: dict[str, Any] | None = None
        
        try:
            # Check if output folder is valid
            path = Path(self.output_dir)
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as folder_err:
                raise PermissionError(f"Cannot write to output folder: {folder_err}") from folder_err
                
            # Build options
            opts = self._build_options()
            
            # Run download
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                
            duration = time.time() - self._start_time
            title = info.get("title", self.url) if isinstance(info, dict) else self.url
            result = {
                "title": title,
                "mode": self.mode,
                "quality": self.quality_label,
                "output_dir": self.output_dir,
                "duration": duration,
            }
            
            # Log success
            self._log_to_file(self.url, "Success", duration)
            
        except Exception as e:
            error = e
            duration = time.time() - self._start_time
            
            # Check if it was cancelled
            if self._cancel_requested or "cancelled by user" in str(e).lower():
                self._log_to_file(self.url, "Cancelled", duration)
            else:
                self._log_to_file(self.url, "Failed", duration, str(e))
                
        # Trigger completion callback
        if self.completion_callback:
            self.completion_callback(result, error)

    def _build_options(self) -> dict[str, Any]:
        path = Path(self.output_dir)
        
        # Check if URL is a playlist before setting outtmpl
        from analyzer import validate_and_detect_url
        try:
            _, is_playlist = validate_and_detect_url(self.url)
        except Exception:
            is_playlist = False
            
        if is_playlist:
            # Automatically number files and preserve playlist order
            outtmpl = str(path / "%(playlist_index)03d - %(title)s.%(ext)s")
        else:
            outtmpl = str(path / "%(title)s.%(ext)s")

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": outtmpl,
            "paths": {"home": str(path)},
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
        }

        # Set formats
        if self.mode == "Audio (MP3)":
            if self.audio_format_id:
                options["format"] = f"{self.audio_format_id}"
            else:
                options["format"] = "bestaudio/best"
                
            # Postprocessors to convert to mp3, embed thumbnail, and write metadata
            options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "0",  # VBR best quality
                },
                {
                    "key": "FFmpegEmbedThumbnail",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }
            ]
            options["writethumbnail"] = True  # Required for FFmpegEmbedThumbnail
        else:
            # Video Mode
            # If we have specific format IDs, use them
            if self.video_format_id and self.audio_format_id:
                options["format"] = f"{self.video_format_id}+{self.audio_format_id}/best"
            elif self.video_format_id:
                options["format"] = f"{self.video_format_id}"
            else:
                options["format"] = "bestvideo+bestaudio/best"
                
            # Output format MP4: ffmpeg will merge into mp4 container automatically
            options["merge_output_format"] = "mp4"

        return options

    def _progress_hook(self, data: dict[str, Any]) -> None:
        if self._cancel_requested:
            raise DownloadCancelledError("Download cancelled by user")
            
        if self.progress_callback:
            self.progress_callback(data)

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        if self._cancel_requested:
            raise DownloadCancelledError("Download cancelled by user")
            
        status = data.get("status")
        pp_name = data.get("postprocessor")
        
        if status == "started" and self.status_callback:
            if pp_name == "FFmpegMerger":
                self.status_callback("Merging...")
            elif pp_name == "FFmpegExtractAudio":
                self.status_callback("Converting...")

    def _log_to_file(self, url: str, status: str, duration: float, error_msg: str | None = None) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        err_str = f" | Error: {error_msg}" if error_msg else ""
        log_line = f"[{timestamp}] URL: {url} | Status: {status} | Duration: {duration:.2f}s{err_str}\n"
        
        log_path = Path(__file__).resolve().parent / "downloads.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to write to downloads.log: {e}")
