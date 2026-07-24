import unittest
from format_manager import FormatManager, VideoFormat, AudioFormat, DownloadOption, format_size


class FormatManagerTests(unittest.TestCase):
    def test_format_size(self) -> None:
        self.assertEqual(format_size(None), "Unknown size")
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1024 * 1024 * 5.5), "5.5 MB")
        self.assertEqual(format_size(1024 * 1024 * 1024 * 1.25), "1.2 GB")

    def test_parse_formats_and_pairing(self) -> None:
        # Mock info_dict from yt-dlp
        info = {
            "formats": [
                # Storyboard format (should be ignored)
                {
                    "format_id": "sb0",
                    "vcodec": "none",
                    "acodec": "none",
                    "height": 90
                },
                # Video-only 1080p stream
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "vcodec": "avc1.64002a",
                    "acodec": "none",
                    "height": 1080,
                    "fps": 30,
                    "filesize": 1000000,
                },
                # Video-only 720p stream
                {
                    "format_id": "136",
                    "ext": "mp4",
                    "vcodec": "avc1.4d401f",
                    "acodec": "none",
                    "height": 720,
                    "fps": 30,
                    "filesize": 500000,
                },
                # Audio-only medium quality
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                    "abr": 128,
                    "filesize": 100000,
                },
                # Audio-only high quality ( Opus )
                {
                    "format_id": "251",
                    "ext": "webm",
                    "vcodec": "none",
                    "acodec": "opus",
                    "abr": 160,
                    "filesize": 120000,
                }
            ]
        }

        manager = FormatManager(info)

        # Check video options count (Best Available, 1080p, 720p)
        self.assertEqual(len(manager.video_options), 3)

        # Option 0 should be "Best Available" pointing to 1080p paired with best audio (251)
        opt_best = manager.video_options[0]
        self.assertEqual(opt_best.quality_label, "Best Available")
        self.assertEqual(opt_best.video_format.format_id, "137")
        self.assertEqual(opt_best.audio_format.format_id, "251")
        self.assertEqual(opt_best.estimated_filesize, 1000000 + 120000)

        # Option 1 should be "1080p"
        opt_1080 = manager.video_options[1]
        self.assertEqual(opt_1080.quality_label, "1080p")
        self.assertEqual(opt_1080.video_format.format_id, "137")
        self.assertEqual(opt_1080.audio_format.format_id, "251")

        # Option 2 should be "720p"
        opt_720 = manager.video_options[2]
        self.assertEqual(opt_720.quality_label, "720p")
        self.assertEqual(opt_720.video_format.format_id, "136")
        self.assertEqual(opt_720.audio_format.format_id, "251")
        self.assertEqual(opt_720.estimated_filesize, 500000 + 120000)

        # Check Best Audio option
        self.assertIsNotNone(manager.audio_option)
        self.assertEqual(manager.audio_option.quality_label, "Best Audio")
        self.assertEqual(manager.audio_option.audio_format.format_id, "251")
        self.assertEqual(manager.audio_option.estimated_filesize, 120000)
        self.assertEqual(manager.audio_option.container, "mp3")

    def test_combined_video_audio_stream_no_merge(self) -> None:
        info = {
            "formats": [
                # Legacy combined 360p stream (both audio and video codecs set)
                {
                    "format_id": "18",
                    "ext": "mp4",
                    "vcodec": "h264",
                    "acodec": "aac",
                    "height": 360,
                    "fps": 30,
                    "filesize": 300000,
                }
            ]
        }

        manager = FormatManager(info)

        # 360p combined stream doesn't need pairing with best audio
        self.assertEqual(len(manager.video_options), 2)  # Best Available and 360p
        opt_360 = manager.video_options[1]
        self.assertEqual(opt_360.quality_label, "360p")
        self.assertEqual(opt_360.video_format.format_id, "18")
        self.assertIsNone(opt_360.audio_format)
        self.assertEqual(opt_360.estimated_filesize, 300000)
        self.assertEqual(opt_360.video_codec, "h264")
        self.assertEqual(opt_360.audio_codec, "aac")


if __name__ == "__main__":
    unittest.main()
