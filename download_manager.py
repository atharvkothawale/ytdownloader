from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import yt_dlp
from datetime import datetime

logger = logging.getLogger("yt_downloader_pro.download_manager")


class DownloadCancelledError(Exception):
    """Exception raised when the download is cancelled by the user."""
    pass


@dataclass
class DownloadTask:
    task_id: str
    url: str
    output_dir: str
    mode: str
    quality_label: str
    video_format_id: str | None
    audio_format_id: str | None
    status: str = "Pending"  # "Pending", "Downloading", "Completed", "Failed", "Cancelled"
    title: str = "Unknown Title"
    total_size: int | None = None
    downloaded_size: int = 0
    progress: float = 0.0  # 0.0 to 100.0
    speed: float | None = None  # bytes/s
    eta: float | None = None  # seconds
    error_msg: str | None = None
    start_time: str | None = None
    finish_time: str | None = None
    duration: float = 0.0
    avg_speed: float | None = None  # bytes/s
    conflict_option: str = "Rename"  # "Skip", "Overwrite", "Rename"


class DownloadManager:
    """Manages background download threads, yt-dlp configurations, progress hooks, and cancellation."""
    
    def __init__(
        self,
        task: DownloadTask,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        completion_callback: Callable[[dict[str, Any] | None, Exception | None], None] | None = None,
    ) -> None:
        self.task = task
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.completion_callback = completion_callback
        
        self._cancel_requested = False
        self._thread: threading.Thread | None = None
        self._start_time: float = 0.0
        self._speeds_collected: list[float] = []

    def start(self) -> None:
        """Starts the download in a background worker thread."""
        self._start_time = time.time()
        self.task.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._run()

    def cancel(self) -> None:
        """Flags the download to be cancelled."""
        self._cancel_requested = True

    def _run(self) -> None:
        error: Exception | None = None
        result: dict[str, Any] | None = None
        
        try:
            # Check if output folder is valid
            path = Path(self.task.output_dir)
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as folder_err:
                raise PermissionError(f"Cannot write to output folder: {folder_err}") from folder_err
                
            # Build initial options
            opts = self._build_options()
            
            # Pre-extract info to inspect destination filename for existing file conflicts
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.task.url, download=False)
                
            if not isinstance(info, dict):
                raise AnalysisError("Failed to extract video info for downloading.")
                
            # Predict output filename
            predicted_filename = ydl.prepare_filename(info)
            final_ext = "mp4" if self.task.mode == "Video (MP4)" else "mp3"
            dest_path = Path(predicted_filename).with_suffix(f".{final_ext}")
            
            # Evaluate file conflicts
            if dest_path.exists():
                conflict = self.task.conflict_option
                if conflict == "Skip":
                    logger.info(f"File already exists. Skipping download: {dest_path}")
                    self.task.status = "Completed"
                    self.task.progress = 100.0
                    self.task.total_size = dest_path.stat().st_size
                    self.task.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    if self.completion_callback:
                        self.completion_callback({
                            "title": info.get("title", self.task.title),
                            "mode": self.task.mode,
                            "quality": self.task.quality_label,
                            "output_dir": self.task.output_dir,
                            "duration": 0.0,
                            "total_size": self.task.total_size,
                            "avg_speed": None,
                        }, None)
                    return
                elif conflict == "Overwrite":
                    logger.info(f"File already exists. Overwriting: {dest_path}")
                    try:
                        dest_path.unlink()
                    except Exception as del_err:
                        logger.warning(f"Failed to delete existing file: {del_err}")
                elif conflict == "Rename":
                    # Rename automatically by suffixing (1), (2), etc.
                    base_stem = dest_path.stem
                    suffix = dest_path.suffix
                    counter = 1
                    new_path = dest_path
                    while new_path.exists():
                        new_path = dest_path.with_name(f"{base_stem} ({counter}){suffix}")
                        counter += 1
                    logger.info(f"File already exists. Renaming output to: {new_path}")
                    
                    # Update yt-dlp outtmpl to match the unique filename
                    opts["outtmpl"] = str(Path(self.task.output_dir) / f"{new_path.stem}.%(ext)s")

            # Run actual download
            with yt_dlp.YoutubeDL(opts) as ydl_run:
                info_run = ydl_run.extract_info(self.task.url, download=True)
                
            duration = time.time() - self._start_time
            title = info_run.get("title", self.task.title) if isinstance(info_run, dict) else self.task.title
            self.task.title = title
            self.task.duration = duration
            self.task.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.task.status = "Completed"
            
            # Calculate average speed
            if self._speeds_collected:
                self.task.avg_speed = sum(self._speeds_collected) / len(self._speeds_collected)
            elif self.task.total_size and duration > 0:
                self.task.avg_speed = self.task.total_size / duration
                
            result = {
                "title": title,
                "mode": self.task.mode,
                "quality": self.task.quality_label,
                "output_dir": self.task.output_dir,
                "duration": duration,
                "total_size": self.task.total_size,
                "avg_speed": self.task.avg_speed,
            }
            
            # Log success
            self._log_to_file("Success")
            
        except Exception as e:
            error = e
            duration = time.time() - self._start_time
            self.task.duration = duration
            self.task.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Check if it was cancelled
            if self._cancel_requested or "cancelled" in str(e).lower():
                self.task.status = "Cancelled"
                self._log_to_file("Cancelled")
            else:
                self.task.status = "Failed"
                self.task.error_msg = str(e)
                self._log_to_file("Failed", str(e))
                
        # Trigger completion callback
        if self.completion_callback:
            self.completion_callback(result, error)

    def _build_options(self) -> dict[str, Any]:
        path = Path(self.task.output_dir)
        
        # Check if URL is a playlist before setting outtmpl
        from analyzer import validate_and_detect_url
        try:
            _, is_playlist = validate_and_detect_url(self.task.url)
        except Exception:
            is_playlist = False
            
        if is_playlist:
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
            "ignoreerrors": True,
        }

        # Set formats
        if self.task.mode == "Audio (MP3)":
            if self.task.audio_format_id:
                options["format"] = f"{self.task.audio_format_id}"
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
            if self.task.video_format_id and self.task.audio_format_id:
                options["format"] = f"{self.task.video_format_id}+{self.task.audio_format_id}/best"
            elif self.task.video_format_id:
                options["format"] = f"{self.task.video_format_id}"
            else:
                options["format"] = "bestvideo+bestaudio/best"
                
            options["merge_output_format"] = "mp4"

        return options

    def _progress_hook(self, data: dict[str, Any]) -> None:
        if self._cancel_requested:
            raise DownloadCancelledError("Download cancelled by user")
            
        # Capture size and speed stats
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if total:
            self.task.total_size = int(total)
        self.task.downloaded_size = int(data.get("downloaded_bytes", 0))
        
        speed = data.get("speed")
        if speed:
            self.task.speed = float(speed)
            self._speeds_collected.append(float(speed))
            
        eta = data.get("eta")
        if eta:
            self.task.eta = float(eta)

        if self.progress_callback:
            self.progress_callback(data)

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        if self._cancel_requested:
            raise DownloadCancelledError("Download cancelled by user")
            
        status = data.get("status")
        pp_name = data.get("postprocessor")
        
        if status == "started" and self.status_callback:
            if pp_name == "FFmpegMerger":
                self.status_callback("Merging Video + Audio...")
            elif pp_name == "FFmpegExtractAudio":
                self.status_callback("Converting Audio...")
            elif pp_name == "FFmpegEmbedThumbnail":
                self.status_callback("Embedding Thumbnail...")

    def _log_to_file(self, status: str, error_msg: str | None = None) -> None:
        # Columns: Start Time, Finish Time, Average Speed, Output Path, File Size, Status, Duration, Errors
        start = self.task.start_time or "N/A"
        finish = self.task.finish_time or "N/A"
        
        avg_speed_val = self.task.avg_speed
        avg_speed_str = "N/A"
        if avg_speed_val:
            avg_speed_mb = avg_speed_val / 1024 / 1024
            avg_speed_str = f"{avg_speed_mb:.1f} MB/s"
            
        size_str = format_size(self.task.total_size)
        err_str = error_msg if error_msg else "None"
        
        log_line = (
            f"[Start: {start} | Finish: {finish}] URL: {self.task.url} | "
            f"Status: {status} | Size: {size_str} | Speed: {avg_speed_str} | "
            f"Duration: {self.task.duration:.1f}s | Path: {self.task.output_dir} | "
            f"Errors: {err_str}\n"
        )
        
        log_path = Path(__file__).resolve().parent / "downloads.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
        except Exception as e:
            logger.error(f"Failed to write to downloads.log: {e}")


