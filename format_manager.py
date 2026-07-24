from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("yt_downloader_pro.format_manager")


@dataclass
class VideoFormat:
    format_id: str
    resolution: str
    height: int
    fps: int | None
    vcodec: str
    acodec: str
    ext: str
    container: str
    hdr_available: bool
    estimated_filesize: int | None  # in bytes
    requires_merge: bool


@dataclass
class AudioFormat:
    format_id: str
    codec: str
    bitrate: float | None  # abr or tbr in kbps
    ext: str
    container: str
    estimated_filesize: int | None  # in bytes


@dataclass
class DownloadOption:
    quality_label: str  # e.g., "Best Available", "1080p", "Best Audio"
    video_format: VideoFormat | None
    audio_format: AudioFormat | None
    is_audio_only: bool
    container: str
    estimated_filesize: int | None  # in bytes
    video_codec: str
    audio_codec: str


def format_size(size_bytes: int | None) -> str:
    """Converts a size in bytes to a human-readable string."""
    if size_bytes is None:
        return "Unknown size"
    if size_bytes <= 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


class FormatManager:
    """Extracts and configures download formats from yt-dlp metadata."""

    def __init__(self, info_dict: dict[str, Any]) -> None:
        self.info_dict = info_dict
        self.video_formats: list[VideoFormat] = []
        self.audio_formats: list[AudioFormat] = []
        self.best_audio: AudioFormat | None = None
        self.video_options: list[DownloadOption] = []
        self.audio_option: DownloadOption | None = None
        
        self._parse()

    def _parse(self) -> None:
        raw_formats = self.info_dict.get("formats", [])
        if not isinstance(raw_formats, list):
            logger.warning("No formats list found in metadata dictionary")
            return

        # 1. Parse raw formats into VideoFormat and AudioFormat lists
        for raw_fmt in raw_formats:
            if not isinstance(raw_fmt, dict):
                continue

            vcodec = raw_fmt.get("vcodec")
            acodec = raw_fmt.get("acodec")
            
            # Skip storyboards and non-media formats
            if (vcodec == "none" or vcodec is None) and (acodec == "none" or acodec is None):
                continue

            # Determine filesizes
            filesize = raw_fmt.get("filesize") or raw_fmt.get("filesize_approx")
            if filesize is not None:
                filesize = int(filesize)

            # Check if it is a video stream (with or without audio)
            if vcodec != "none" and vcodec is not None:
                height = raw_fmt.get("height")
                if height is None:
                    continue
                height = int(height)
                
                # Determine resolution labels
                res_label = self._map_resolution_label(height)
                
                # Check for HDR availability
                dynamic_range = raw_fmt.get("dynamic_range")
                hdr_available = dynamic_range is not None and "HDR" in str(dynamic_range)

                # Determine if format is video-only and needs merging
                requires_merge = acodec == "none" or acodec is None

                self.video_formats.append(
                    VideoFormat(
                        format_id=str(raw_fmt.get("format_id", "")),
                        resolution=res_label,
                        height=height,
                        fps=raw_fmt.get("fps"),
                        vcodec=str(vcodec),
                        acodec=str(acodec) if acodec else "none",
                        ext=str(raw_fmt.get("ext", "mp4")),
                        container=str(raw_fmt.get("container") or raw_fmt.get("ext") or "mp4"),
                        hdr_available=hdr_available,
                        estimated_filesize=filesize,
                        requires_merge=requires_merge,
                    )
                )

            # Check if it is an audio-only stream
            elif acodec != "none" and acodec is not None:
                bitrate = raw_fmt.get("abr") or raw_fmt.get("tbr")
                if bitrate is not None:
                    bitrate = float(bitrate)

                self.audio_formats.append(
                    AudioFormat(
                        format_id=str(raw_fmt.get("format_id", "")),
                        codec=str(acodec),
                        bitrate=bitrate,
                        ext=str(raw_fmt.get("ext", "m4a")),
                        container=str(raw_fmt.get("container") or raw_fmt.get("ext") or "m4a"),
                        estimated_filesize=filesize,
                    )
                )

        # 2. Select best audio-only stream (highest bitrate)
        if self.audio_formats:
            # Sort descending: prioritize higher bitrate, then larger size
            self.audio_formats.sort(
                key=lambda x: (x.bitrate or 0.0, x.estimated_filesize or 0),
                reverse=True,
            )
            self.best_audio = self.audio_formats[0]

        # 3. Process video resolutions
        # Group by resolution, picking the best format for each resolution
        res_groups: dict[str, list[VideoFormat]] = {}
        for vf in self.video_formats:
            res_groups.setdefault(vf.resolution, []).append(vf)

        sorted_res_options: list[DownloadOption] = []
        for res, formats_in_res in res_groups.items():
            # Sort formats within the same resolution to pick the best video quality
            # Prioritize fps, then estimated filesize
            formats_in_res.sort(
                key=lambda x: (x.height, x.fps or 0, x.estimated_filesize or 0),
                reverse=True,
            )
            best_vf = formats_in_res[0]

            # Pair with best audio if it's video-only
            if best_vf.requires_merge:
                if self.best_audio:
                    combined_size = None
                    if best_vf.estimated_filesize is not None and self.best_audio.estimated_filesize is not None:
                        combined_size = best_vf.estimated_filesize + self.best_audio.estimated_filesize
                    
                    sorted_res_options.append(
                        DownloadOption(
                            quality_label=res,
                            video_format=best_vf,
                            audio_format=self.best_audio,
                            is_audio_only=False,
                            container="mp4" if best_vf.ext == "mp4" else best_vf.container,
                            estimated_filesize=combined_size,
                            video_codec=best_vf.vcodec,
                            audio_codec=self.best_audio.codec,
                        )
                    )
                else:
                    # Fallback if no audio format is found
                    sorted_res_options.append(
                        DownloadOption(
                            quality_label=res,
                            video_format=best_vf,
                            audio_format=None,
                            is_audio_only=False,
                            container=best_vf.container,
                            estimated_filesize=best_vf.estimated_filesize,
                            video_codec=best_vf.vcodec,
                            audio_codec="none",
                        )
                    )
            else:
                # Combined video + audio stream (requires no merge)
                sorted_res_options.append(
                    DownloadOption(
                        quality_label=res,
                        video_format=best_vf,
                        audio_format=None,
                        is_audio_only=False,
                        container=best_vf.container,
                        estimated_filesize=best_vf.estimated_filesize,
                        video_codec=best_vf.vcodec,
                        audio_codec=best_vf.acodec,
                    )
                )

        # Sort the resulting resolutions from highest to lowest height
        sorted_res_options.sort(
            key=lambda x: x.video_format.height if x.video_format else 0,
            reverse=True,
        )
        self.video_options = sorted_res_options

        # Create "Best Available" video option
        if self.video_options:
            best_opt = self.video_options[0]
            best_available_option = DownloadOption(
                quality_label="Best Available",
                video_format=best_opt.video_format,
                audio_format=best_opt.audio_format,
                is_audio_only=False,
                container=best_opt.container,
                estimated_filesize=best_opt.estimated_filesize,
                video_codec=best_opt.video_codec,
                audio_codec=best_opt.audio_codec,
            )
            # Add at the very beginning of video options list
            self.video_options.insert(0, best_available_option)

        # Create "Best Audio" option
        if self.best_audio:
            self.audio_option = DownloadOption(
                quality_label="Best Audio",
                video_format=None,
                audio_format=self.best_audio,
                is_audio_only=True,
                container="mp3",  # transcode output container
                estimated_filesize=self.best_audio.estimated_filesize,
                video_codec="none",
                audio_codec=self.best_audio.codec,
            )

    @staticmethod
    def _map_resolution_label(height: int) -> str:
        """Maps height to standard YouTube quality labels."""
        if height >= 4320:
            return "4320p (8K)"
        elif height >= 2160:
            return "2160p (4K)"
        elif height >= 1440:
            return "1440p"
        elif height >= 1080:
            return "1080p"
        elif height >= 720:
            return "720p"
        elif height >= 480:
            return "480p"
        elif height >= 360:
            return "360p"
        elif height >= 240:
            return "240p"
        elif height >= 144:
            return "144p"
        else:
            return f"{height}p"
