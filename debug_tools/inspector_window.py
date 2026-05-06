from __future__ import annotations

import queue

import customtkinter as ctk

from config.settings import get_settings
from debug_tools.inspector_service import InspectorService
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    APP_BG,
    BORDER,
    CARD_BG,
    CARD_ALT_BG,
    ERROR,
    HEADER_BG,
    INPUT_BG,
    SECONDARY_BUTTON,
    SECONDARY_BUTTON_HOVER,
    TEXTBOX_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
)


class DebugInspectorWindow(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Debug Inspector")
        self.geometry("1180x760")
        self.minsize(980, 680)
        self.configure(fg_color=APP_BG)

        base_dir = get_settings().local_data_dir / "debug"
        self._service = InspectorService(str(base_dir))
        self._session_root = ""
        self._active = False
        self._site_var = ctk.StringVar(value="compinche")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_controls()
        self._build_body()
        self._poll_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_header(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=18, border_width=1, border_color=BORDER)
        frame.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            frame,
            text="Inspector automático de sitios",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=18, pady=(16, 6), sticky="w")

        self._status_label = ctk.CTkLabel(
            frame,
            text="Observación inactiva",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=TEXT_MUTED,
        )
        self._status_label.grid(row=1, column=0, padx=18, pady=(0, 16), sticky="w")

    def _build_controls(self) -> None:
        frame = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=18, border_width=1, border_color=BORDER)
        frame.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        frame.grid_columnconfigure(5, weight=1)

        self._site_menu = ctk.CTkOptionMenu(
            frame,
            values=["compinche", "paripe"],
            variable=self._site_var,
        )
        self._site_menu.grid(row=0, column=0, padx=(16, 10), pady=14, sticky="ew")

        ctk.CTkButton(
            frame,
            text="Abrir navegador",
            command=self._open_browser,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        ).grid(row=0, column=1, padx=10, pady=14, sticky="ew")

        ctk.CTkButton(
            frame,
            text="Iniciar observación",
            command=self._start_observation,
            fg_color=SECONDARY_BUTTON,
            hover_color=SECONDARY_BUTTON_HOVER,
        ).grid(row=0, column=2, padx=10, pady=14, sticky="ew")

        ctk.CTkButton(
            frame,
            text="Detener observación",
            command=self._service.stop_observation,
            fg_color=CARD_ALT_BG,
            hover_color=SECONDARY_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=3, padx=10, pady=14, sticky="ew")

        ctk.CTkButton(
            frame,
            text="Exportar reporte",
            command=self._service.export_report,
            fg_color=CARD_ALT_BG,
            hover_color=SECONDARY_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=4, padx=10, pady=14, sticky="ew")

        self._search_entry = ctk.CTkEntry(
            frame,
            placeholder_text="Texto opcional a vigilar en página/iframes",
            fg_color=INPUT_BG,
        )
        self._search_entry.grid(row=0, column=5, padx=(10, 16), pady=14, sticky="ew")

    def _build_body(self) -> None:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=2, column=0, padx=18, pady=(0, 18), sticky="nsew")
        frame.grid_columnconfigure(0, weight=3)
        frame.grid_columnconfigure(1, weight=2)
        frame.grid_rowconfigure(0, weight=1)

        log_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=18, border_width=1, border_color=BORDER)
        log_card.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            log_card,
            text="Eventos en tiempo real",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self._log_text = ctk.CTkTextbox(log_card, fg_color=TEXTBOX_BG, wrap="word")
        self._log_text.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._log_text.insert("1.0", "La herramienta espera eventos del worker de Playwright.\n")
        self._protect_textbox(self._log_text)

        side_card = ctk.CTkFrame(frame, fg_color=CARD_BG, corner_radius=18, border_width=1, border_color=BORDER)
        side_card.grid(row=0, column=1, padx=(10, 0), sticky="nsew")
        side_card.grid_columnconfigure(0, weight=1)
        side_card.grid_rowconfigure(1, weight=1)
        side_card.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            side_card,
            text="Iframes detectados",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self._iframe_text = ctk.CTkTextbox(side_card, height=220, fg_color=TEXTBOX_BG, wrap="word")
        self._iframe_text.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._iframe_text.insert("1.0", "Sin iframes todavía.\n")
        self._protect_textbox(self._iframe_text)

        ctk.CTkLabel(
            side_card,
            text="Sesión actual",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")

        self._session_text = ctk.CTkTextbox(side_card, height=160, fg_color=TEXTBOX_BG, wrap="word")
        self._session_text.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self._session_text.insert("1.0", "Los reportes se crearán en local_data/debug.\n")
        self._protect_textbox(self._session_text)

    def _start_observation(self) -> None:
        self._service.start_observation(self._search_entry.get())

    def _poll_events(self) -> None:
        while True:
            try:
                event = self._service.event_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        self.after(250, self._poll_events)

    def _handle_event(self, event: dict[str, object]) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "status":
            self._active = bool(event.get("active"))
            self._status_label.configure(
                text=str(event.get("message", "")),
                text_color=ACCENT if self._active else TEXT_MUTED,
            )
        elif event_type == "log":
            self._append_log(str(event.get("message", "")))
        elif event_type == "error":
            self._append_log(f"ERROR: {event.get('message', '')}")
            self._status_label.configure(text="Error en observación", text_color=ERROR)
        elif event_type == "snapshot":
            self._append_log(f"{event.get('kind', 'snapshot')}: {event.get('message', '')}")
            self._update_iframes(event.get("iframes"))
            self._update_session(event)
        elif event_type == "heartbeat":
            self._update_iframes(event.get("iframes"))

    def _append_log(self, message: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"{message}\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _update_iframes(self, payload: object) -> None:
        items = payload if isinstance(payload, list) else []
        lines = []
        for item in items:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"[{item.get('index', '-')}] title={item.get('title', '-') or '-'}\nsrc={item.get('src', '-') or '-'}\nurl={item.get('url', '-') or '-'}\naccesible={item.get('accessible', False)}\nerror={item.get('inspect_error', '') or '-'}\n"
            )
        if not lines:
            lines = ["Sin iframes detectados.\n"]
        self._iframe_text.configure(state="normal")
        self._iframe_text.delete("1.0", "end")
        self._iframe_text.insert("1.0", "\n".join(lines))
        self._iframe_text.configure(state="disabled")

    def _update_session(self, event: dict[str, object]) -> None:
        session_root = str(event.get("session_root", "") or "")
        if session_root:
            self._session_root = session_root
        lines = [
            f"Estado: {'activa' if self._active else 'inactiva'}",
            f"Sesión: {self._session_root or 'pendiente'}",
            f"URL: {event.get('url', '')}",
            f"Título: {event.get('title', '')}",
            f"Último evento: {event.get('kind', '')}",
            f"Hora: {event.get('at', '')}",
        ]
        self._session_text.configure(state="normal")
        self._session_text.delete("1.0", "end")
        self._session_text.insert("1.0", "\n".join(lines))
        self._session_text.configure(state="disabled")

    def _protect_textbox(self, textbox: ctk.CTkTextbox) -> None:
        textbox.configure(state="disabled")
        textbox.bind("<Control-c>", lambda _event: None)
        textbox.bind("<Control-a>", lambda event: self._select_all(event.widget))
        textbox.bind("<Key>", lambda event: "break" if not (event.state & 0x4) else None)

    def _select_all(self, widget: ctk.CTkTextbox) -> str:
        widget.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _on_close(self) -> None:
        self._service.shutdown()
        self.destroy()
    def _open_browser(self) -> None:
        self._service.open_browser(self._site_var.get())
