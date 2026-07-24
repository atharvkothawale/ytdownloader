from __future__ import annotations

import customtkinter as ctk
from main_window import MainWindow


def main() -> None:
    # Set default CustomTkinter appearance and theme colors
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    
    root = ctk.CTk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
