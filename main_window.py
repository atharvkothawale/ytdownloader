from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any
from io import BytesIO

import customtkinter as ctk
from PIL import Image
import requests
from CTkMessagebox import CTkMessagebox

from analyzer import analyze_url, MediaMetadata, AnalysisError
from format_manager import FormatManager, DownloadOption, format_size
from download_manager import DownloadManager, DownloadCancelledError, DownloadQueue, DownloadTask
from playlist_manager import PlaylistManager, PlaylistMetadata, PlaylistItem
from settings_manager import SettingsManager
from history_manager import HistoryManager

logger = logging.getLogger("yt_downloader_pro.main_window")


class DownloadCompleteDialog(ctk.CTkToplevel):
    """Custom modal window to notify completion of downloads with folder actions."""

    def __init__(self, parent: ctk.CTk, title: str, output_dir: str, elapsed_time: float) -> None:
        super().__init__(parent)
        self.title("Download Complete")
        self.geometry("460x230")
        self.resizable(False, False)
        self.configure(fg_color="#0f172a")

        # Make modal dialog centered over parent
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        x = parent_x + (parent_w - 460) // 2
        y = parent_y + (parent_h - 230) // 2
        self.geometry(f"+{x}+{y}")

        # Components
        lbl_header = ctk.CTkLabel(self, text="Download Complete! 🎉", font=("Segoe UI", 16, "bold"), text_color="#38bdf8")
        lbl_header.pack(pady=(20, 10))

        lbl_file = ctk.CTkLabel(self, text=f"File: {title}", font=("Segoe UI", 11), text_color="#f8fafc", wraplength=400, justify="center")
        lbl_file.pack(pady=4)

        lbl_dir = ctk.CTkLabel(self, text=f"Output: {output_dir}", font=("Segoe UI", 10), text_color="#94a3b8", wraplength=400, justify="center")
        lbl_dir.pack(pady=4)

        lbl_time = ctk.CTkLabel(self, text=f"Elapsed Time: {elapsed_time:.1f}s", font=("Segoe UI", 10), text_color="#94a3b8")
        lbl_time.pack(pady=4)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=(16, 16))

        btn_open = ctk.CTkButton(
            btn_frame, 
            text="Open Folder", 
            font=("Segoe UI", 11, "bold"), 
            fg_color="#2563eb", 
            hover_color="#1d4ed8", 
            text_color="#ffffff", 
            width=130, 
            height=30,
            command=self._open_folder
        )
        btn_open.pack(side="left", padx=8)

        btn_close = ctk.CTkButton(
            btn_frame, 
            text="Download Another", 
            font=("Segoe UI", 11, "bold"), 
            fg_color="#1f2937", 
            hover_color="#374151", 
            text_color="#e5e7eb", 
            width=130, 
            height=30,
            command=self.destroy
        )
        btn_close.pack(side="left", padx=8)

        self.output_dir = output_dir

    def _open_folder(self) -> None:
        import os
        try:
            os.startfile(self.output_dir)
        except Exception as e:
            logger.error(f"Failed to open folder: {e}")
        self.destroy()


