import unittest
from playlist_manager import PlaylistManager, PlaylistItem, PlaylistMetadata


class PlaylistManagerTests(unittest.TestCase):
    def test_parse_playlist(self) -> None:
        info = {
            "title": "My Playlist",
            "uploader": "Channel Owner",
            "playlist_count": 2,
            "entries": [
                {
                    "title": "Video 1",
                    "id": "vid1",
                    "duration": 120,
                    "thumbnail": "thumb1",
                    "uploader": "Uploader 1",
                    "upload_date": "20260720"
                },
                {
                    "title": "Video 2",
                    "id": "vid2",
                    "duration": 300,
                    "thumbnail": "thumb2",
                    "uploader": "Uploader 2",
                    "upload_date": "20260721"
                }
            ]
        }
        meta = PlaylistManager.parse_playlist(info)
        self.assertEqual(meta.title, "My Playlist")
        self.assertEqual(meta.uploader, "Channel Owner")
        self.assertEqual(len(meta.items), 2)
        
        self.assertEqual(meta.items[0].title, "Video 1")
        self.assertEqual(meta.items[0].duration_str, "2:00")
        self.assertEqual(meta.items[1].duration_str, "5:00")

    def test_filter_items(self) -> None:
        items = [
            PlaylistItem(
                index=1, 
                video_id="1", 
                title="Alpha Video", 
                url="url1", 
                duration_sec=100.0, 
                duration_str="1:40", 
                uploader="Owner", 
                thumbnail_url=None, 
                upload_date="20260720"
            ),
            PlaylistItem(
                index=2, 
                video_id="2", 
                title="Beta Video", 
                url="url2", 
                duration_sec=250.0, 
                duration_str="4:10", 
                uploader="Owner", 
                thumbnail_url=None, 
                upload_date="20260722"
            ),
        ]
        
        # Test title filter
        res = PlaylistManager.get_filtered_items(items, title_contains="alpha")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].video_id, "1")
        
        # Test duration filter
        res = PlaylistManager.get_filtered_items(items, min_duration=150.0)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].video_id, "2")
        
        # Test index filter
        res = PlaylistManager.get_filtered_items(items, index_start=2)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].video_id, "2")
        
        # Test date filter
        res = PlaylistManager.get_filtered_items(items, upload_date_after="2026-07-21")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].video_id, "2")


if __name__ == "__main__":
    unittest.main()
