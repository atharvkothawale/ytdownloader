import unittest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime

from settings_manager import SettingsManager
from history_manager import HistoryManager


class SettingsManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_default_settings_creation(self) -> None:
        sm = SettingsManager(config_dir=self.test_dir)
        self.assertEqual(sm.get("theme"), "dark")
        self.assertEqual(sm.get("accent_color"), "blue")
        self.assertTrue(sm.settings_file.exists())

    def test_settings_save_and_reload(self) -> None:
        sm = SettingsManager(config_dir=self.test_dir)
        sm.set("theme", "light")
        sm.set("accent_color", "green")
        sm.set("last_download_folder", "C:/Downloads")

        # Load again in a new manager
        sm2 = SettingsManager(config_dir=self.test_dir)
        self.assertEqual(sm2.get("theme"), "light")
        self.assertEqual(sm2.get("accent_color"), "green")
        self.assertEqual(sm2.get("last_download_folder"), "C:/Downloads")


class HistoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp())
        self.hm = HistoryManager(db_dir=self.test_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir)

    def test_add_and_get_records(self) -> None:
        # Add single video download
        self.hm.add_record(
            task_id="task-1",
            title="Video One",
            url="https://youtube.com/watch?v=1",
            duration="1:30",
            file_size=1000000,
            output_path="C:/out",
            status="Completed",
            download_type="Video (MP4)",
            quality="1080p",
            thumbnail_path=None,
            uploader="Channel One",
            is_playlist=False,
            avg_speed=50000.0
        )

        # Add playlist audio download
        self.hm.add_record(
            task_id="task-2",
            title="Audio Two",
            url="https://youtube.com/watch?v=2",
            duration="2:45",
            file_size=500000,
            output_path="C:/out",
            status="Failed",
            download_type="Audio (MP3)",
            quality="Best Audio",
            thumbnail_path=None,
            uploader="Channel Two",
            is_playlist=True,
            avg_speed=10000.0
        )

        # Retrieve records
        records = self.hm.get_records()
        self.assertEqual(len(records), 2)
        
        # Test filters
        vids = self.hm.get_records(type_filter="Videos")
        self.assertEqual(len(vids), 1)
        self.assertEqual(vids[0]["task_id"], "task-1")

        auds = self.hm.get_records(type_filter="Audio")
        self.assertEqual(len(auds), 1)
        self.assertEqual(auds[0]["task_id"], "task-2")

        playlists = self.hm.get_records(type_filter="Playlists")
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["task_id"], "task-2")

        # Test Search
        search_res = self.hm.get_records(search_query="One")
        self.assertEqual(len(search_res), 1)
        self.assertEqual(search_res[0]["task_id"], "task-1")

    def test_statistics(self) -> None:
        self.hm.add_record(
            task_id="task-1",
            title="Video One",
            url="url1",
            duration="1:00",
            file_size=100,
            output_path="C:/out",
            status="Completed",
            download_type="Video (MP4)",
            quality="1080p",
            thumbnail_path=None,
            uploader="Uploader A",
            is_playlist=False,
            avg_speed=10.0
        )
        self.hm.add_record(
            task_id="task-2",
            title="Video Two",
            url="url2",
            duration="2:00",
            file_size=200,
            output_path="C:/out",
            status="Completed",
            download_type="Video (MP4)",
            quality="720p",
            thumbnail_path=None,
            uploader="Uploader A",
            is_playlist=True,
            avg_speed=20.0
        )

        stats = self.hm.get_statistics()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["videos"], 1)
        self.assertEqual(stats["playlists"], 1)
        self.assertEqual(stats["total_size"], 300)
        self.assertEqual(stats["most_downloaded_channel"], "Uploader A")

    def test_export_data(self) -> None:
        self.hm.add_record(
            task_id="task-1",
            title="Export Test",
            url="url1",
            duration="1:00",
            file_size=100,
            output_path="C:/out",
            status="Completed",
            download_type="Video (MP4)",
            quality="1080p",
            thumbnail_path=None,
            uploader="Uploader A",
            is_playlist=False,
            avg_speed=10.0
        )

        csv_file = self.test_dir / "history.csv"
        json_file = self.test_dir / "history.json"

        self.hm.export_csv(csv_file)
        self.hm.export_json(json_file)

        self.assertTrue(csv_file.exists())
        self.assertTrue(json_file.exists())

        # Validate JSON content
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["title"], "Export Test")


if __name__ == "__main__":
    unittest.main()
