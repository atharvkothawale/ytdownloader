import unittest
from unittest.mock import MagicMock, patch
import yt_dlp

from analyzer import (
    analyze_url,
    validate_and_detect_url,
    _format_duration,
    _format_upload_date,
    _format_view_count,
    InvalidURLError,
    VideoUnavailableError,
    AgeRestrictedError,
    NetworkError,
    AnalysisError
)


class AnalyzerTests(unittest.TestCase):
    def test_validate_and_detect_video_url(self) -> None:
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        norm, is_playlist = validate_and_detect_url(url)
        self.assertEqual(norm, url)
        self.assertFalse(is_playlist)

    def test_validate_and_detect_short_url(self) -> None:
        url = "https://youtu.be/dQw4w9WgXcQ"
        norm, is_playlist = validate_and_detect_url(url)
        self.assertEqual(norm, url)
        self.assertFalse(is_playlist)

    def test_validate_and_detect_playlist_url(self) -> None:
        url = "https://www.youtube.com/playlist?list=PL6NdkXsPL07KN01gH2vucrHCEyyNmVEx4"
        norm, is_playlist = validate_and_detect_url(url)
        self.assertEqual(norm, url)
        self.assertTrue(is_playlist)

    def test_validate_and_detect_invalid_url(self) -> None:
        with self.assertRaises(InvalidURLError):
            validate_and_detect_url("https://google.com")

        with self.assertRaises(InvalidURLError):
            validate_and_detect_url("")

    def test_format_duration(self) -> None:
        self.assertEqual(_format_duration(0), "0:00")
        self.assertEqual(_format_duration(65), "1:05")
        self.assertEqual(_format_duration(3665), "1:01:05")
        self.assertEqual(_format_duration("invalid"), "N/A")

    def test_format_upload_date(self) -> None:
        self.assertEqual(_format_upload_date("20091025"), "2009-10-25")
        self.assertEqual(_format_upload_date("invalid"), "invalid")
        self.assertEqual(_format_upload_date(None), "Unknown")

    def test_format_view_count(self) -> None:
        self.assertEqual(_format_view_count(1234567), "1,234,567")
        self.assertEqual(_format_view_count("123"), "123")
        self.assertEqual(_format_view_count(None), "0")

    @patch("yt_dlp.YoutubeDL")
    def test_analyze_video_url_success(self, mock_ytdl) -> None:
        mock_instance = MagicMock()
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        
        mock_instance.extract_info.return_value = {
            "title": "Rick Astley - Never Gonna Give You Up",
            "uploader": "Rick Astley",
            "duration": 213,
            "upload_date": "20091025",
            "view_count": 1000000,
            "thumbnails": [{"url": "http://example.com/thumb.jpg"}],
            "formats": [{"resolution": "1080p", "ext": "mp4"}]
        }
        
        metadata = analyze_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertFalse(metadata.is_playlist)
        self.assertEqual(metadata.title, "Rick Astley - Never Gonna Give You Up")
        self.assertEqual(metadata.uploader, "Rick Astley")
        self.assertEqual(metadata.duration, "3:33")
        self.assertEqual(metadata.upload_date, "2009-10-25")
        self.assertEqual(metadata.view_count, "1,000,000")
        self.assertEqual(metadata.thumbnail_url, "http://example.com/thumb.jpg")
        self.assertIn("1080p (mp4)", metadata.formats)

    @patch("yt_dlp.YoutubeDL")
    def test_analyze_playlist_url_success(self, mock_ytdl) -> None:
        mock_instance = MagicMock()
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        
        mock_instance.extract_info.return_value = {
            "_type": "playlist",
            "title": "My Favorite Tracks",
            "uploader": "MusicFan",
            "playlist_count": 10,
            "thumbnails": [{"url": "http://example.com/playlist.jpg"}],
            "entries": [{}, {}]
        }
        
        metadata = analyze_url("https://www.youtube.com/playlist?list=PL123")
        self.assertTrue(metadata.is_playlist)
        self.assertEqual(metadata.title, "My Favorite Tracks")
        self.assertEqual(metadata.uploader, "MusicFan")
        self.assertEqual(metadata.total_videos, 10)
        self.assertEqual(metadata.thumbnail_url, "http://example.com/playlist.jpg")

    @patch("yt_dlp.YoutubeDL")
    def test_analyze_url_age_restricted_error(self, mock_ytdl) -> None:
        mock_instance = MagicMock()
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("Sign in to confirm your age")
        
        with self.assertRaises(AgeRestrictedError):
            analyze_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    @patch("yt_dlp.YoutubeDL")
    def test_analyze_url_private_error(self, mock_ytdl) -> None:
        mock_instance = MagicMock()
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("This video is private")
        
        with self.assertRaises(VideoUnavailableError):
            analyze_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    @patch("yt_dlp.YoutubeDL")
    def test_analyze_url_network_error(self, mock_ytdl) -> None:
        mock_instance = MagicMock()
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("Unable to download API page: HTTP Error 404: Not Found")
        
        with self.assertRaises(NetworkError):
            analyze_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


if __name__ == "__main__":
    unittest.main()
