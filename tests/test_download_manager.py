import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from download_manager import DownloadManager, DownloadCancelledError


class DownloadManagerTests(unittest.TestCase):
    def test_build_options_single_video_mp4(self) -> None:
        dm = DownloadManager(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir="C:/downloads",
            mode="Video (MP4)",
            quality_label="1080p",
            video_format_id="137",
            audio_format_id="251"
        )
        opts = dm._build_options()
        self.assertEqual(opts["format"], "137+251/best")
        self.assertEqual(opts["merge_output_format"], "mp4")
        self.assertTrue(opts["outtmpl"].endswith("%(title)s.%(ext)s"))
        self.assertEqual(opts["paths"]["home"], str(Path("C:/downloads")))

    def test_build_options_playlist_video_mp4(self) -> None:
        dm = DownloadManager(
            url="https://www.youtube.com/playlist?list=PL123",
            output_dir="C:/downloads",
            mode="Video (MP4)",
            quality_label="Best Available"
        )
        opts = dm._build_options()
        self.assertEqual(opts["format"], "bestvideo+bestaudio/best")
        self.assertTrue(opts["outtmpl"].endswith("%(playlist_index)03d - %(title)s.%(ext)s"))

    def test_build_options_audio_mp3(self) -> None:
        dm = DownloadManager(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir="C:/downloads",
            mode="Audio (MP3)",
            quality_label="Best Audio",
            audio_format_id="251"
        )
        opts = dm._build_options()
        self.assertEqual(opts["format"], "251")
        self.assertTrue(opts["writethumbnail"])
        
        # Check postprocessors
        pps = opts["postprocessors"]
        self.assertEqual(pps[0]["key"], "FFmpegExtractAudio")
        self.assertEqual(pps[0]["preferredcodec"], "mp3")
        self.assertEqual(pps[1]["key"], "FFmpegEmbedThumbnail")
        self.assertEqual(pps[2]["key"], "FFmpegMetadata")

    def test_cancel_checks_raise_exception(self) -> None:
        dm = DownloadManager(
            url="url",
            output_dir="dir",
            mode="Video (MP4)",
            quality_label="Best Available"
        )
        dm.cancel()
        with self.assertRaises(DownloadCancelledError):
            dm._progress_hook({})
        with self.assertRaises(DownloadCancelledError):
            dm._postprocessor_hook({})


if __name__ == "__main__":
    unittest.main()