class MainWindow:
    """Main application window for YT Downloader Pro using CustomTkinter with tabbed views."""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("YT Downloader Pro")
        
        # Load settings
        self.settings = SettingsManager()
        self.history = HistoryManager()
        
        # Apply configurations
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        ctk.set_default_color_theme(self.settings.get("accent_color", "blue"))
        
        # Set Window geometry size
        self.root.geometry(self.settings.get("last_window_size", "1220x860"))
        self.root.geometry(self.settings.get("last_window_position", ""))
        self.root.minsize(1150, 800)
        self.root.configure(fg_color="#0f172a")

        # Dynamic download properties variables
        self.download_mode_var = ctk.StringVar(value=self.settings.get("last_download_type", "Video (MP4)"))
        last_folder = self.settings.get("last_download_folder")
        self.output_dir_var = ctk.StringVar(value=last_folder if last_folder else str(self._default_output_dir()))
        self.status_var = ctk.StringVar(value="Status: Ready")
        self.quality_var = ctk.StringVar(value=self.settings.get("last_quality", "Best available"))
        
        # Advanced Audio Options
        self.audio_format_var = ctk.StringVar(value="mp3")
        self.audio_quality_var = ctk.StringVar(value="Best Available")
        
        # Advanced Subtitle & Chapter Options
        self.subtitles_enabled_var = ctk.BooleanVar(value=False)
        self.subtitles_auto_var = ctk.BooleanVar(value=False)
        self.subtitles_lang_var = ctk.StringVar(value="en")
        self.subtitles_embed_var = ctk.BooleanVar(value=False)
        self.subtitles_separate_var = ctk.BooleanVar(value=False)
        self.chapters_embed_var = ctk.BooleanVar(value=False)
        self.chapters_export_var = ctk.BooleanVar(value=False)
        self.naming_template_var = ctk.StringVar(value="%(title)s")
        
        # Playlist scopes
        self.playlist_scope_var = ctk.StringVar(value="Selected Only")
        self.playlist_conflict_var = ctk.StringVar(value="Rename")

        # Format detection options state
        self.metadata: MediaMetadata | None = None
        self.video_options: list[DownloadOption] = []
        self.audio_option: DownloadOption | None = None
        
        # Playlist manager state
        self.playlist_metadata: PlaylistMetadata | None = None
        self.playlist_items: list[PlaylistItem] = []
        self.filtered_playlist_items: list[PlaylistItem] = []

        # Download Queue Manager
        self.queue = DownloadQueue()
        self.queue.on_queue_changed = self._on_queue_changed
        self.queue.on_task_progress = self._on_task_progress
        self.queue.on_queue_complete = self._on_queue_complete

        # Handle window shutdown logic to save geometries
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()

    def _default_output_dir(self) -> Path:
        return Path(__file__).resolve().parent / "downloads"

    def _build_ui(self) -> None:
        # 2 main layouts: Left Sidebar Navigation and Right Tab Container
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # ----------------- SIDEBAR -----------------
        sidebar = ctk.CTkFrame(self.root, fg_color="#111827", corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(6, weight=1)

        title_lbl = ctk.CTkLabel(sidebar, text="YT Downloader Pro", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        title_lbl.grid(row=0, column=0, sticky="w", padx=24, pady=(24, 4))
        
        subtitle_lbl = ctk.CTkLabel(sidebar, text="Professional Windows downloader", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        subtitle_lbl.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 24))

        # Nav Buttons
        self.nav_download_btn = ctk.CTkButton(sidebar, text="Download Center", font=("Segoe UI", 11, "bold"), fg_color="#1f2937", hover_color="#374151", command=lambda: self._select_tab("Download"))
        self.nav_download_btn.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 10))

        self.nav_history_btn = ctk.CTkButton(sidebar, text="Download History", font=("Segoe UI", 11, "bold"), fg_color="#1f2937", hover_color="#374151", command=lambda: self._select_tab("History"))
        self.nav_history_btn.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 10))

        self.nav_settings_btn = ctk.CTkButton(sidebar, text="Settings Options", font=("Segoe UI", 11, "bold"), fg_color="#1f2937", hover_color="#374151", command=lambda: self._select_tab("Settings"))
        self.nav_settings_btn.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 10))

        sidebar_status = ctk.CTkLabel(sidebar, text="Ready", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        sidebar_status.grid(row=7, column=0, sticky="sw", padx=24, pady=24)

        # ----------------- TABS FRAMES -----------------
        # Tab 1: Download frame
        self.download_frame = ctk.CTkFrame(self.root, fg_color="#0f172a", corner_radius=0)
        self._build_download_tab()

        # Tab 2: History frame
        self.history_frame = ctk.CTkFrame(self.root, fg_color="#0f172a", corner_radius=0)
        self._build_history_tab()

        # Tab 3: Settings frame
        self.settings_frame = ctk.CTkFrame(self.root, fg_color="#0f172a", corner_radius=0)
        self._build_settings_tab()

        # Default select Download Tab
        self._select_tab("Download")

    def _select_tab(self, tab_name: str) -> None:
        self.download_frame.grid_forget()
        self.history_frame.grid_forget()
        self.settings_frame.grid_forget()

        self.nav_download_btn.configure(fg_color="#1f2937")
        self.nav_history_btn.configure(fg_color="#1f2937")
        self.nav_settings_btn.configure(fg_color="#1f2937")

        if tab_name == "Download":
            self.download_frame.grid(row=0, column=1, sticky="nsew")
            self.nav_download_btn.configure(fg_color="#2563eb")
        elif tab_name == "History":
            self.history_frame.grid(row=0, column=1, sticky="nsew")
            self.nav_history_btn.configure(fg_color="#2563eb")
            self._refresh_history_tab()
        elif tab_name == "Settings":
            self.settings_frame.grid(row=0, column=1, sticky="nsew")
            self.nav_settings_btn.configure(fg_color="#2563eb")
            self._refresh_settings_tab()

    # =========================================================================
    # TAB 1: DOWNLOAD TAB BUILDER
    # =========================================================================
    def _build_download_tab(self) -> None:
        self.download_frame.grid_columnconfigure(0, weight=1)
        self.download_frame.grid_rowconfigure(0, weight=0)
        self.download_frame.grid_rowconfigure(1, weight=1)

        # Header
        header = ctk.CTkFrame(self.download_frame, fg_color="#111827", corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 6))
        header.grid_columnconfigure(0, weight=1)
        
        header_title = ctk.CTkLabel(header, text="Download Center", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        header_title.grid(row=0, column=0, sticky="w", padx=24, pady=(16, 4))
        
        header_subtitle = ctk.CTkLabel(header, text="Enter a URL, configure options, and queue downloads.", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        header_subtitle.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        # Main Scrollable Frame (where settings, widgets, queue list resides)
        self.main_card = ctk.CTkFrame(self.download_frame, fg_color="#111827", corner_radius=8)
        self.main_card.grid(row=1, column=0, sticky="nsew", padx=24, pady=(6, 24))
        self.main_card.grid_columnconfigure(0, weight=1)
        
        self.main_card.grid_rowconfigure(5, weight=1)  # Resizable preview panel
        self.main_card.grid_rowconfigure(7, weight=1)  # Resizable queue panel

        # URL Input
        url_lbl = ctk.CTkLabel(self.main_card, text="Enter URL", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        url_lbl.grid(row=0, column=0, sticky="w", padx=24, pady=(16, 2))
        self.url_entry = ctk.CTkEntry(self.main_card, font=("Segoe UI", 12), fg_color="#0f172a", border_color="#374151", text_color="#f8fafc", height=32)
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 12))

        # Options Panel
        options_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        options_panel.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 12))
        options_panel.grid_columnconfigure((1, 3), weight=1)

        # Download Type
        type_lbl = ctk.CTkLabel(options_panel, text="Download Type", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        type_lbl.grid(row=0, column=0, sticky="w", padx=(16, 8), pady=(12, 12))
        self.mode_combo = ctk.CTkComboBox(options_panel, variable=self.download_mode_var, values=["Video (MP4)", "Audio (MP3)"], state="readonly", fg_color="#111827", border_color="#374151", height=28, command=self._on_mode_change)
        self.mode_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=12)

        # Quality Resolution
        self.quality_lbl = ctk.CTkLabel(options_panel, text="Resolution", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        self.quality_lbl.grid(row=0, column=2, sticky="w", padx=(16, 8), pady=12)
        self.quality_combo = ctk.CTkComboBox(options_panel, variable=self.quality_var, values=["Best available"], state="disabled", fg_color="#111827", border_color="#374151", height=28, command=self._on_quality_change)
        self.quality_combo.grid(row=0, column=3, sticky="ew", padx=(0, 16), pady=12)
        self.best_audio_label = ctk.CTkLabel(options_panel, text="Best Audio", font=("Segoe UI", 11, "bold"), text_color="#cbd5e1", anchor="w")

        # Output Folder
        folder_lbl = ctk.CTkLabel(options_panel, text="Output Folder", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        folder_lbl.grid(row=1, column=0, sticky="w", padx=(16, 8), pady=(0, 12))
        folder_entry = ctk.CTkEntry(options_panel, textvariable=self.output_dir_var, fg_color="#111827", border_color="#374151", text_color="#f8fafc", height=26)
        folder_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(0, 12))
        self.folder_button = ctk.CTkButton(options_panel, text="Browse", font=("Segoe UI", 10, "bold"), fg_color="#111827", hover_color="#374151", text_color="#e5e7eb", border_width=1, border_color="#374151", width=80, height=26, command=self._choose_folder)
        self.folder_button.grid(row=1, column=3, sticky="w", padx=(10, 16), pady=(0, 12))

        # Advanced Settings Frame (Milestone 8 expand options)
        adv_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        adv_panel.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 12))
        adv_panel.grid_columnconfigure((1, 3, 5), weight=1)

        # Audio Codec selectors
        lbl_acodec = ctk.CTkLabel(adv_panel, text="Audio Codec", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        lbl_acodec.grid(row=0, column=0, sticky="w", padx=(12, 6), pady=8)
        self.combo_acodec = ctk.CTkComboBox(adv_panel, variable=self.audio_format_var, values=["mp3", "m4a", "flac", "wav", "opus"], state="readonly", height=22, font=("Segoe UI", 10), fg_color="#111827", border_color="#374151")
        self.combo_acodec.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=8)

        # Audio quality bitrate selectors
        lbl_abitrate = ctk.CTkLabel(adv_panel, text="Bitrate", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        lbl_abitrate.grid(row=0, column=2, sticky="w", padx=(12, 6), pady=8)
        self.combo_abitrate = ctk.CTkComboBox(adv_panel, variable=self.audio_quality_var, values=["Best Available", "320 kbps", "256 kbps", "192 kbps", "128 kbps"], state="readonly", height=22, font=("Segoe UI", 10), fg_color="#111827", border_color="#374151")
        self.combo_abitrate.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=8)

        # Output Naming templates selector
        lbl_name = ctk.CTkLabel(adv_panel, text="Naming Template", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        lbl_name.grid(row=0, column=4, sticky="w", padx=(12, 6), pady=8)
        self.combo_name_template = ctk.CTkComboBox(adv_panel, variable=self.naming_template_var, values=["%(title)s", "%(channel)s - %(title)s", "%(playlist_index)s - %(title)s"], state="readonly", height=22, font=("Segoe UI", 10), fg_color="#111827", border_color="#374151")
        self.combo_name_template.grid(row=0, column=5, sticky="ew", padx=(0, 12), pady=8)

        # Subtitles configurations row
        sub_frame = ctk.CTkFrame(adv_panel, fg_color="transparent")
        sub_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=12, pady=4)
        
        chk_sub = ctk.CTkCheckBox(sub_frame, text="Download Subs", variable=self.subtitles_enabled_var, font=("Segoe UI", 10, "bold"))
        chk_sub.pack(side="left", padx=(0, 12))
        
        chk_auto_sub = ctk.CTkCheckBox(sub_frame, text="Auto Captions", variable=self.subtitles_auto_var, font=("Segoe UI", 10, "bold"))
        chk_auto_sub.pack(side="left", padx=12)

        lbl_sub_lang = ctk.CTkLabel(sub_frame, text="Lang:", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        lbl_sub_lang.pack(side="left", padx=(12, 4))
        self.combo_sub_lang = ctk.CTkComboBox(sub_frame, variable=self.subtitles_lang_var, values=["en", "es", "fr", "de", "ja"], state="readonly", width=70, height=20, font=("Segoe UI", 9), fg_color="#111827", border_color="#374151")
        self.combo_sub_lang.pack(side="left", padx=4)

        chk_embed_sub = ctk.CTkCheckBox(sub_frame, text="Embed into MP4", variable=self.subtitles_embed_var, font=("Segoe UI", 10, "bold"))
        chk_embed_sub.pack(side="left", padx=12)

        chk_sep_sub = ctk.CTkCheckBox(sub_frame, text="Save Separately", variable=self.subtitles_separate_var, font=("Segoe UI", 10, "bold"))
        chk_sep_sub.pack(side="left", padx=12)

        # Chapters configurations row
        chapters_frame = ctk.CTkFrame(adv_panel, fg_color="transparent")
        chapters_frame.grid(row=2, column=0, columnspan=6, sticky="ew", padx=12, pady=(4, 12))

        chk_embed_chap = ctk.CTkCheckBox(chapters_frame, text="Embed Chapters", variable=self.chapters_embed_var, font=("Segoe UI", 10, "bold"))
        chk_embed_chap.pack(side="left", padx=(0, 12))

        chk_exp_chap = ctk.CTkCheckBox(chapters_frame, text="Export Chapters text", variable=self.chapters_export_var, font=("Segoe UI", 10, "bold"))
        chk_exp_chap.pack(side="left", padx=12)

        # Action Row (Buttons)
        action_row = ctk.CTkFrame(self.main_card, fg_color="transparent")
        action_row.grid(row=4, column=0, sticky="ew", padx=24, pady=(0, 12))
        
        self.analyze_button = ctk.CTkButton(action_row, text="Analyze URL", font=("Segoe UI", 11, "bold"), fg_color="#1f2937", hover_color="#374151", text_color="#e5e7eb", border_width=1, border_color="#374151", width=120, height=35, command=self._analyze_action)
        self.analyze_button.pack(side="left", padx=(0, 10))

        self.download_button = ctk.CTkButton(action_row, text="Add to Queue", font=("Segoe UI", 11, "bold"), fg_color="#2563eb", hover_color="#1d4ed8", text_color="#ffffff", width=120, height=35, state="disabled", command=self._download_action)
        self.download_button.pack(side="left", padx=(0, 10))

        # Preview Panel
        self.preview_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        self.preview_panel.grid(row=5, column=0, sticky="nsew", padx=24, pady=(0, 12))
        self.preview_panel.grid_columnconfigure(0, weight=1)
        self.preview_panel.grid_columnconfigure(1, weight=2)
        self.preview_panel.grid_rowconfigure(0, weight=1)

        self.preview_placeholder = ctk.CTkLabel(
            self.preview_panel,
            text="No media analyzed. Insert a YouTube URL to retrieve details.",
            font=("Segoe UI", 11),
            text_color="#94a3b8",
            wraplength=600,
            justify="left",
            anchor="w"
        )
        self.preview_placeholder.grid(row=0, column=0, columnspan=2, sticky="nw", padx=16, pady=16)

        # Progress Dashboard Frame
        self.progress_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        self.progress_panel.grid(row=6, column=0, sticky="ew", padx=24, pady=(0, 12))
        self.progress_panel.grid_columnconfigure(0, weight=1)

        self.current_file_label = ctk.CTkLabel(self.progress_panel, text="No active download", font=("Segoe UI", 11, "bold"), text_color="#f8fafc", anchor="w")
        self.current_file_label.grid(row=0, column=0, sticky="w", padx=16, pady=(10, 2))

        self.video_progress_lbl = ctk.CTkLabel(self.progress_panel, text="Current Video: 0%", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        self.video_progress_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 2))
        self.progress_bar = ctk.CTkProgressBar(self.progress_panel, progress_color="#3b82f6", fg_color="#111827", height=8)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.progress_bar.set(0.0)

        self.playlist_progress_lbl = ctk.CTkLabel(self.progress_panel, text="Overall Progress: 0%", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        self.playlist_progress_bar = ctk.CTkProgressBar(self.progress_panel, progress_color="#22c55e", fg_color="#111827", height=8)

        # Stats grid
        self.stats_frame = ctk.CTkFrame(self.progress_panel, fg_color="transparent")
        self.stats_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 10))
        self.stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_status = ctk.CTkLabel(self.stats_frame, text="Status: Ready", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_status.grid(row=0, column=0, sticky="w")

        self.stat_speed = ctk.CTkLabel(self.stats_frame, text="Speed: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_speed.grid(row=0, column=1, sticky="w")

        self.stat_eta = ctk.CTkLabel(self.stats_frame, text="ETA: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_eta.grid(row=0, column=2, sticky="w")

        self.stat_size = ctk.CTkLabel(self.stats_frame, text="Downloaded: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_size.grid(row=0, column=3, sticky="w")

        # Scrollable Queue panel
        self.queue_frame = ctk.CTkScrollableFrame(self.main_card, label_text="Download Queue List", height=130, fg_color="#1f2937")
        self.queue_frame.grid(row=7, column=0, sticky="ew", padx=24, pady=(0, 16))
        self._render_queue()

    # =========================================================================
    # TAB 2: HISTORY TAB BUILDER
    # =========================================================================
    def _build_history_tab(self) -> None:
        self.history_frame.grid_columnconfigure(0, weight=1)
        self.history_frame.grid_rowconfigure(1, weight=1)

        # Header
        h_frame = ctk.CTkFrame(self.history_frame, fg_color="#111827", corner_radius=8)
        h_frame.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 6))
        h_frame.grid_columnconfigure(0, weight=1)

        h_title = ctk.CTkLabel(h_frame, text="Downloads Log Database", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        h_title.grid(row=0, column=0, sticky="w", padx=24, pady=(16, 4))
        h_desc = ctk.CTkLabel(h_frame, text="View log history list, search database entries, and export stats.", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        h_desc.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        # Main History panel card
        self.history_card = ctk.CTkFrame(self.history_frame, fg_color="#111827", corner_radius=8)
        self.history_card.grid(row=1, column=0, sticky="nsew", padx=24, pady=(6, 24))
        self.history_card.grid_columnconfigure(0, weight=1)
        self.history_card.grid_rowconfigure(2, weight=1)

        # Filters toolbar Row
        tool_frame = ctk.CTkFrame(self.history_card, fg_color="#1f2937", corner_radius=6)
        tool_frame.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 10))
        tool_frame.grid_columnconfigure(0, weight=2)

        # Search Entry
        self.hist_search_entry = ctk.CTkEntry(tool_frame, placeholder_text="Search database...", font=("Segoe UI", 11), height=28, fg_color="#0f172a", border_color="#374151")
        self.hist_search_entry.grid(row=0, column=0, sticky="ew", padx=(12, 10), pady=10)
        self.hist_search_entry.bind("<KeyRelease>", lambda e: self._refresh_history_tab())

        # Status filter combo
        self.hist_status_filter = ctk.StringVar(value="All")
        self.combo_status_filter = ctk.CTkComboBox(tool_frame, variable=self.hist_status_filter, values=["All", "Completed", "Failed", "Cancelled"], font=("Segoe UI", 10), width=110, height=28, state="readonly", fg_color="#111827", border_color="#374151", command=lambda v: self._refresh_history_tab())
        self.combo_status_filter.grid(row=0, column=1, sticky="w", padx=6, pady=10)

        # Media Type filter combo
        self.hist_type_filter = ctk.StringVar(value="All")
        self.combo_type_filter = ctk.CTkComboBox(tool_frame, variable=self.hist_type_filter, values=["All", "Videos", "Playlists", "Audio"], font=("Segoe UI", 10), width=110, height=28, state="readonly", fg_color="#111827", border_color="#374151", command=lambda v: self._refresh_history_tab())
        self.combo_type_filter.grid(row=0, column=2, sticky="w", padx=6, pady=10)

        # Export buttons
        btn_csv = ctk.CTkButton(tool_frame, text="Export CSV", font=("Segoe UI", 10, "bold"), width=80, height=28, fg_color="#111827", hover_color="#374151", text_color="#cbd5e1", command=self._export_history_csv)
        btn_csv.grid(row=0, column=3, sticky="w", padx=6, pady=10)

        btn_json = ctk.CTkButton(tool_frame, text="Export JSON", font=("Segoe UI", 10, "bold"), width=80, height=28, fg_color="#111827", hover_color="#374151", text_color="#cbd5e1", command=self._export_history_json)
        btn_json.grid(row=0, column=4, sticky="w", padx=(6, 12), pady=10)

        # Statistics Dashboard row cards
        self.stats_dash_frame = ctk.CTkFrame(self.history_card, fg_color="transparent")
        self.stats_dash_frame.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 10))
        self.stats_dash_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.card_total = self._create_stat_card(self.stats_dash_frame, "Total Tasks", "0", 0)
        self.card_videos = self._create_stat_card(self.stats_dash_frame, "Single Videos", "0", 1)
        self.card_playlists = self._create_stat_card(self.stats_dash_frame, "Playlist items", "0", 2)
        self.card_size = self._create_stat_card(self.stats_dash_frame, "Storage Used", "0 B", 3)

        # Scrollable table container
        self.history_list_frame = ctk.CTkScrollableFrame(self.history_card, label_text="Download Logs Database", fg_color="#111827", height=230)
        self.history_list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 20))

    def _create_stat_card(self, parent: ctk.CTkFrame, label: str, value: str, col: int) -> ctk.CTkLabel:
        card = ctk.CTkFrame(parent, fg_color="#1f2937", corner_radius=6, height=50)
        card.grid(row=0, column=col, sticky="ew", padx=4)
        card.grid_columnconfigure(0, weight=1)
        
        lbl_title = ctk.CTkLabel(card, text=label, font=("Segoe UI", 9, "bold"), text_color="#94a3b8")
        lbl_title.grid(row=0, column=0, pady=(4, 0))
        
        lbl_val = ctk.CTkLabel(card, text=value, font=("Segoe UI", 12, "bold"), text_color="#38bdf8")
        lbl_val.grid(row=1, column=0, pady=(0, 4))
        return lbl_val

    def _refresh_history_tab(self) -> None:
        # Update Stats display
        stats = self.history.get_statistics()
        self.card_total.configure(text=str(stats["total"]))
        self.card_videos.configure(text=str(stats["videos"]))
        self.card_playlists.configure(text=str(stats["playlists"]))
        self.card_size.configure(text=format_size(stats["total_size"]))

        # Populate rows
        for widget in self.history_list_frame.winfo_children():
            widget.destroy()

        search_q = self.hist_search_entry.get().strip() or None
        records = self.history.get_records(
            search_query=search_q,
            status_filter=self.hist_status_filter.get(),
            type_filter=self.hist_type_filter.get()
        )

        if not records:
            empty_lbl = ctk.CTkLabel(self.history_list_frame, text="No download history logs found matching filters.", font=("Segoe UI", 11), text_color="#94a3b8")
            empty_lbl.pack(pady=30)
            return

        for r in records:
            row = ctk.CTkFrame(self.history_list_frame, fg_color="#1f2937")
            row.pack(fill="x", padx=4, pady=4)
            
            # Type indicator icon / tag
            is_video = r.get("download_type") == "Video (MP4)"
            tag_color = "#3b82f6" if is_video else "#ec4899"
            tag_text = "VIDEO" if is_video else "AUDIO"
            if r.get("is_playlist"):
                tag_text += " (PLAYLIST)"
                tag_color = "#22c55e"
                
            tag_lbl = ctk.CTkLabel(row, text=tag_text, font=("Segoe UI", 8, "bold"), text_color="#ffffff", fg_color=tag_color, corner_radius=4, width=80)
            tag_lbl.pack(side="left", padx=8, pady=4)

            # Details: Title, channel, date
            title_text = r.get("title") or "Unknown"
            info_text = f"Channel: {r.get('uploader') or 'N/A'} • Size: {format_size(r.get('file_size'))} • Date: {r.get('download_date')}"
            
            desc_frame = ctk.CTkFrame(row, fg_color="transparent")
            desc_frame.pack(side="left", fill="x", expand=True, padx=4, pady=2)
            
            t_lbl = ctk.CTkLabel(desc_frame, text=title_text, font=("Segoe UI", 11, "bold"), text_color="#f8fafc", anchor="w", justify="left", wraplength=480)
            t_lbl.pack(side="top", anchor="w")
            
            sub_lbl = ctk.CTkLabel(desc_frame, text=info_text, font=("Segoe UI", 9), text_color="#94a3b8", anchor="w")
            sub_lbl.pack(side="top", anchor="w")

            # Status Badge
            status = r.get("status") or "N/A"
            status_colors = {
                "Completed": "#22c55e",
                "Failed": "#ef4444",
                "Cancelled": "#94a3b8"
            }
            s_color = status_colors.get(status, "#cbd5e1")
            status_lbl = ctk.CTkLabel(row, text=status, font=("Segoe UI", 9, "bold"), text_color=s_color, width=80)
            status_lbl.pack(side="left", padx=8)

            # Actions buttons: Open Folder, Redownload, Delete
            btn_folder = ctk.CTkButton(
                row, 
                text="Folder", 
                font=("Segoe UI", 9, "bold"), 
                width=50, 
                height=20, 
                fg_color="#111827", 
                hover_color="#374151", 
                text_color="#e5e7eb",
                command=lambda p=r.get("output_path"): self._open_history_folder(p)
            )
            btn_folder.pack(side="left", padx=4)

            btn_redownload = ctk.CTkButton(
                row, 
                text="Redownload", 
                font=("Segoe UI", 9, "bold"), 
                width=75, 
                height=20, 
                fg_color="#2563eb", 
                hover_color="#1d4ed8", 
                text_color="#ffffff",
                command=lambda u=r.get("url"): self._redownload_history_item(u)
            )
            btn_redownload.pack(side="left", padx=4)

            btn_del = ctk.CTkButton(
                row, 
                text="Delete", 
                font=("Segoe UI", 9, "bold"), 
                width=50, 
                height=20, 
                fg_color="#ef4444", 
                hover_color="#dc2626", 
                text_color="#ffffff",
                command=lambda tid=r.get("task_id"): self._delete_history_item(tid)
            )
            btn_del.pack(side="left", padx=(4, 8))

    def _open_history_folder(self, path_str: str | None) -> None:
        if path_str:
            import os
            try:
                os.startfile(path_str)
            except Exception as e:
                logger.error(f"Failed to open folder: {e}")

    def _redownload_history_item(self, url: str | None) -> None:
        if url:
            self._select_tab("Download")
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self._analyze_action()

    def _delete_history_item(self, task_id: str | None) -> None:
        if task_id:
            self.history.delete_record(task_id)
            self._refresh_history_tab()

    def _export_history_csv(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(title="Save CSV History", filetypes=[("CSV Files", "*.csv")], defaultextension=".csv")
        if path:
            self.history.export_csv(Path(path))
            CTkMessagebox(title="Export Complete", message="Database history successfully exported to CSV.", icon="info")

    def _export_history_json(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(title="Save JSON History", filetypes=[("JSON Files", "*.json")], defaultextension=".json")
        if path:
            self.history.export_json(Path(path))
            CTkMessagebox(title="Export Complete", message="Database history successfully exported to JSON.", icon="info")

    # =========================================================================
    # TAB 3: SETTINGS TAB BUILDER
    # =========================================================================
    def _build_settings_tab(self) -> None:
        self.settings_frame.grid_columnconfigure(0, weight=1)
        self.settings_frame.grid_rowconfigure(1, weight=1)

        # Header
        h_frame = ctk.CTkFrame(self.settings_frame, fg_color="#111827", corner_radius=8)
        h_frame.grid(row=0, column=0, sticky="ew", padx=24, pady=(24, 6))
        h_frame.grid_columnconfigure(0, weight=1)

        h_title = ctk.CTkLabel(h_frame, text="Preferences & Settings", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        h_title.grid(row=0, column=0, sticky="w", padx=24, pady=(16, 4))
        h_desc = ctk.CTkLabel(h_frame, text="Customize interface appearance options, downloads configurations, and performance buffer values.", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        h_desc.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 16))

        # Main Settings Scroll Panel
        self.settings_scroll = ctk.CTkScrollableFrame(self.settings_frame, fg_color="#111827", corner_radius=8)
        self.settings_scroll.grid(row=1, column=0, sticky="nsew", padx=24, pady=(6, 24))
        self.settings_scroll.grid_columnconfigure(0, weight=1)

        # Section 1: Appearance Settings
        app_box = ctk.CTkFrame(self.settings_scroll, fg_color="#1f2937", corner_radius=6)
        app_box.pack(fill="x", padx=16, pady=8)
        app_box.grid_columnconfigure((1, 3), weight=1)

        lbl_app_sec = ctk.CTkLabel(app_box, text="Appearance Styles", font=("Segoe UI", 11, "bold"), text_color="#38bdf8")
        lbl_app_sec.grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 4))

        lbl_theme = ctk.CTkLabel(app_box, text="Theme Color", font=("Segoe UI", 10, "bold"), text_color="#e2e8f0")
        lbl_theme.grid(row=1, column=0, sticky="w", padx=(16, 8), pady=8)
        self.combo_theme = ctk.CTkComboBox(app_box, values=["dark", "light", "system"], font=("Segoe UI", 10), height=24, state="readonly", fg_color="#111827", border_color="#374151", command=self._on_theme_change)
        self.combo_theme.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=8)

        lbl_accent = ctk.CTkLabel(app_box, text="Accent Color", font=("Segoe UI", 10, "bold"), text_color="#e2e8f0")
        lbl_accent.grid(row=1, column=2, sticky="w", padx=(16, 8), pady=8)
        self.combo_accent = ctk.CTkComboBox(app_box, values=["blue", "green", "dark-blue"], font=("Segoe UI", 10), height=24, state="readonly", fg_color="#111827", border_color="#374151", command=self._on_accent_change)
        self.combo_accent.grid(row=1, column=3, sticky="ew", padx=(0, 16), pady=8)

        # Section 2: Downloads Preferences
        dl_box = ctk.CTkFrame(self.settings_scroll, fg_color="#1f2937", corner_radius=6)
        dl_box.pack(fill="x", padx=16, pady=8)

        lbl_dl_sec = ctk.CTkLabel(dl_box, text="Downloads Engine Options", font=("Segoe UI", 11, "bold"), text_color="#38bdf8")
        lbl_dl_sec.pack(anchor="w", padx=16, pady=(10, 4))

        self.chk_auto_folder = ctk.CTkCheckBox(dl_box, text="Auto Create Output Folders", font=("Segoe UI", 10, "bold"), command=lambda: self.settings.set("auto_create_folders", self.chk_auto_folder.get() == 1))
        self.chk_auto_folder.pack(anchor="w", padx=24, pady=6)

        self.chk_skip_ex = ctk.CTkCheckBox(dl_box, text="Skip Downloading Existing Files", font=("Segoe UI", 10, "bold"), command=lambda: self.settings.set("skip_existing_files", self.chk_skip_ex.get() == 1))
        self.chk_skip_ex.pack(anchor="w", padx=24, pady=6)

        self.chk_open_fol = ctk.CTkCheckBox(dl_box, text="Auto Open Folder after Completion", font=("Segoe UI", 10, "bold"), command=lambda: self.settings.set("auto_open_folder", self.chk_open_fol.get() == 1))
        self.chk_open_fol.pack(anchor="w", padx=24, pady=6)

        self.chk_del_temp = ctk.CTkCheckBox(dl_box, text="Delete Transcoding Temporary Files", font=("Segoe UI", 10, "bold"), command=lambda: self.settings.set("delete_temp_files", self.chk_del_temp.get() == 1))
        self.chk_del_temp.pack(anchor="w", padx=24, pady=6)

        # Section 3: Performance Config
        perf_box = ctk.CTkFrame(self.settings_scroll, fg_color="#1f2937", corner_radius=6)
        perf_box.pack(fill="x", padx=16, pady=8)
        perf_box.grid_columnconfigure((1, 3), weight=1)

        lbl_perf_sec = ctk.CTkLabel(perf_box, text="Performance Controls", font=("Segoe UI", 11, "bold"), text_color="#38bdf8")
        lbl_perf_sec.grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 4))

        lbl_retries = ctk.CTkLabel(perf_box, text="Retry Attempts", font=("Segoe UI", 10, "bold"), text_color="#e2e8f0")
        lbl_retries.grid(row=1, column=0, sticky="w", padx=(16, 8), pady=8)
        self.entry_retries = ctk.CTkEntry(perf_box, font=("Segoe UI", 10), height=24, fg_color="#111827", border_color="#374151")
        self.entry_retries.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=8)
        self.entry_retries.bind("<KeyRelease>", lambda e: self._on_int_setting_change("retry_attempts", self.entry_retries.get()))

        lbl_buf = ctk.CTkLabel(perf_box, text="Download Buffer (KB)", font=("Segoe UI", 10, "bold"), text_color="#e2e8f0")
        lbl_buf.grid(row=1, column=2, sticky="w", padx=(16, 8), pady=8)
        self.entry_buffer = ctk.CTkEntry(perf_box, font=("Segoe UI", 10), height=24, fg_color="#111827", border_color="#374151")
        self.entry_buffer.grid(row=1, column=3, sticky="ew", padx=(0, 16), pady=8)
        self.entry_buffer.bind("<KeyRelease>", lambda e: self._on_int_setting_change("buffer_size", self.entry_buffer.get()))

        # Section 4: Storage Displays and Clears
        store_box = ctk.CTkFrame(self.settings_scroll, fg_color="#1f2937", corner_radius=6)
        store_box.pack(fill="x", padx=16, pady=8)
        store_box.grid_columnconfigure((1, 3), weight=1)

        lbl_store_sec = ctk.CTkLabel(store_box, text="Storage & Database Cache", font=("Segoe UI", 11, "bold"), text_color="#38bdf8")
        lbl_store_sec.grid(row=0, column=0, columnspan=4, sticky="w", padx=16, pady=(10, 4))

        self.lbl_cache_size = ctk.CTkLabel(store_box, text="Temporary Cache Size: calculating...", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        self.lbl_cache_size.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=6)

        self.lbl_db_size = ctk.CTkLabel(store_box, text="Database History Size: calculating...", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1")
        self.lbl_db_size.grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=6)

        btn_clear_cache = ctk.CTkButton(store_box, text="Clear Cache Files", font=("Segoe UI", 10, "bold"), fg_color="#ef4444", hover_color="#dc2626", text_color="#ffffff", width=120, command=self._clear_cache_folders)
        btn_clear_cache.grid(row=1, column=2, sticky="w", padx=16, pady=6)

        btn_clear_db = ctk.CTkButton(store_box, text="Clear Database Logs", font=("Segoe UI", 10, "bold"), fg_color="#ef4444", hover_color="#dc2626", text_color="#ffffff", width=120, command=self._clear_history_database)
        btn_clear_db.grid(row=2, column=2, sticky="w", padx=16, pady=6)

    def _refresh_settings_tab(self) -> None:
        self.combo_theme.set(self.settings.get("theme"))
        self.combo_accent.set(self.settings.get("accent_color"))
        
        self.chk_auto_folder.select() if self.settings.get("auto_create_folders") else self.chk_auto_folder.deselect()
        self.chk_skip_ex.select() if self.settings.get("skip_existing_files") else self.chk_skip_ex.deselect()
        self.chk_open_fol.select() if self.settings.get("auto_open_folder") else self.chk_open_fol.deselect()
        self.chk_del_temp.select() if self.settings.get("delete_temp_files") else self.chk_del_temp.deselect()
        
        self.entry_retries.delete(0, "end")
        self.entry_retries.insert(0, str(self.settings.get("retry_attempts")))
        
        self.entry_buffer.delete(0, "end")
        self.entry_buffer.insert(0, str(self.settings.get("buffer_size")))

        # Get cache files sizes
        try:
            cache_size = sum(f.stat().st_size for f in self._default_output_dir().glob("*") if f.is_file())
            self.lbl_cache_size.configure(text=f"Temporary Cache Size: {format_size(cache_size)}")
        except Exception:
            self.lbl_cache_size.configure(text="Temporary Cache Size: 0 B")

        # Get DB file sizes
        try:
            db_size = self.history.db_file.stat().st_size
            self.lbl_db_size.configure(text=f"Database History Size: {format_size(db_size)}")
        except Exception:
            self.lbl_db_size.configure(text="Database History Size: 0 B")

    def _on_theme_change(self, val: str) -> None:
        self.settings.set("theme", val)
        ctk.set_appearance_mode(val)

    def _on_accent_change(self, val: str) -> None:
        self.settings.set("accent_color", val)
        ctk.set_default_color_theme(val)
        # CustomTkinter default theme changes require restart to apply fully, but we persist the JSON value

    def _on_int_setting_change(self, key: str, val_str: str) -> None:
        if val_str.isdigit():
            self.settings.set(key, int(val_str))

    def _clear_cache_folders(self) -> None:
        # Deletes temp cache files in output downloads folders
        try:
            for f in self._default_output_dir().glob("*"):
                if f.is_file():
                    f.unlink()
            self._refresh_settings_tab()
            CTkMessagebox(title="Cache Cleared", message="Output download folders cleared successfully.", icon="info")
        except Exception as e:
            logger.error(f"Failed to clear cache folders: {e}")

    def _clear_history_database(self) -> None:
        if CTkMessagebox(title="Confirm Clear", message="Are you sure you want to clear all history records? This cannot be undone.", icon="warning", option_1="Yes", option_2="No").get() == "Yes":
            self.history.clear_all()
            self._refresh_settings_tab()
            self._refresh_history_tab()

    # =========================================================================
    # TAB 1 ACTION METHODS: ANALYZE AND DOWNLOAD LOGIC
    # =========================================================================
    def _choose_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Choose download folder")
        if folder:
            self.output_dir_var.set(folder)
            self.settings.set("last_download_folder", folder)

    def _on_mode_change(self, mode: str) -> None:
        self.settings.set("last_download_type", mode)
        is_analyzed_video = self.metadata is not None and not self.metadata.is_playlist
        
        if mode == "Audio (MP3)":
            self.quality_combo.grid_forget()
            self.best_audio_label.grid(row=0, column=3, sticky="w", padx=(0, 16), pady=12)
        else:
            self.best_audio_label.grid_forget()
            self.quality_combo.grid(row=0, column=3, sticky="ew", padx=(0, 16), pady=12)
            
            if is_analyzed_video and self.video_options:
                labels = [opt.quality_label for opt in self.video_options]
                self.quality_combo.configure(values=labels)
                self.quality_combo.configure(state="normal")
                self.quality_var.set(labels[0] if labels else "Best available")
            else:
                self.quality_combo.configure(values=["Best available"])
                self.quality_combo.configure(state="disabled")
                self.quality_var.set("Best available")

        self._update_format_details()

    def _on_quality_change(self, quality: str) -> None:
        self.settings.set("last_quality", quality)
        self._update_format_details()

    def _download_action(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Status: please enter a YouTube URL first")
            return

        conflict = self.playlist_conflict_var.get()
        if self.settings.get("skip_existing_files"):
            conflict = "Skip"

        if self.metadata is not None and self.metadata.is_playlist:
            scope = self.playlist_scope_var.get()
            if scope == "Selected Only":
                download_items = [item for item in self.playlist_items if item.is_selected]
            else:
                download_items = list(self.playlist_items)
                
            if not download_items:
                self.status_var.set("Status: no videos selected for download")
                return
                
            for item in download_items:
                self.queue.add_task(
                    url=item.url,
                    output_dir=self.output_dir_var.get(),
                    mode=self.download_mode_var.get(),
                    quality_label=self.quality_var.get(),
                    video_format_id=None,
                    audio_format_id=None,
                    conflict_option=conflict,
                    subtitles_enabled=self.subtitles_enabled_var.get(),
                    subtitles_auto=self.subtitles_auto_var.get(),
                    subtitles_lang=self.subtitles_lang_var.get(),
                    subtitles_embed=self.subtitles_embed_var.get(),
                    subtitles_separate=self.subtitles_separate_var.get(),
                    chapters_embed=self.chapters_embed_var.get(),
                    chapters_export=self.chapters_export_var.get(),
                    naming_template=self.naming_template_var.get(),
                    audio_format=self.audio_format_var.get(),
                    audio_quality=self.audio_quality_var.get(),
                    uploader=item.uploader or "Unknown Channel",
                    is_playlist=True,
                )
            self.status_var.set(f"Status: Added {len(download_items)} playlist items to queue")
        else:
            video_format_id = None
            audio_format_id = None
            uploader_name = "Unknown Channel"
            
            is_analyzed_video = self.metadata is not None and not self.metadata.is_playlist
            if is_analyzed_video:
                uploader_name = self.metadata.uploader or "Unknown Channel"
                mode = self.download_mode_var.get()
                if mode == "Audio (MP3)":
                    if self.audio_option and self.audio_option.audio_format:
                        audio_format_id = self.audio_option.audio_format.format_id
                else:
                    selected_quality = self.quality_var.get()
                    matching_opt = None
                    if self.video_options:
                        for opt in self.video_options:
                            if opt.quality_label == selected_quality:
                                matching_opt = opt
                                break
                    if matching_opt:
                        if matching_opt.video_format:
                            video_format_id = matching_opt.video_format.format_id
                        if matching_opt.audio_format:
                            audio_format_id = matching_opt.audio_format.format_id

            self.queue.add_task(
                url=url,
                output_dir=self.output_dir_var.get(),
                mode=self.download_mode_var.get(),
                quality_label=self.quality_var.get(),
                video_format_id=video_format_id,
                audio_format_id=audio_format_id,
                conflict_option=conflict,
                subtitles_enabled=self.subtitles_enabled_var.get(),
                subtitles_auto=self.subtitles_auto_var.get(),
                subtitles_lang=self.subtitles_lang_var.get(),
                subtitles_embed=self.subtitles_embed_var.get(),
                subtitles_separate=self.subtitles_separate_var.get(),
                chapters_embed=self.chapters_embed_var.get(),
                chapters_export=self.chapters_export_var.get(),
                naming_template=self.naming_template_var.get(),
                audio_format=self.audio_format_var.get(),
                audio_quality=self.audio_quality_var.get(),
                uploader=uploader_name,
                is_playlist=False,
            )
            self.status_var.set("Status: Added task to queue")

    def _on_queue_changed(self) -> None:
        self.root.after(0, self._render_queue)
        
        active = self.queue.active_task
        if active:
            self.root.after(0, self._set_ui_state_downloading)
        else:
            self.root.after(0, self._set_ui_state_idle)

    def _on_task_progress(self, task: DownloadTask, data: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._update_dashboard(task, data))

    def _on_queue_complete(self, summary: dict[str, Any]) -> None:
        self.root.after(0, lambda: self._show_queue_summary(summary))

    def _update_dashboard(self, task: DownloadTask, data: dict[str, Any]) -> None:
        title = task.title
        self.current_file_label.configure(text=f"Downloading: {title}")

        progress_val = task.progress / 100.0
        self.progress_bar.set(progress_val)
        self.video_progress_lbl.configure(text=f"Current Video: {task.progress:.1f}%")

        info_dict = data.get("info_dict", {})
        playlist_index = info_dict.get("playlist_index")
        playlist_count = info_dict.get("playlist_count")

        if playlist_index is not None and playlist_count is not None:
            if not self.playlist_progress_bar.winfo_manager():
                self.playlist_progress_lbl.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 2))
                self.playlist_progress_bar.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
            
            overall_pct = ((playlist_index - 1) + (task.progress / 100.0)) / playlist_count * 100.0
            self.playlist_progress_bar.set(overall_pct / 100.0)
            self.playlist_progress_lbl.configure(
                text=f"Video {playlist_index} of {playlist_count} • Overall Progress: {overall_pct:.1f}%"
            )
            self.status_var.set(f"Downloading... (item {playlist_index} of {playlist_count})")
        else:
            self.playlist_progress_lbl.grid_forget()
            self.playlist_progress_bar.grid_forget()
            self.status_var.set("Downloading...")

        status_text = "Downloading..."
        if "FFmpegMerger" in str(data.get("postprocessor", "")):
            status_text = "Merging Video + Audio..."
        elif "FFmpegExtractAudio" in str(data.get("postprocessor", "")):
            status_text = "Converting Audio..."
        elif "FFmpegEmbedSubtitle" in str(data.get("postprocessor", "")):
            status_text = "Embedding Subtitles..."
        
        self.stat_status.configure(text=f"Status: {status_text}")
        
        speed = task.speed
        if speed:
            speed_mb = speed / 1024 / 1024
            self.stat_speed.configure(text=f"Speed: {speed_mb:.1f} MB/s")
        else:
            self.stat_speed.configure(text="Speed: N/A")

        eta = task.eta
        if eta:
            self.stat_eta.configure(text=f"ETA: {int(eta)}s")
        else:
            self.stat_eta.configure(text="ETA: N/A")

        total_size_str = format_size(task.total_size)
        downloaded_size_str = format_size(task.downloaded_size)
        self.stat_size.configure(text=f"Size: {downloaded_size_str} / {total_size_str}")

        self._render_queue()

    def _render_queue(self) -> None:
        for widget in self.queue_frame.winfo_children():
            widget.destroy()

        with self.queue._lock:
            tasks = list(self.queue.tasks)

        if not tasks:
            empty_lbl = ctk.CTkLabel(self.queue_frame, text="No items queued. Add URLs above.", font=("Segoe UI", 10), text_color="#94a3b8")
            empty_lbl.pack(pady=10)
            return

        for idx, task in enumerate(tasks, 1):
            row_frame = ctk.CTkFrame(self.queue_frame, fg_color="#1f2937")
            row_frame.pack(fill="x", padx=4, pady=4)
            
            title_text = f"{idx}. {task.title}"
            title_lbl = ctk.CTkLabel(row_frame, text=title_text, font=("Segoe UI", 11), text_color="#f8fafc", anchor="w", wraplength=450, justify="left")
            title_lbl.pack(side="left", padx=8, pady=4, fill="x", expand=True)

            status_colors = {
                "Pending": "#eab308",
                "Downloading": "#3b82f6",
                "Completed": "#22c55e",
                "Failed": "#ef4444",
                "Cancelled": "#94a3b8"
            }
            color = status_colors.get(task.status, "#f8fafc")
            
            disp_status = task.status
            if task.status == "Downloading":
                disp_status = f"Downloading ({task.progress:.0f}%)"
                
            status_lbl = ctk.CTkLabel(row_frame, text=disp_status, font=("Segoe UI", 10, "bold"), text_color=color, width=130)
            status_lbl.pack(side="left", padx=8)

            if task.status in ["Downloading", "Pending"]:
                btn_cancel = ctk.CTkButton(
                    row_frame, 
                    text="Cancel", 
                    font=("Segoe UI", 9, "bold"), 
                    fg_color="#ef4444", 
                    hover_color="#dc2626", 
                    text_color="#ffffff", 
                    width=60, 
                    height=20,
                    command=lambda tid=task.task_id: self.queue.cancel_task(tid)
                )
                btn_cancel.pack(side="right", padx=8)
            elif task.status in ["Failed", "Cancelled"]:
                btn_retry = ctk.CTkButton(
                    row_frame, 
                    text="Retry", 
                    font=("Segoe UI", 9, "bold"), 
                    fg_color="#22c55e", 
                    hover_color="#16a34a", 
                    text_color="#ffffff", 
                    width=60, 
                    height=20,
                    command=lambda tid=task.task_id: self.queue.retry_task(tid)
                )
                btn_retry.pack(side="right", padx=8)

                btn_remove = ctk.CTkButton(
                    row_frame, 
                    text="Remove", 
                    font=("Segoe UI", 9, "bold"), 
                    fg_color="#374151", 
                    hover_color="#4b5563", 
                    text_color="#cbd5e1", 
                    width=60, 
                    height=20,
                    command=lambda tid=task.task_id: self.queue.remove_task(tid)
                )
                btn_remove.pack(side="right", padx=(0, 4))

    def _show_queue_summary(self, summary: dict[str, Any]) -> None:
        self._set_ui_state_idle()
        
        self.progress_bar.set(0.0)
        self.video_progress_lbl.configure(text="Current Video: 0%")
        self.playlist_progress_lbl.grid_forget()
        self.playlist_progress_bar.grid_forget()
        self.current_file_label.configure(text="No active download")
        
        self.stat_status.configure(text="Status: Finished")
        self.stat_speed.configure(text="Speed: N/A")
        self.stat_eta.configure(text="ETA: N/A")
        self.stat_size.configure(text="Downloaded: N/A")
        
        self.status_var.set("Finished")

        for widget in self.preview_panel.winfo_children():
            widget.destroy()

        self.preview_placeholder = ctk.CTkLabel(self.preview_panel, text="", font=("Segoe UI", 11), text_color="#cbd5e1")
        self.preview_placeholder.grid(row=0, column=0, columnspan=2, sticky="nw", padx=16, pady=16)

        avg_speed_str = "N/A"
        if summary.get("avg_speed"):
            avg_speed_mb = summary["avg_speed"] / 1024 / 1024
            avg_speed_str = f"{avg_speed_mb:.1f} MB/s"

        summary_text = (
            f"🎉 Download Summary\n\n"
            f"• Downloaded Files: {summary['completed']} files\n"
            f"• Failed: {summary['failed']} files\n"
            f"• Total Transferred Size: {format_size(summary['total_size'])}\n"
            f"• Average Speed: {avg_speed_str}\n"
            f"• Elapsed Time: {summary['duration']:.1f}s\n"
        )
        self.preview_placeholder.configure(text=summary_text, justify="left")

        # Dialog Complete Popup window
        output_dir = self.output_dir_var.get()
        title_summary = f"{summary['completed']} items downloaded successfully"
        DownloadCompleteDialog(self.root, title_summary, output_dir, summary["duration"])

        # Auto open folder option
        if self.settings.get("auto_open_folder"):
            import os
            try:
                os.startfile(output_dir)
            except Exception:
                pass

    # =========================================================================
    # TAB 1 LAYOUT HELPER METHODS: REDRAWING FOR PLAYLISTS VS VIDEO
    # =========================================================================
    def _render_playlist_preview(self, metadata: MediaMetadata, thumbnail_img: Image.Image | None) -> None:
        self.preview_panel.grid_columnconfigure(0, weight=1)
        self.preview_panel.grid_columnconfigure(1, weight=2)

        # Left Info Frame
        left_frame = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        left_frame.grid_columnconfigure(0, weight=1)

        thumb_lbl = ctk.CTkLabel(left_frame, text="")
        if thumbnail_img:
            thumbnail_img.thumbnail((220, 130), Image.Resampling.LANCZOS)
            ctk_image = ctk.CTkImage(light_image=thumbnail_img, dark_image=thumbnail_img, size=thumbnail_img.size)
            thumb_lbl.configure(image=ctk_image)
            thumb_lbl.image = ctk_image
        else:
            thumb_lbl.configure(text="No Playlist Thumbnail")
        thumb_lbl.grid(row=0, column=0, sticky="nw", pady=(0, 10))

        title_lbl = ctk.CTkLabel(left_frame, text=metadata.title, font=("Segoe UI", 13, "bold"), text_color="#f8fafc", anchor="w", wraplength=220, justify="left")
        title_lbl.grid(row=1, column=0, sticky="w", pady=2)

        owner_lbl = ctk.CTkLabel(left_frame, text=f"By: {metadata.uploader}", font=("Segoe UI", 11), text_color="#94a3b8", anchor="w", wraplength=220, justify="left")
        owner_lbl.grid(row=2, column=0, sticky="w", pady=2)

        count_lbl = ctk.CTkLabel(left_frame, text=f"Total: {metadata.total_videos} videos", font=("Segoe UI", 11), text_color="#94a3b8", anchor="w")
        count_lbl.grid(row=3, column=0, sticky="w", pady=2)

        # Sum Durations & Estimate sizes
        total_duration_sec = sum(item.duration_sec for item in self.playlist_items if item.duration_sec is not None)
        is_video = self.download_mode_var.get() == "Video (MP4)"
        factor = 12.0 if is_video else 1.2
        est_size_bytes = (total_duration_sec / 60.0) * factor * 1024 * 1024
        est_lbl = ctk.CTkLabel(left_frame, text=f"Est. Size: {format_size(est_size_bytes)}", font=("Segoe UI", 11), text_color="#94a3b8", anchor="w")
        est_lbl.grid(row=4, column=0, sticky="w", pady=(2, 10))

        scope_lbl = ctk.CTkLabel(left_frame, text="Download Scope", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1", anchor="w")
        scope_lbl.grid(row=5, column=0, sticky="w", pady=(4, 2))
        self.scope_combo = ctk.CTkComboBox(left_frame, variable=self.playlist_scope_var, values=["Selected Only", "Entire Playlist"], font=("Segoe UI", 10), height=25, state="readonly", fg_color="#111827", border_color="#374151")
        self.scope_combo.grid(row=6, column=0, sticky="ew", pady=(0, 8))

        conflict_lbl = ctk.CTkLabel(left_frame, text="Existing Files", font=("Segoe UI", 10, "bold"), text_color="#cbd5e1", anchor="w")
        conflict_lbl.grid(row=7, column=0, sticky="w", pady=(4, 2))
        self.conflict_combo = ctk.CTkComboBox(left_frame, variable=self.playlist_conflict_var, values=["Rename", "Skip", "Overwrite"], font=("Segoe UI", 10), height=25, state="readonly", fg_color="#111827", border_color="#374151")
        self.conflict_combo.grid(row=8, column=0, sticky="ew", pady=(0, 8))

        # Right Video List Frame
        right_frame = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(2, weight=1)

        # Filters Box Panel
        filter_box = ctk.CTkFrame(right_frame, fg_color="#111827", corner_radius=6, height=75)
        filter_box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_box.grid_columnconfigure((0, 1, 2), weight=1)

        lbl_q = ctk.CTkLabel(filter_box, text="Title Contains", font=("Segoe UI", 9, "bold"), text_color="#94a3b8")
        lbl_q.grid(row=0, column=0, sticky="w", padx=8, pady=(4, 0))
        self.filter_title_entry = ctk.CTkEntry(filter_box, placeholder_text="Search...", font=("Segoe UI", 10), height=20, fg_color="#0f172a", border_color="#374151")
        self.filter_title_entry.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        self.filter_title_entry.bind("<KeyRelease>", self._apply_playlist_filters)

        lbl_dur = ctk.CTkLabel(filter_box, text="Max Duration (min)", font=("Segoe UI", 9, "bold"), text_color="#94a3b8")
        lbl_dur.grid(row=0, column=1, sticky="w", padx=8, pady=(4, 0))
        self.filter_dur_max_entry = ctk.CTkEntry(filter_box, placeholder_text="e.g. 10", font=("Segoe UI", 10), height=20, fg_color="#0f172a", border_color="#374151")
        self.filter_dur_max_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=(0, 6))
        self.filter_dur_max_entry.bind("<KeyRelease>", self._apply_playlist_filters)

        lbl_idx = ctk.CTkLabel(filter_box, text="Index Range (Start - End)", font=("Segoe UI", 9, "bold"), text_color="#94a3b8")
        lbl_idx.grid(row=0, column=2, sticky="w", padx=8, pady=(4, 0))
        range_frame = ctk.CTkFrame(filter_box, fg_color="transparent")
        range_frame.grid(row=1, column=2, sticky="ew", padx=8, pady=(0, 6))
        range_frame.grid_columnconfigure((0, 1), weight=1)
        
        self.filter_idx_start_entry = ctk.CTkEntry(range_frame, placeholder_text="1", font=("Segoe UI", 10), height=20, fg_color="#0f172a", border_color="#374151")
        self.filter_idx_start_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.filter_idx_start_entry.bind("<KeyRelease>", self._apply_playlist_filters)
        
        self.filter_idx_end_entry = ctk.CTkEntry(range_frame, placeholder_text="50", font=("Segoe UI", 10), height=20, fg_color="#0f172a", border_color="#374151")
        self.filter_idx_end_entry.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.filter_idx_end_entry.bind("<KeyRelease>", self._apply_playlist_filters)

        # Bulk Selection Toolbar
        select_bar = ctk.CTkFrame(right_frame, fg_color="transparent")
        select_bar.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        
        btn_all = ctk.CTkButton(select_bar, text="Select All", font=("Segoe UI", 10, "bold"), width=80, height=22, fg_color="#1f2937", hover_color="#374151", text_color="#e5e7eb", command=self._bulk_select_all)
        btn_all.pack(side="left", padx=(0, 8))
        
        btn_none = ctk.CTkButton(select_bar, text="Deselect All", font=("Segoe UI", 10, "bold"), width=80, height=22, fg_color="#1f2937", hover_color="#374151", text_color="#e5e7eb", command=self._bulk_deselect_all)
        btn_none.pack(side="left", padx=8)

        btn_invert = ctk.CTkButton(select_bar, text="Invert", font=("Segoe UI", 10, "bold"), width=70, height=22, fg_color="#1f2937", hover_color="#374151", text_color="#e5e7eb", command=self._bulk_invert)
        btn_invert.pack(side="left", padx=8)

        # Scrollable Playlist Video List
        self.playlist_scroll_frame = ctk.CTkScrollableFrame(right_frame, height=230, fg_color="#111827")
        self.playlist_scroll_frame.grid(row=2, column=0, sticky="nsew")

        # Initial Render
        self._render_playlist_video_list()

    def _render_playlist_video_list(self) -> None:
        for widget in self.playlist_scroll_frame.winfo_children():
            widget.destroy()

        if not self.filtered_playlist_items:
            empty_lbl = ctk.CTkLabel(self.playlist_scroll_frame, text="No playlist items match filters.", font=("Segoe UI", 11), text_color="#94a3b8")
            empty_lbl.pack(pady=20)
            return

        for item in self.filtered_playlist_items:
            row_frame = ctk.CTkFrame(self.playlist_scroll_frame, fg_color="#1f2937")
            row_frame.pack(fill="x", padx=4, pady=4)
            
            chk_var = ctk.BooleanVar(value=item.is_selected)
            chk = ctk.CTkCheckBox(row_frame, text="", variable=chk_var, width=20, height=20, command=lambda var=chk_var, it=item: self._toggle_item_selection(it, var))
            chk.pack(side="left", padx=8)

            idx_lbl = ctk.CTkLabel(row_frame, text=f"#{item.index:02d}", font=("Segoe UI", 10, "bold"), text_color="#94a3b8", width=30)
            idx_lbl.pack(side="left", padx=(0, 4))

            title_lbl = ctk.CTkLabel(row_frame, text=item.title, font=("Segoe UI", 11), text_color="#f8fafc", anchor="w", justify="left", wraplength=380)
            title_lbl.pack(side="left", fill="x", expand=True, padx=4, pady=2)

            dur_lbl = ctk.CTkLabel(row_frame, text=item.duration_str, font=("Segoe UI", 10), text_color="#cbd5e1", width=50)
            dur_lbl.pack(side="right", padx=8)

            res_lbl = ctk.CTkLabel(row_frame, text=item.resolution or "Best", font=("Segoe UI", 9, "bold"), text_color="#38bdf8", width=45)
            res_lbl.pack(side="right", padx=4)

    def _toggle_item_selection(self, item: PlaylistItem, var: ctk.BooleanVar) -> None:
        item.is_selected = var.get()

    def _bulk_select_all(self) -> None:
        PlaylistManager.select_all(self.filtered_playlist_items)
        self._render_playlist_video_list()

    def _bulk_deselect_all(self) -> None:
        PlaylistManager.deselect_all(self.filtered_playlist_items)
        self._render_playlist_video_list()

    def _bulk_invert(self) -> None:
        PlaylistManager.invert_selection(self.filtered_playlist_items)
        self._render_playlist_video_list()

    def _apply_playlist_filters(self, event: Any = None) -> None:
        title_q = self.filter_title_entry.get().strip() or None
        
        dur_max = None
        if self.filter_dur_max_entry.get().strip():
            try:
                dur_max = float(self.filter_dur_max_entry.get().strip()) * 60.0
            except ValueError:
                pass
                
        idx_start = None
        if self.filter_idx_start_entry.get().strip():
            try:
                idx_start = int(self.filter_idx_start_entry.get().strip())
            except ValueError:
                pass
        idx_end = None
        if self.filter_idx_end_entry.get().strip():
            try:
                idx_end = int(self.filter_idx_end_entry.get().strip())
            except ValueError:
                pass

        self.filtered_playlist_items = PlaylistManager.get_filtered_items(
            self.playlist_items,
            title_contains=title_q,
            max_duration=dur_max,
            index_start=idx_start,
            index_end=idx_end,
        )
        self._render_playlist_video_list()

    # =========================================================================
    # CLOSING / SAVING WINDOW SETTINGS
    # =========================================================================
    def _on_close(self) -> None:
        # Save geometry sizes and window positions
        self.settings.set("last_window_size", f"{self.root.winfo_width()}x{self.root.winfo_height()}")
        self.settings.set("last_window_position", f"+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.root.destroy()

    def _analyze_action(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Status: please enter a YouTube URL first")
            return

        self.status_var.set("Status: Analyzing...")
        self.analyze_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.quality_combo.configure(state="disabled")
        
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.stat_status.configure(text="Status: Fetching Information...")
        
        self.root.update_idletasks()

        threading.Thread(
            target=self._run_analysis,
            args=(url,),
            daemon=True
        ).start()

    def _run_analysis(self, url: str) -> None:
        try:
            metadata = analyze_url(url)
            
            video_options = []
            audio_option = None
            if not metadata.is_playlist:
                fm = FormatManager(metadata.info_dict)
                video_options = fm.video_options
                audio_option = fm.audio_option
                if not video_options and not audio_option:
                    raise AnalysisError("No downloadable formats available for this video.")

            thumbnail_img = None
            if metadata.thumbnail_url:
                try:
                    response = requests.get(metadata.thumbnail_url, timeout=10)
                    response.raise_for_status()
                    thumbnail_img = Image.open(BytesIO(response.content))
                except Exception as thumb_err:
                    logger.warning(f"Failed to download thumbnail: {thumb_err}")

            self.root.after(0, lambda: self._on_analysis_success(metadata, thumbnail_img, video_options, audio_option))
        except Exception as exc:
            logger.exception("Analysis failed in background thread")
            self.root.after(0, lambda: self._on_analysis_failure(exc))

    def _on_analysis_success(
        self,
        metadata: MediaMetadata,
        thumbnail_img: Image.Image | None,
        video_options: list[DownloadOption],
        audio_option: DownloadOption | None
    ) -> None:
        self.metadata = metadata
        self.video_options = video_options
        self.audio_option = audio_option

        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0.0)
        self.stat_status.configure(text="Status: Ready")
        self.status_var.set("Status: Analysis complete")
        
        self.analyze_button.configure(state="normal")
        self.download_button.configure(state="normal")

        # Clean preview panel
        for widget in self.preview_panel.winfo_children():
            widget.destroy()

        if metadata.is_playlist:
            # Handle playlist entries parsing
            self.playlist_metadata = PlaylistManager.parse_playlist(metadata.info_dict)
            self.playlist_items = self.playlist_metadata.items
            self.filtered_playlist_items = list(self.playlist_items)
            self._render_playlist_preview(metadata, thumbnail_img)
            self.playlist_scope_var.set("Selected Only")
            
            # Disable quality resolution combos since we process each playlist item separately
            self.quality_combo.configure(values=["Best available"])
            self.quality_combo.configure(state="disabled")
            self.quality_var.set("Best available")
        else:
            self.playlist_metadata = None
            self.playlist_items.clear()
            self.filtered_playlist_items.clear()
            
            # Single Video Preview
            self.preview_panel.grid_columnconfigure(0, weight=1)
            self.preview_panel.grid_columnconfigure(1, weight=1)
            
            thumb_lbl = ctk.CTkLabel(self.preview_panel, text="")
            if thumbnail_img:
                thumbnail_img.thumbnail((260, 160), Image.Resampling.LANCZOS)
                ctk_image = ctk.CTkImage(light_image=thumbnail_img, dark_image=thumbnail_img, size=thumbnail_img.size)
                thumb_lbl.configure(image=ctk_image)
                thumb_lbl.image = ctk_image
            else:
                thumb_lbl.configure(text="No Thumbnail")
            thumb_lbl.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)

            info_text = (
                f"Title: {metadata.title}\n"
                f"Channel: {metadata.uploader}\n"
                f"Duration: {metadata.duration_str}\n"
                f"Views: {metadata.view_count:, if metadata.view_count else 'N/A'}\n"
                f"Upload Date: {metadata.upload_date or 'N/A'}\n"
            )
            info_lbl = ctk.CTkLabel(self.preview_panel, text=info_text, font=("Segoe UI", 11), text_color="#cbd5e1", justify="left", anchor="w", wraplength=300)
            info_lbl.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)

            # Update quality resolutions dropdown list
            self._on_mode_change(self.download_mode_var.get())

        self._update_format_details()

    def _on_analysis_failure(self, error: Exception) -> None:
        self.metadata = None
        self.video_options.clear()
        self.audio_option = None
        
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0.0)
        self.stat_status.configure(text="Status: Analysis Failed")
        self.status_var.set("Status: Analysis failed")
        
        self.analyze_button.configure(state="normal")
        self.download_button.configure(state="disabled")

        for widget in self.preview_panel.winfo_children():
            widget.destroy()
            
        self.preview_placeholder = ctk.CTkLabel(self.preview_panel, text=f"Analysis Failed:\n{error}", font=("Segoe UI", 11), text_color="#ef4444")
        self.preview_placeholder.grid(row=0, column=0, columnspan=2, sticky="nw", padx=16, pady=16)

    def _update_format_details(self) -> None:
        # Extra details mapping
        pass

    def _set_ui_state_downloading(self) -> None:
        self.analyze_button.configure(state="disabled")
        self.url_entry.configure(state="disabled")
        self.mode_combo.configure(state="disabled")
        self.quality_combo.configure(state="disabled")

    def _set_ui_state_idle(self) -> None:
        self.analyze_button.configure(state="normal")
        self.url_entry.configure(state="normal")
        self.mode_combo.configure(state="normal")
        if self.metadata and not self.metadata.is_playlist and self.download_mode_var.get() == "Video (MP4)":
            self.quality_combo.configure(state="normal")