class DownloadQueue:
    """Manages sequential execution of DownloadTasks on a background thread."""

    def __init__(self) -> None:
        self.tasks: list[DownloadTask] = []
        self.active_task: DownloadTask | None = None
        self._active_manager: DownloadManager | None = None
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._is_running = False
        
        # UI update callbacks
        self.on_queue_changed: Callable[[], None] | None = None
        self.on_task_progress: Callable[[DownloadTask, dict[str, Any]], None] | None = None
        self.on_queue_complete: Callable[[dict[str, Any]], None] | None = None
        
        # Statistics for finished summary
        self.completed_count = 0
        self.failed_count = 0
        self.total_bytes_transferred = 0
        self.total_elapsed_time = 0.0

    def add_task(
        self,
        url: str,
        output_dir: str,
        mode: str,
        quality_label: str,
        video_format_id: str | None = None,
        audio_format_id: str | None = None,
        conflict_option: str = "Rename",
    ) -> DownloadTask:
        """Creates and appends a task to the queue, initiating execution if idle."""
        task = DownloadTask(
            task_id=str(uuid.uuid4()),
            url=url,
            output_dir=output_dir,
            mode=mode,
            quality_label=quality_label,
            video_format_id=video_format_id,
            audio_format_id=audio_format_id,
            status="Pending",
            conflict_option=conflict_option,
        )
        
        with self._lock:
            self.tasks.append(task)
            
        self._notify_changed()
        self.start()
        return task

    def start(self) -> None:
        """Starts the queue processing thread if it's not active."""
        with self._lock:
            if not self._is_running:
                self._is_running = True
                self.queue_start_time = time.time()
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()

    def cancel_task(self, task_id: str) -> None:
        """Cancels a specific task. If active, aborts yt-dlp downloader."""
        with self._lock:
            for task in self.tasks:
                if task.task_id == task_id:
                    if task.status == "Downloading" and self._active_manager:
                        self._active_manager.cancel()
                    elif task.status == "Pending":
                        task.status = "Cancelled"
                        task.finish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    break
        self._notify_changed()

    def retry_task(self, task_id: str) -> None:
        """Sets a Failed or Cancelled task back to Pending and triggers loop execution."""
        with self._lock:
            for task in self.tasks:
                if task.task_id == task_id and task.status in ["Failed", "Cancelled"]:
                    task.status = "Pending"
                    task.progress = 0.0
                    task.downloaded_size = 0
                    task.error_msg = None
                    task.speed = None
                    task.eta = None
                    break
        self._notify_changed()
        self.start()

    def remove_task(self, task_id: str) -> None:
        """Removes a task from the list. Cancels it first if active."""
        self.cancel_task(task_id)
        with self._lock:
            self.tasks = [t for t in self.tasks if t.task_id != task_id]
        self._notify_changed()

    def clear(self) -> None:
        """Cancels active tasks and clears the queue list."""
        with self._lock:
            if self.active_task and self._active_manager:
                self._active_manager.cancel()
            self.tasks.clear()
        self._notify_changed()

    def _loop(self) -> None:
        logger.info("Sequential Queue processing thread started")
        
        while True:
            # Pick next pending task
            next_task = None
            with self._lock:
                for task in self.tasks:
                    if task.status == "Pending":
                        next_task = task
                        break
            
            if next_task is None:
                break
                
            self._run_task(next_task)
            
        with self._lock:
            self._is_running = False
            
        # Queue complete stats
        total_duration = time.time() - self.queue_start_time
        avg_speed_combined = None
        if self.total_bytes_transferred > 0 and total_duration > 0:
            avg_speed_combined = self.total_bytes_transferred / total_duration
            
        summary = {
            "completed": self.completed_count,
            "failed": self.failed_count,
            "total_size": self.total_bytes_transferred,
            "duration": total_duration,
            "avg_speed": avg_speed_combined,
        }
        
        if self.on_queue_complete:
            self.on_queue_complete(summary)

        # Reset counts for the next batch
        self.completed_count = 0
        self.failed_count = 0
        self.total_bytes_transferred = 0
        
        logger.info("Sequential Queue processing complete")

    def _run_task(self, task: DownloadTask) -> None:
        with self._lock:
            self.active_task = task
            task.status = "Downloading"
            
        self._notify_changed()
        
        # Instantiate manager
        manager = DownloadManager(
            task=task,
            progress_callback=lambda data: self._on_progress(task, data),
            status_callback=self._on_status,
            completion_callback=None,
        )
        
        with self._lock:
            self._active_manager = manager
            
        # Blocking call
        manager.start()
        
        # Task has finished running
        with self._lock:
            self._active_manager = None
            self.active_task = None
            
            if task.status == "Completed":
                self.completed_count += 1
                self.total_bytes_transferred += task.total_size or 0
            elif task.status == "Failed":
                self.failed_count += 1
                
        self._notify_changed()

    def _on_progress(self, task: DownloadTask, data: dict[str, Any]) -> None:
        # Calculate percentage
        downloaded = data.get("downloaded_bytes", 0)
        total = data.get("total_bytes") or data.get("total_bytes_estimate") or 1
        percent = min(100.0, (downloaded / total) * 100.0)
        task.progress = percent
        
        if self.on_task_progress:
            self.on_task_progress(task, data)

    def _on_status(self, status: str) -> None:
        self._notify_changed()

    def _notify_changed(self) -> None:
        if self.on_queue_changed:
            self.on_queue_changed()
