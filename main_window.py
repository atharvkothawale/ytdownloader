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
    """Main application window for YT Downloader Pro using CustomTkinter."""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("YT Downloader Pro")
        self.root.geometry("1180x820")
        self.root.minsize(1050, 750)
        self.root.configure(fg_color="#0f172a")

        self.download_mode_var = ctk.StringVar(value="Video (MP4)")
        self.output_dir_var = ctk.StringVar(value=str(self._default_output_dir()))
        self.status_var = ctk.StringVar(value="Status: Ready")
        self.quality_var = ctk.StringVar(value="Best available")
        
        # Format detection options state
        self.metadata: MediaMetadata | None = None
        self.video_options: list[DownloadOption] = []
        self.audio_option: DownloadOption | None = None
        
        # Download Queue Manager
        self.queue = DownloadQueue()
        self.queue.on_queue_changed = self._on_queue_changed
        self.queue.on_task_progress = self._on_task_progress
        self.queue.on_queue_complete = self._on_queue_complete

        self._build_ui()

    def _default_output_dir(self) -> Path:
        return Path(__file__).resolve().parent / "downloads"

    def _build_ui(self) -> None:
        # 2 columns: Sidebar (0) and Content (1)
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=0)

        # ----------------- SIDEBAR -----------------
        sidebar = ctk.CTkFrame(self.root, fg_color="#111827", corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(6, weight=1)  # Spacer row

        # Sidebar Title
        title_lbl = ctk.CTkLabel(sidebar, text="YT Downloader Pro", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        title_lbl.grid(row=0, column=0, sticky="w", padx=24, pady=(24, 4))
        
        subtitle_lbl = ctk.CTkLabel(sidebar, text="Professional Windows downloader", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        subtitle_lbl.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 24))

        # Nav Buttons
        self._create_nav_button(sidebar, "Download", 2)
        self._create_nav_button(sidebar, "Analyze", 3)
        self._create_nav_button(sidebar, "History", 4)
        self._create_nav_button(sidebar, "Settings", 5)

        # Status inside sidebar
        sidebar_status = ctk.CTkLabel(sidebar, text="Ready", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        sidebar_status.grid(row=7, column=0, sticky="sw", padx=24, pady=24)

        # ----------------- CONTENT AREA -----------------
        content = ctk.CTkFrame(self.root, fg_color="#0f172a", corner_radius=0)
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=0)
        content.grid_rowconfigure(1, weight=1)

        # Header Card
        header = ctk.CTkFrame(content, fg_color="#111827", corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 9))
        header.grid_columnconfigure(0, weight=1)
        
        header_title = ctk.CTkLabel(header, text="Download Center", font=("Segoe UI", 22, "bold"), text_color="#f8fafc", anchor="w")
        header_title.grid(row=0, column=0, sticky="w", padx=24, pady=(20, 4))
        
        header_subtitle = ctk.CTkLabel(header, text="Paste a YouTube URL and choose your preferred download options.", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        header_subtitle.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 20))

        # Main Card (where inputs, dashboard, and queue reside)
        self.main_card = ctk.CTkFrame(content, fg_color="#111827", corner_radius=8)
        self.main_card.grid(row=1, column=0, sticky="nsew", padx=28, pady=(9, 20))
        self.main_card.grid_columnconfigure(0, weight=1)
        self.main_card.grid_rowconfigure(4, weight=1)  # Preview panel is resizable
        self.main_card.grid_rowconfigure(6, weight=1)  # Queue frame is resizable

        # URL Input
        url_lbl = ctk.CTkLabel(self.main_card, text="Enter URL", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        url_lbl.grid(row=0, column=0, sticky="w", padx=24, pady=(24, 4))
        
        self.url_entry = ctk.CTkEntry(self.main_card, font=("Segoe UI", 12), fg_color="#0f172a", border_color="#374151", text_color="#f8fafc", height=35)
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 16))

        # Options Panel (Type, Quality, Output Folder)
        options_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        options_panel.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 16))
        options_panel.grid_columnconfigure(1, weight=1)

        # Download Type
        type_lbl = ctk.CTkLabel(options_panel, text="Download type", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        type_lbl.grid(row=0, column=0, sticky="w", padx=(16, 12), pady=(16, 6))
        self.mode_combo = ctk.CTkComboBox(
            options_panel, 
            variable=self.download_mode_var, 
            values=["Video (MP4)", "Audio (MP3)"], 
            state="readonly", 
            fg_color="#111827", 
            border_color="#374151", 
            button_color="#111827", 
            button_hover_color="#1f2937",
            command=self._on_mode_change
        )
        self.mode_combo.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(16, 6))

        # Quality
        self.quality_lbl = ctk.CTkLabel(options_panel, text="Quality", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        self.quality_lbl.grid(row=1, column=0, sticky="w", padx=(16, 12), pady=6)
        
        self.quality_combo = ctk.CTkComboBox(
            options_panel, 
            variable=self.quality_var, 
            values=["Best available"], 
            state="disabled",  # disabled initially
            fg_color="#111827", 
            border_color="#374151", 
            button_color="#111827", 
            button_hover_color="#1f2937",
            command=self._on_quality_change
        )
        self.quality_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=6)

        # Best Audio static label placeholder (hidden initially)
        self.best_audio_label = ctk.CTkLabel(options_panel, text="Best Audio", font=("Segoe UI", 11, "bold"), text_color="#f8fafc", anchor="w")

        # Output Folder
        folder_lbl = ctk.CTkLabel(options_panel, text="Output folder", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        folder_lbl.grid(row=2, column=0, sticky="w", padx=(16, 12), pady=(6, 16))
        folder_entry = ctk.CTkEntry(options_panel, textvariable=self.output_dir_var, fg_color="#111827", border_color="#374151", text_color="#f8fafc", height=28)
        folder_entry.grid(row=2, column=1, sticky="ew", pady=(6, 16))
        self.folder_button = ctk.CTkButton(options_panel, text="Browse", font=("Segoe UI", 10, "bold"), fg_color="#111827", hover_color="#374151", text_color="#e5e7eb", border_width=1, border_color="#374151", width=80, height=28, command=self._choose_folder)
        self.folder_button.grid(row=2, column=2, sticky="w", padx=(10, 16), pady=(6, 16))

        # Action Row (Buttons)
        action_row = ctk.CTkFrame(self.main_card, fg_color="transparent")
        action_row.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 16))
        
        self.analyze_button = ctk.CTkButton(action_row, text="Analyze", font=("Segoe UI", 11, "bold"), fg_color="#1f2937", hover_color="#374151", text_color="#e5e7eb", border_width=1, border_color="#374151", width=120, height=35, command=self._analyze_action)
        self.analyze_button.pack(side="left", padx=(0, 10))

        self.download_button = ctk.CTkButton(action_row, text="Add to Queue", font=("Segoe UI", 11, "bold"), fg_color="#2563eb", hover_color="#1d4ed8", text_color="#ffffff", width=120, height=35, state="disabled", command=self._download_action)
        self.download_button.pack(side="left", padx=(0, 10))

        # Preview Panel
        self.preview_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        self.preview_panel.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 16))
        self.preview_panel.grid_columnconfigure(0, weight=0)  # Col 0: Thumbnail
        self.preview_panel.grid_columnconfigure(1, weight=1)  # Col 1: Details
        self.preview_panel.grid_rowconfigure(0, weight=1)

        # Placeholder inside Preview
        self.preview_placeholder = ctk.CTkLabel(
            self.preview_panel,
            text="No media selected yet. The controls above are ready for analysis and download configuration.",
            font=("Segoe UI", 11),
            text_color="#94a3b8",
            wraplength=600,
            justify="left",
            anchor="w"
        )
        self.preview_placeholder.grid(row=0, column=0, columnspan=2, sticky="nw", padx=16, pady=16)

        # Hidden Thumbnail and Details Frame
        self.preview_image_label = ctk.CTkLabel(self.preview_panel, text="")
        self.details_frame = ctk.CTkFrame(self.preview_panel, fg_color="transparent")
        self.metadata_subframe = ctk.CTkFrame(self.details_frame, fg_color="transparent")
        self.format_subframe = ctk.CTkFrame(self.details_frame, fg_color="transparent")

        # Progress Dashboard Panel
        self.progress_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        self.progress_panel.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 16))
        self.progress_panel.grid_columnconfigure(0, weight=1)

        # Filename Header
        self.current_file_label = ctk.CTkLabel(self.progress_panel, text="No active download", font=("Segoe UI", 11, "bold"), text_color="#f8fafc", anchor="w")
        self.current_file_label.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))

        # Twin Progress Bar 1: Current Video Progress
        self.video_progress_lbl = ctk.CTkLabel(self.progress_panel, text="Current Video: 0%", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        self.video_progress_lbl.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 2))
        self.progress_bar = ctk.CTkProgressBar(self.progress_panel, progress_color="#3b82f6", fg_color="#111827", height=8)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.progress_bar.set(0.0)

        # Twin Progress Bar 2: Overall Playlist Progress (hidden initially)
        self.playlist_progress_lbl = ctk.CTkLabel(self.progress_panel, text="Overall Progress: 0%", font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        self.playlist_progress_bar = ctk.CTkProgressBar(self.progress_panel, progress_color="#22c55e", fg_color="#111827", height=8)

        # Stats Grid Frame
        self.stats_frame = ctk.CTkFrame(self.progress_panel, fg_color="transparent")
        self.stats_frame.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 12))
        self.stats_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_status = ctk.CTkLabel(self.stats_frame, text="Status: Ready", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_status.grid(row=0, column=0, sticky="w")

        self.stat_speed = ctk.CTkLabel(self.stats_frame, text="Speed: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_speed.grid(row=0, column=1, sticky="w")

        self.stat_eta = ctk.CTkLabel(self.stats_frame, text="ETA: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_eta.grid(row=0, column=2, sticky="w")

        self.stat_size = ctk.CTkLabel(self.stats_frame, text="Downloaded: N/A", font=("Segoe UI", 10), text_color="#94a3b8", anchor="w")
        self.stat_size.grid(row=0, column=3, sticky="w")

        # Scrollable Download Queue Panel
        self.queue_frame = ctk.CTkScrollableFrame(self.main_card, label_text="Download Queue", height=150, fg_color="#1f2937")
        self.queue_frame.grid(row=6, column=0, sticky="ew", padx=24, pady=(0, 24))
        self._render_queue()

        # Bottom Status Bar
        status_bar = ctk.CTkFrame(self.root, fg_color="#111827", corner_radius=0, height=35)
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        status_bar.grid_columnconfigure(0, weight=1)
        
        bottom_status = ctk.CTkLabel(status_bar, textvariable=self.status_var, font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        bottom_status.grid(row=0, column=0, sticky="w", padx=24, pady=6)

    def _create_nav_button(self, parent: ctk.CTkFrame, text: str, row: int) -> None:
        button = ctk.CTkButton(
            parent,
            text=text,
            fg_color="#1f2937",
            hover_color="#374151",
            text_color="#e5e7eb",
            font=("Segoe UI", 10, "bold")
        )
        button.grid(row=row, column=0, sticky="ew", padx=24, pady=(0, 10))

    def _choose_folder(self) -> None:
        from tkinter import filedialog
        folder = filedialog.askdirectory(title="Choose download folder")
        if folder:
            self.output_dir_var.set(folder)

    def _set_ui_state_downloading(self) -> None:
        """Locks settings panel while downloads run. Spaced sequentially inside queue."""
        self.url_entry.configure(state="disabled")
        self.mode_combo.configure(state="disabled")
        self.quality_combo.configure(state="disabled")
        self.folder_button.configure(state="disabled")
        self.analyze_button.configure(state="disabled")
        self.download_button.configure(state="disabled")

    def _set_ui_state_idle(self) -> None:
        """Unlocks configuration inputs when queue processes finish or idle."""
        self.url_entry.configure(state="normal")
        self.mode_combo.configure(state="normal")
        self.folder_button.configure(state="normal")
        self.analyze_button.configure(state="normal")
        
        is_analyzed = self.metadata is not None
        if is_analyzed:
            self.download_button.configure(state="normal")
            if not self.metadata.is_playlist and self.download_mode_var.get() == "Video (MP4)":
                self.quality_combo.configure(state="normal")
        else:
            self.download_button.configure(state="disabled")
            self.quality_combo.configure(state="disabled")

    def _analyze_action(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Status: please enter a YouTube URL first")
            return

        self.status_var.set("Status: Analyzing...")
        self.analyze_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.quality_combo.configure(state="disabled")
        
        # Start loading animation
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.stat_status.configure(text="Status: Fetching Information...")
        
        self.root.update_idletasks()

        # Run analysis in a background thread to prevent UI freezing
        threading.Thread(
            target=self._run_analysis,
            args=(url,),
            daemon=True
        ).start()

    def _run_analysis(self, url: str) -> None:
        try:
            metadata = analyze_url(url)
            
            # Fetch formats using FormatManager (only if it's a single video)
            video_options = []
            audio_option = None
            if not metadata.is_playlist:
                fm = FormatManager(metadata.info_dict)
                video_options = fm.video_options
                audio_option = fm.audio_option
                if not video_options and not audio_option:
                    raise AnalysisError("No downloadable formats available for this video.")

            # Fetch thumbnail in background
            thumbnail_img = None
            if metadata.thumbnail_url:
                try:
                    response = requests.get(metadata.thumbnail_url, timeout=10)
                    response.raise_for_status()
                    thumbnail_img = Image.open(BytesIO(response.content))
                except Exception as thumb_err:
                    logger.warning(f"Failed to download thumbnail: {thumb_err}")

            # Route back to main thread for UI updates
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
        # Reset loading animation
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0.0)
        self.stat_status.configure(text="Status: Ready")
        
        self.metadata = metadata
        self.video_options = video_options
        self.audio_option = audio_option
        
        # Restore controls state
        self._set_ui_state_idle()

        media_type = "playlist" if metadata.is_playlist else "video"
        self.status_var.set(f"Status: Analyzed {media_type} successfully")

        # Hide placeholder
        self.preview_placeholder.grid_forget()

        # Display proportional thumbnail
        if thumbnail_img:
            thumbnail_img.thumbnail((280, 160), Image.Resampling.LANCZOS)
            ctk_image = ctk.CTkImage(light_image=thumbnail_img, dark_image=thumbnail_img, size=thumbnail_img.size)
            self.preview_image_label.configure(image=ctk_image, text="")
            self.preview_image_label.image = ctk_image  # Keep reference
            self.preview_image_label.grid(row=0, column=0, sticky="nw", padx=16, pady=16)
        else:
            self.preview_image_label.configure(image=None, text="No Thumbnail")
            self.preview_image_label.grid(row=0, column=0, sticky="nw", padx=16, pady=16)

        # Clear previous details
        for widget in self.details_frame.winfo_children():
            widget.destroy()

        self.details_frame.grid(row=0, column=1, sticky="nsew", padx=(0, 16), pady=16)

        # Create structured subframes for metadata and format details
        self.metadata_subframe = ctk.CTkFrame(self.details_frame, fg_color="transparent")
        self.metadata_subframe.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.format_subframe = ctk.CTkFrame(self.details_frame, fg_color="transparent")
        self.format_subframe.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(10, 0))

        if metadata.is_playlist:
            details = [
                ("Playlist Title:", metadata.title),
                ("Playlist Owner:", metadata.uploader),
                ("Total Videos:", f"{metadata.total_videos} videos"),
            ]
            self.quality_combo.configure(state="disabled")
        else:
            details = [
                ("Title:", metadata.title),
                ("Channel:", metadata.uploader),
                ("Duration:", metadata.duration or "N/A"),
                ("Upload Date:", metadata.upload_date or "Unknown"),
                ("Views:", metadata.view_count or "0"),
            ]
            
            # Setup Quality Dropdown values
            self._on_mode_change(self.download_mode_var.get())

        # Layout metadata details
        for i, (label_text, val_text) in enumerate(details):
            lbl_name = ctk.CTkLabel(self.metadata_subframe, text=label_text, font=("Segoe UI", 11, "bold"), text_color="#94a3b8", anchor="w")
            lbl_name.grid(row=i, column=0, sticky="w", pady=2)
            lbl_val = ctk.CTkLabel(self.metadata_subframe, text=val_text, font=("Segoe UI", 11), text_color="#f8fafc", anchor="w", wraplength=450, justify="left")
            lbl_val.grid(row=i, column=1, sticky="w", padx=(10, 0), pady=2)

    def _on_analysis_failure(self, exc: Exception) -> None:
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0.0)
        self.stat_status.configure(text="Status: Ready")
        
        self.metadata = None
        self.video_options = []
        self.audio_option = None
        
        self._set_ui_state_idle()
        self.status_var.set("Status: Ready")

        from analyzer import (
            InvalidURLError,
            VideoUnavailableError,
            AgeRestrictedError,
            NetworkError
        )

        title = "Analysis Failed"
        icon = "cancel"

        # Determine user-friendly messages for different exception subclasses
        if isinstance(exc, InvalidURLError):
            title = "Invalid URL"
            message = str(exc)
            icon = "warning"
        elif isinstance(exc, VideoUnavailableError):
            title = "Content Unavailable"
            message = str(exc)
            icon = "cancel"
        elif isinstance(exc, AgeRestrictedError):
            title = "Age Restricted"
            message = str(exc)
            icon = "warning"
        elif isinstance(exc, NetworkError):
            title = "Network Error"
            message = str(exc)
            icon = "warning"
        else:
            message = f"An unexpected error occurred during URL analysis:\n{str(exc)}"

        CTkMessagebox(title=title, message=message, icon=icon)

    def _on_mode_change(self, mode: str) -> None:
        is_analyzed_video = self.metadata is not None and not self.metadata.is_playlist
        
        if mode == "Audio (MP3)":
            # Hide quality selector combobox, display Best Audio label placeholder
            self.quality_combo.grid_forget()
            self.best_audio_label.grid(row=1, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=6)
            self.quality_lbl.configure(text="Quality")
        else:
            # Show quality selector combobox, hide Best Audio label placeholder
            self.best_audio_label.grid_forget()
            self.quality_combo.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=6)
            self.quality_lbl.configure(text="Quality")
            
            # Populate combo values if analyzed
            if is_analyzed_video and self.video_options:
                labels = [opt.quality_label for opt in self.video_options]
                self.quality_combo.configure(values=labels)
                self.quality_combo.configure(state="normal")
                self.quality_var.set(labels[0] if labels else "Best available")
            else:
                self.quality_combo.configure(values=["Best available"])
                self.quality_combo.configure(state="disabled")
                self.quality_var.set("Best available")

        # Update dynamic format details in UI
        self._update_format_details()

    def _on_quality_change(self, quality: str) -> None:
        self._update_format_details()

    def _update_format_details(self) -> None:
        # Clear previous formats info
        for widget in self.format_subframe.winfo_children():
            widget.destroy()

        if self.metadata is None or self.metadata.is_playlist:
            return

        mode = self.download_mode_var.get()
        
        if mode == "Audio (MP3)":
            if self.audio_option:
                opt = self.audio_option
                bitrate_str = f"{opt.audio_format.bitrate:.0f} kbps" if opt.audio_format and opt.audio_format.bitrate else "Unknown"
                details = [
                    ("Selected Quality:", "Best Audio"),
                    ("Container:", "mp3"),
                    ("Estimated Size:", format_size(opt.estimated_filesize)),
                    ("Codec:", f"mp3 (source: {opt.audio_codec})"),
                    ("Bitrate:", bitrate_str)
                ]
            else:
                details = [
                    ("Selected Quality:", "Best Audio"),
                    ("Container:", "mp3"),
                    ("Estimated Size:", "Unknown size"),
                    ("Codec:", "mp3"),
                    ("Bitrate:", "Unknown")
                ]
        else:
            selected_quality = self.quality_var.get()
            matching_opt = None
            if self.video_options:
                for opt in self.video_options:
                    if opt.quality_label == selected_quality:
                        matching_opt = opt
                        break

            if matching_opt:
                # Format specific details
                details = [
                    ("Selected Quality:", matching_opt.quality_label),
                    ("Container:", matching_opt.container),
                    ("Estimated Size:", format_size(matching_opt.estimated_filesize)),
                    ("Video Codec:", matching_opt.video_codec),
                    ("Audio Codec:", matching_opt.audio_codec),
                ]
            else:
                details = [
                    ("Selected Quality:", selected_quality),
                    ("Container:", "mp4"),
                    ("Estimated Size:", "Unknown size"),
                    ("Video Codec:", "Unknown"),
                    ("Audio Codec:", "Unknown"),
                ]

        # Layout inside format_subframe with a distinct color theme (Sky Blue labels)
        for i, (label_text, val_text) in enumerate(details):
            lbl_name = ctk.CTkLabel(self.format_subframe, text=label_text, font=("Segoe UI", 11, "bold"), text_color="#38bdf8", anchor="w")
            lbl_name.grid(row=i, column=0, sticky="w", pady=2)
            lbl_val = ctk.CTkLabel(self.format_subframe, text=val_text, font=("Segoe UI", 11), text_color="#f1f5f9", anchor="w", wraplength=450, justify="left")
            lbl_val.grid(row=i, column=1, sticky="w", padx=(10, 0), pady=2)

    def _download_action(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Status: please enter a YouTube URL first")
            return

        # Parse selected formats
        video_format_id = None
        audio_format_id = None
        
        is_analyzed_video = self.metadata is not None and not self.metadata.is_playlist
        if is_analyzed_video:
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

        # Add to Sequential Queue
        self.queue.add_task(
            url=url,
            output_dir=self.output_dir_var.get(),
            mode=self.download_mode_var.get(),
            quality_label=self.quality_var.get(),
            video_format_id=video_format_id,
            audio_format_id=audio_format_id,
        )
        self.status_var.set("Status: Added task to queue")

    def _on_queue_changed(self) -> None:
        self.root.after(0, self._render_queue)
        
        # Check active execution state to toggle locks
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
        # File title header
        title = task.title
        self.current_file_label.configure(text=f"Downloading: {title}")

        # Current progress bar 1
        progress_val = task.progress / 100.0
        self.progress_bar.set(progress_val)
        self.video_progress_lbl.configure(text=f"Current Video: {task.progress:.1f}%")

        # Overall progress bar 2 for playlist downloads
        info_dict = data.get("info_dict", {})
        playlist_index = info_dict.get("playlist_index")
        playlist_count = info_dict.get("playlist_count")

        if playlist_index is not None and playlist_count is not None:
            # Grid twin bars if playlist active
            if not self.playlist_progress_bar.winfo_manager():
                self.playlist_progress_lbl.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 2))
                self.playlist_progress_bar.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
            
            # Overall percentage math
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

        # Stats grid values
        status_text = "Downloading..."
        if "FFmpegMerger" in str(data.get("postprocessor", "")):
            status_text = "Merging Video + Audio..."
        elif "FFmpegExtractAudio" in str(data.get("postprocessor", "")):
            status_text = "Converting Audio..."
        
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

        # Re-render queue list to update active row percents
        self._render_queue()

    def _render_queue(self) -> None:
        # Clear frame children
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

            # Controls: Cancel for processing tasks, Retry/Remove for finished failures
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
        
        # Reset labels
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

        # Grid queue summary cards in the preview section
        self.preview_image_label.grid_forget()
        self.details_frame.grid_forget()
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

        # Open Dialog Complete window Popup
        output_dir = self.output_dir_var.get()
        title_summary = f"{summary['completed']} items downloaded successfully"
        DownloadCompleteDialog(self.root, title_summary, output_dir, summary["duration"])
