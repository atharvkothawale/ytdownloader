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
from downloader import Downloader
from format_manager import FormatManager, DownloadOption, format_size

logger = logging.getLogger("yt_downloader_pro.main_window")


class MainWindow:
    """Main application window for YT Downloader Pro using CustomTkinter."""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title("YT Downloader Pro")
        self.root.geometry("1180x760")
        self.root.minsize(1000, 700)
        self.root.configure(fg_color="#0f172a")

        self.download_mode_var = ctk.StringVar(value="Video (MP4)")
        self.output_dir_var = ctk.StringVar(value=str(self._default_output_dir()))
        self.status_var = ctk.StringVar(value="Status: waiting for input")
        self.quality_var = ctk.StringVar(value="Best available")
        
        self.downloader = Downloader()
        
        # Mapped format options state
        self.metadata: MediaMetadata | None = None
        self.video_options: list[DownloadOption] = []
        self.audio_option: DownloadOption | None = None

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

        # Main Card (where inputs and preview reside)
        self.main_card = ctk.CTkFrame(content, fg_color="#111827", corner_radius=8)
        self.main_card.grid(row=1, column=0, sticky="nsew", padx=28, pady=(9, 20))
        self.main_card.grid_columnconfigure(0, weight=1)
        self.main_card.grid_rowconfigure(4, weight=1)  # Preview panel is resizable

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

        self.download_button = ctk.CTkButton(action_row, text="Download", font=("Segoe UI", 11, "bold"), fg_color="#2563eb", hover_color="#1d4ed8", text_color="#ffffff", width=120, height=35, state="disabled", command=self._download_action)
        self.download_button.pack(side="left")

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

        # Progress Panel
        progress_panel = ctk.CTkFrame(self.main_card, fg_color="#1f2937", corner_radius=6)
        progress_panel.grid(row=5, column=0, sticky="ew", padx=24, pady=(0, 24))
        progress_panel.grid_columnconfigure(0, weight=1)

        progress_lbl = ctk.CTkLabel(progress_panel, text="Progress", font=("Segoe UI", 11, "bold"), text_color="#e2e8f0", anchor="w")
        progress_lbl.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
        
        self.progress_bar = ctk.CTkProgressBar(progress_panel, progress_color="#2563eb", fg_color="#111827", height=8)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=4)
        self.progress_bar.set(0.0)
        
        self.progress_status_label = ctk.CTkLabel(progress_panel, textvariable=self.status_var, font=("Segoe UI", 10), text_color="#cbd5e1", anchor="w")
        self.progress_status_label.grid(row=2, column=0, sticky="w", padx=16, pady=(4, 12))

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

    def _analyze_action(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            self.status_var.set("Status: please enter a YouTube URL first")
            return

        self.status_var.set("Status: analyzing URL and fetching formats...")
        self.analyze_button.configure(state="disabled")
        
        # Start loading animation
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        
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
        self.analyze_button.configure(state="normal")
        
        self.metadata = metadata
        self.video_options = video_options
        self.audio_option = audio_option

        media_type = "playlist" if metadata.is_playlist else "video"
        self.status_var.set(f"Status: analyzed {media_type} successfully")

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
            self.download_button.configure(state="normal")
        else:
            details = [
                ("Title:", metadata.title),
                ("Channel:", metadata.uploader),
                ("Duration:", metadata.duration or "N/A"),
                ("Upload Date:", metadata.upload_date or "Unknown"),
                ("Views:", metadata.view_count or "0"),
            ]
            
            # Setup Quality Dropdown values
            self.download_button.configure(state="normal")
            
            # Trigger Mode Change logic to setup quality selectors and populate details
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
        
        self.analyze_button.configure(state="normal")
        self.quality_combo.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.status_var.set("Status: analysis failed")

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

        # Modern CustomTkinter message box
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

        self.progress_bar.set(0.0)
        self.status_var.set("Status: starting download...")
        self.root.update_idletasks()

        threading.Thread(
            target=self._run_download,
            args=(url,),
            daemon=True,
        ).start()

    def _run_download(self, url: str) -> None:
        try:
            result = self.downloader.download(
                url=url,
                output_dir=self.output_dir_var.get(),
                mode=self.download_mode_var.get(),
                quality=self.quality_var.get(),
                progress_callback=self._update_progress,
            )
        except Exception as exc:
            logger.exception("Download failed in background thread")
            self.root.after(0, lambda: CTkMessagebox(title="Download Failed", message=f"Unable to download the media:\n{exc}", icon="cancel"))
            self.root.after(0, lambda: self.status_var.set("Status: download failed"))
            return

        self.root.after(0, lambda: self.progress_bar.set(1.0))
        self.root.after(0, lambda: self.status_var.set(f"Status: completed {result['title']}"))
        
        def update_ui_on_success():
            # Reset layout to display completion summary
            self.preview_image_label.grid_forget()
            self.details_frame.grid_forget()
            self.preview_placeholder.grid(row=0, column=0, columnspan=2, sticky="nw", padx=16, pady=16)
            self.preview_placeholder.configure(
                text=(
                    f"Download Completed Successfully!\n\n"
                    f"Title: {result['title']}\n"
                    f"Mode: {result['mode']}\n"
                    f"Quality: {result['quality']}\n"
                    f"Saved to: {result['output_dir']}"
                )
            )
        self.root.after(0, update_ui_on_success)

    def _update_progress(self, data: dict[str, Any]) -> None:
        if data.get("status") == "downloading":
            downloaded = data.get("downloaded_bytes", 0)
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 1
            percent = min(100.0, (downloaded / total) * 100.0)
            self.root.after(0, lambda: self.progress_bar.set(percent / 100.0))
            speed = data.get("speed") or 0
            eta = data.get("eta") or 0
            if speed:
                self.root.after(0, lambda: self.status_var.set(f"Status: {percent:.1f}% • {speed/1024/1024:.1f} MB/s • ETA {eta}s"))
            else:
                self.root.after(0, lambda: self.status_var.set(f"Status: {percent:.1f}% complete"))
