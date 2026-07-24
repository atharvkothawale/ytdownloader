import unittest

from downloader import Downloader


class DownloaderTests(unittest.TestCase):
    def test_build_options_for_mp4_uses_video_format(self) -> None:
        downloader = Downloader()
        options = downloader.build_options("C:/tmp", mode="Video (MP4)", quality="Best available")
        self.assertIn("format", options)
        self.assertIn("outtmpl", options)
        self.assertNotIn("postprocessors", options)

    def test_build_options_for_mp3_uses_audio_postprocessor(self) -> None:
        downloader = Downloader()
        options = downloader.build_options("C:/tmp", mode="Audio (MP3)", quality="Best available")
        self.assertEqual(options["format"], "bestaudio/best")
        self.assertTrue(options["postprocessors"])


if __name__ == "__main__":
    unittest.main()
