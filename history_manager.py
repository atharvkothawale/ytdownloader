from __future__ import annotations

import csv
import json
import logging
import sqlite3
import contextlib
from pathlib import Path
from typing import Any, Generator
from datetime import datetime

logger = logging.getLogger("yt_downloader_pro.history_manager")


class HistoryManager:
    """Manages SQLite download history databases and exports."""

    def __init__(self, db_dir: Path | None = None) -> None:
        if db_dir is None:
            self.db_dir = Path(__file__).resolve().parent / "config"
        else:
            self.db_dir = db_dir
            
        self.db_file = self.db_dir / "history.db"
        self._init_db()

    @contextlib.contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a managed database connection that is guaranteed to close on exit."""
        conn = sqlite3.connect(self.db_file)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Establishes database structure schema on initialization."""
        try:
            self.db_dir.mkdir(parents=True, exist_ok=True)
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downloads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT UNIQUE,
                        title TEXT,
                        url TEXT,
                        download_date TEXT,
                        duration TEXT,
                        file_size INTEGER,
                        output_path TEXT,
                        status TEXT,
                        download_type TEXT,
                        quality TEXT,
                        thumbnail_path TEXT,
                        uploader TEXT,
                        is_playlist INTEGER,
                        avg_speed REAL
                    )
                    """
                )
                conn.commit()
            logger.info("Successfully initialized SQLite history database")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite history database: {e}")

    def add_record(
        self,
        task_id: str,
        title: str,
        url: str,
        duration: str,
        file_size: int,
        output_path: str,
        status: str,
        download_type: str,
        quality: str,
        thumbnail_path: str | None,
        uploader: str | None,
        is_playlist: bool = False,
        avg_speed: float | None = None,
    ) -> None:
        """Inserts or replaces a download event record in SQLite."""
        try:
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            playlist_flag = 1 if is_playlist else 0
            
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO downloads (
                        task_id, title, url, download_date, duration, file_size, 
                        output_path, status, download_type, quality, thumbnail_path, 
                        uploader, is_playlist, avg_speed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id, title, url, date_str, duration, file_size,
                        output_path, status, download_type, quality, thumbnail_path,
                        uploader, playlist_flag, avg_speed
                    )
                )
                conn.commit()
            logger.info(f"Recorded download history row for task: {task_id}")
        except Exception as e:
            logger.error(f"Failed to add download record to database: {e}")

    def get_records(
        self,
        search_query: str | None = None,
        status_filter: str | None = None,
        type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves and filters download history rows from SQLite."""
        query = "SELECT * FROM downloads WHERE 1=1"
        params: list[Any] = []
        
        if search_query:
            query += " AND (title LIKE ? OR uploader LIKE ? OR url LIKE ? OR download_date LIKE ?)"
            like_pat = f"%{search_query}%"
            params.extend([like_pat, like_pat, like_pat, like_pat])
            
        if status_filter and status_filter != "All":
            query += " AND status = ?"
            params.append(status_filter)
            
        if type_filter and type_filter != "All":
            if type_filter == "Videos":
                query += " AND download_type = 'Video (MP4)' AND is_playlist = 0"
            elif type_filter == "Playlists":
                query += " AND is_playlist = 1"
            elif type_filter == "Audio":
                query += " AND download_type = 'Audio (MP3)'"
                
        query += " ORDER BY download_date DESC"
        
        records: list[dict[str, Any]] = []
        try:
            with self._connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    records.append(dict(row))
        except Exception as e:
            logger.error(f"Failed to get records from database: {e}")
            
        return records

    def delete_record(self, task_id: str) -> None:
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM downloads WHERE task_id = ?", (task_id,))
                conn.commit()
            logger.info(f"Deleted download record: {task_id}")
        except Exception as e:
            logger.error(f"Failed to delete download record: {e}")

    def clear_all(self) -> None:
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM downloads")
                conn.commit()
            logger.info("Cleared all download history database rows")
        except Exception as e:
            logger.error(f"Failed to clear history database: {e}")

    def get_statistics(self) -> dict[str, Any]:
        """Calculates counters, active uploaders, sizes, and averages for history dashboard widgets."""
        stats = {
            "total": 0,
            "videos": 0,
            "playlists": 0,
            "audio": 0,
            "total_size": 0,
            "avg_speed": 0.0,
            "most_downloaded_channel": "N/A",
            "today_count": 0,
        }
        
        try:
            with self._connection() as conn:
                cursor = conn.cursor()
                
                # Basic counts
                cursor.execute("SELECT COUNT(*) FROM downloads")
                stats["total"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM downloads WHERE download_type = 'Video (MP4)' AND is_playlist = 0")
                stats["videos"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM downloads WHERE is_playlist = 1")
                stats["playlists"] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM downloads WHERE download_type = 'Audio (MP3)'")
                stats["audio"] = cursor.fetchone()[0]
                
                # Size
                cursor.execute("SELECT SUM(file_size) FROM downloads WHERE file_size IS NOT NULL")
                res_size = cursor.fetchone()[0]
                stats["total_size"] = res_size if res_size else 0
                
                # Speed average
                cursor.execute("SELECT AVG(avg_speed) FROM downloads WHERE avg_speed IS NOT NULL")
                res_speed = cursor.fetchone()[0]
                stats["avg_speed"] = res_speed if res_speed else 0.0
                
                # Today's downloads
                today_date = datetime.now().strftime("%Y-%m-%d")
                cursor.execute("SELECT COUNT(*) FROM downloads WHERE download_date LIKE ?", (f"{today_date}%",))
                stats["today_count"] = cursor.fetchone()[0]
                
                # Active channel uploader
                cursor.execute(
                    """
                    SELECT uploader, COUNT(*) as cnt 
                    FROM downloads 
                    WHERE uploader IS NOT NULL AND uploader != ''
                    GROUP BY uploader 
                    ORDER BY cnt DESC 
                    LIMIT 1
                    """
                )
                res_chan = cursor.fetchone()
                stats["most_downloaded_channel"] = res_chan[0] if res_chan else "N/A"
                
        except Exception as e:
            logger.error(f"Failed to calculate database statistics: {e}")
            
        return stats

    def export_csv(self, filepath: Path) -> None:
        """Exports download history as a CSV file."""
        records = self.get_records()
        try:
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "Title", "URL", "Download Date", "Duration", 
                        "File Size (Bytes)", "Output Path", "Status", 
                        "Type", "Quality", "Channel"
                    ]
                )
                for r in records:
                    writer.writerow(
                        [
                            r.get("title"), r.get("url"), r.get("download_date"),
                            r.get("duration"), r.get("file_size"), r.get("output_path"),
                            r.get("status"), r.get("download_type"), r.get("quality"),
                            r.get("uploader")
                        ]
                    )
            logger.info(f"Successfully exported download history to CSV: {filepath}")
        except Exception as e:
            logger.error(f"Failed to export history CSV: {e}")

    def export_json(self, filepath: Path) -> None:
        """Exports download history as a JSON file."""
        records = self.get_records()
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=4)
            logger.info(f"Successfully exported download history to JSON: {filepath}")
        except Exception as e:
            logger.error(f"Failed to export history JSON: {e}")
