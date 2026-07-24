import unittest
from unittest.mock import MagicMock
from download_manager import DownloadQueue, DownloadTask


class DownloadQueueTests(unittest.TestCase):
    def test_queue_adding_task(self) -> None:
        q = DownloadQueue()
        q._notify_changed = MagicMock()
        q.start = MagicMock()
        
        task = q.add_task(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir="C:/downloads",
            mode="Video (MP4)",
            quality_label="Best Available"
        )
        self.assertEqual(len(q.tasks), 1)
        self.assertEqual(task.status, "Pending")
        self.assertEqual(task.url, "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        q.start.assert_called_once()

    def test_queue_cancellation_pending_task(self) -> None:
        q = DownloadQueue()
        q._notify_changed = MagicMock()
        q.start = MagicMock()
        
        task = q.add_task(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir="C:/downloads",
            mode="Video (MP4)",
            quality_label="Best Available"
        )
        q.cancel_task(task.task_id)
        self.assertEqual(task.status, "Cancelled")
        q._notify_changed.assert_called()

    def test_queue_retry_failed_task(self) -> None:
        q = DownloadQueue()
        q._notify_changed = MagicMock()
        q.start = MagicMock()
        
        task = q.add_task(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            output_dir="C:/downloads",
            mode="Video (MP4)",
            quality_label="Best Available"
        )
        task.status = "Failed"
        task.error_msg = "Network Timeout"
        
        q.retry_task(task.task_id)
        self.assertEqual(task.status, "Pending")
        self.assertIsNone(task.error_msg)
        self.assertEqual(q.start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
