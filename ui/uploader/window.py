from __future__ import annotations

import customtkinter as ctk

from services.uploader_service import UploaderService
from ui.theme import APP_BG
from ui.uploader.panel import UploaderPanel


class UploaderWindow(ctk.CTk):
    def __init__(self, uploader_service: UploaderService | None = None) -> None:
        super().__init__()
        self._uploader_service = uploader_service or UploaderService()

        self.title("Uploader de Fotos")
        self.geometry("1080x720")
        self.minsize(920, 620)
        self.configure(fg_color=APP_BG)

        panel = UploaderPanel(self, uploader_service=self._uploader_service)
        panel.pack(fill="both", expand=True, padx=24, pady=24)
