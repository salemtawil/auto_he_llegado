from __future__ import annotations

import customtkinter as ctk

from ui.theme import (
    ACCENT,
    ACCENT_SOFT,
    BORDER,
    CARD_ALT_BG,
    ERROR,
    ERROR_SOFT,
    INFO,
    INFO_SOFT,
    INPUT_BG,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    SUCCESS_SOFT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SOFT,
    WARNING,
    WARNING_SOFT,
)


class ExtensionStatusPanel(ctk.CTkFrame):
    def __init__(self, master, *, on_open_extensions=None, on_open_browser=None, on_export_state=None, **kwargs) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=20, border_width=1, border_color=BORDER, **kwargs)
        self._on_open_extensions = on_open_extensions
        self._on_open_browser = on_open_browser
        self._on_export_state = on_export_state
        self._compact = False
        self._details_visible = False
        self._detail_values: dict[str, ctk.CTkLabel] = {}
        self._history_rows: list[ctk.CTkLabel] = []

        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=14, pady=(10, 6), sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self.eyebrow = ctk.CTkLabel(
            header,
            text="Diagnostico",
            fg_color=ACCENT_SOFT,
            corner_radius=999,
            padx=8,
            pady=3,
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.eyebrow.grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Diagnóstico",
            font=ctk.CTkFont(family="Georgia", size=17, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=1, column=0, pady=(5, 1), sticky="w")

        self.subline = ctk.CTkLabel(
            header,
            text="Sin sesión de navegador detectada.",
            text_color=TEXT_SOFT,
            font=ctk.CTkFont(size=10),
        )
        self.subline.grid(row=2, column=0, sticky="w")

        self.header_buttons = ctk.CTkFrame(header, fg_color="transparent")
        self.header_buttons.grid(row=0, column=1, rowspan=3, sticky="e")

        self.open_browser_button = ctk.CTkButton(
            self.header_buttons,
            text="Abrir navegador",
            command=self._handle_open_browser,
            height=30,
            width=104,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.open_browser_button.grid(row=0, column=0, padx=(0, 6), sticky="e")

        self.export_state_button = ctk.CTkButton(
            self.header_buttons,
            text="Exportar debug",
            command=self._handle_export_state,
            height=30,
            width=120,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.export_state_button.grid(row=0, column=1, padx=(0, 6), sticky="e")

        self.open_extensions_button = ctk.CTkButton(
            self.header_buttons,
            text="Ver diagnóstico",
            command=self.toggle_details,
            height=30,
            width=124,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.open_extensions_button.grid(row=0, column=2, padx=(0, 6), sticky="e")

        self.extension_browser_button = ctk.CTkButton(
            self.header_buttons,
            text="Ver extensión",
            command=self._handle_open_extensions,
            height=30,
            width=108,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        self.extension_browser_button.grid(row=0, column=3, sticky="e")

        self.metrics = ctk.CTkFrame(self, fg_color="transparent")
        self.metrics.grid(row=1, column=0, padx=12, pady=(0, 10), sticky="ew")
        for column in range(5):
            self.metrics.grid_columnconfigure(column, weight=1)

        self.motor_chip = self._build_metric(self.metrics, 0, "Motor", "--")
        self.browser_chip = self._build_metric(self.metrics, 1, "Browser", "--")
        self.extension_chip = self._build_metric(self.metrics, 2, "Extensión", "--")
        self.phase_chip = self._build_metric(self.metrics, 3, "Fase", "--")
        self.overlay_chip = self._build_metric(self.metrics, 4, "Overlay", "--")
        self._detail_values["Motor"] = self.motor_chip

        self.message_card = ctk.CTkFrame(
            self,
            fg_color=INPUT_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.message_card.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        self.message_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.message_card,
            text="Resumen",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, padx=12, pady=(10, 0), sticky="w")
        self.message_label = ctk.CTkLabel(
            self.message_card,
            text="Todavía no hay confirmación de extensión.",
            text_color=TEXT_PRIMARY,
            justify="left",
            anchor="w",
            wraplength=520,
            font=ctk.CTkFont(size=11),
        )
        self.message_label.grid(row=1, column=0, padx=12, pady=(6, 12), sticky="ew")

        self.details_frame = ctk.CTkFrame(
            self,
            fg_color=INPUT_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        self.details_frame.grid_columnconfigure(0, weight=1)
        self.details_frame.grid_columnconfigure(1, weight=1)

        detail_labels = (
            "Browser args",
            "Manifest",
            "Service worker",
            "Frames",
            "Latest debug",
            "Nota",
        )
        for index, label in enumerate(detail_labels):
            row = index // 2
            column = index % 2
            card = ctk.CTkFrame(self.details_frame, fg_color="transparent")
            card.grid(
                row=row,
                column=column,
                padx=(12, 6) if column == 0 else (6, 12),
                pady=(10 if row == 0 else 6, 0),
                sticky="ew",
            )
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                card,
                text=label,
                font=ctk.CTkFont(size=9, weight="bold"),
                text_color=TEXT_MUTED,
            ).grid(row=0, column=0, sticky="w")
            value = ctk.CTkLabel(
                card,
                text="--",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=TEXT_PRIMARY,
                anchor="w",
                justify="left",
                wraplength=440,
            )
            value.grid(row=1, column=0, pady=(2, 0), sticky="ew")
            self._detail_values[label] = value

        self.history_card = ctk.CTkFrame(self.details_frame, fg_color="transparent")
        self.history_card.grid(row=3, column=0, columnspan=2, padx=12, pady=(8, 12), sticky="ew")
        self.history_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.history_card,
            text="Historial reciente",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color=TEXT_MUTED,
        ).grid(row=0, column=0, sticky="w")
        for index in range(4):
            label = ctk.CTkLabel(
                self.history_card,
                text="--",
                text_color=TEXT_PRIMARY,
                justify="left",
                anchor="w",
                wraplength=860,
                font=ctk.CTkFont(size=10),
            )
            label.grid(row=index + 1, column=0, pady=(6 if index == 0 else 4, 0), sticky="ew")
            self._history_rows.append(label)

        self.set_placeholder()

    def _build_metric(self, master, column: int, label: str, value: str) -> ctk.CTkLabel:
        tile = ctk.CTkFrame(master, fg_color=INPUT_BG, corner_radius=12)
        tile.grid(row=0, column=column, padx=(0, 8) if column < 4 else 0, sticky="ew")
        tile.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tile, text=label, font=ctk.CTkFont(size=9, weight="bold"), text_color=TEXT_MUTED).grid(
            row=0,
            column=0,
            padx=10,
            pady=(8, 0),
            sticky="w",
        )
        value_label = ctk.CTkLabel(tile, text=value, font=ctk.CTkFont(size=12, weight="bold"), text_color=TEXT_PRIMARY)
        value_label.grid(row=1, column=0, padx=10, pady=(2, 9), sticky="w")
        return value_label

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self.message_label.configure(wraplength=340 if compact else 760)
        for value in self._detail_values.values():
            value.configure(wraplength=340 if compact else 440)
        for value in self._history_rows:
            value.configure(wraplength=340 if compact else 860)
        if compact:
            for index, child in enumerate(self.metrics.winfo_children()):
                child.grid_configure(row=index // 2, column=index % 2, padx=(0, 8), pady=(0, 6), sticky="ew")
            for column in range(2):
                self.metrics.grid_columnconfigure(column, weight=1)
        else:
            for index, child in enumerate(self.metrics.winfo_children()):
                child.grid_configure(row=0, column=index, padx=(0, 8) if index < 4 else 0, pady=0, sticky="ew")
            for column in range(5):
                self.metrics.grid_columnconfigure(column, weight=1)
        if self._details_visible:
            self.details_frame.grid(
                row=3,
                column=0,
                padx=12,
                pady=(0, 12),
                sticky="ew",
            )

    def toggle_details(self) -> None:
        self._details_visible = not self._details_visible
        self.open_extensions_button.configure(text="Ocultar diagnóstico" if self._details_visible else "Ver diagnóstico")
        if self._details_visible:
            self.details_frame.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")
        else:
            self.details_frame.grid_forget()

    def set_placeholder(self) -> None:
        self.subline.configure(text="Sin sesión de navegador detectada.")
        self.motor_chip.configure(text="Traditional")
        self.browser_chip.configure(text="N/A")
        self.extension_chip.configure(text="No usada")
        self.phase_chip.configure(text="--")
        self.overlay_chip.configure(text="no")
        for value in self._detail_values.values():
            value.configure(text="--")
        for row in self._history_rows:
            row.configure(text="--")
        self.message_label.configure(text="Todavía no hay confirmación de extensión.")
        self._apply_visual_state("neutral")
        if self._details_visible:
            self.toggle_details()

    def set_status(
        self,
        *,
        session_active: bool,
        extension_requested: bool,
        flow_engine: str,
        session_debug: dict | None,
    ) -> None:
        debug = session_debug or {}
        state = debug.get("state") or {}
        phase = state.get("phase") or debug.get("phase") or "--"
        overlay_present = bool(debug.get("overlayPresent"))
        iframe_overlay_present = bool(debug.get("overlayFramePresent"))
        overlay_label = "sí" if overlay_present or iframe_overlay_present else "no"
        browser_channel = str(debug.get("browser_channel") or "N/A").strip() or "N/A"
        using_real_chrome = bool(debug.get("using_real_chrome"))
        uses_playwright_chromium = bool(debug.get("uses_playwright_chromium"))
        if using_real_chrome:
            browser_label = "Chrome"
        elif uses_playwright_chromium or browser_channel.lower() == "chromium":
            browser_label = "Chromium"
        elif browser_channel.lower() == "chrome":
            browser_label = "Chrome"
        else:
            browser_label = browser_channel if session_active else "N/A"

        extension_enabled = bool(debug.get("extension_enabled", extension_requested))
        extension_loaded = bool(debug.get("extension_loaded"))
        marker = str(debug.get("marker") or "").strip().lower()
        if flow_engine == "traditional":
            extension_label = "No usada"
        elif extension_loaded and marker == "loaded":
            extension_label = "Cargada"
        elif extension_loaded:
            extension_label = "Sin carga"
        elif extension_enabled:
            extension_label = "Sin carga"
        else:
            extension_label = "Desactivada"

        motor_label = "Extension" if flow_engine == "extension" else "Traditional"
        self.motor_chip.configure(text=motor_label)
        self.browser_chip.configure(text=browser_label)
        self.extension_chip.configure(text=extension_label)
        self.phase_chip.configure(text=phase or "--")
        self.overlay_chip.configure(text=overlay_label)

        note = str(debug.get("note") or "--").strip() or "--"
        manifest_path = debug.get("manifest_path") or "--"
        manifest_exists = bool(debug.get("manifest_exists"))
        service_worker = debug.get("extension_service_worker_url") or "--"
        browser_args = debug.get("browser_args") or []
        latest_debug_summary = self._build_latest_debug_summary(debug)
        frame_summary = self._build_frame_summary(debug)

        self._detail_values["Browser args"].configure(text=self._truncate(", ".join(browser_args) if browser_args else "--"))
        self._detail_values["Manifest"].configure(text=f"{manifest_path} ({'ok' if manifest_exists else 'missing'})")
        self._detail_values["Service worker"].configure(text=self._truncate(str(service_worker)))
        self._detail_values["Frames"].configure(text=frame_summary)
        self._detail_values["Latest debug"].configure(text=latest_debug_summary)
        self._detail_values["Nota"].configure(text=self._truncate(note))
        self._render_phase_history(state.get("phaseHistory") or [], debug.get("engine_phase_history") or [])

        summary_bits = [motor_label, browser_label, phase or "--"]
        self.subline.configure(text=" | ".join(summary_bits))
        self.message_label.configure(text=self._build_main_message(flow_engine, extension_label, browser_label, phase, note, session_active))
        self._apply_visual_state(self._resolve_visual_state(flow_engine, extension_label, session_active))

    def _resolve_visual_state(self, flow_engine: str, extension_label: str, session_active: bool) -> str:
        if flow_engine == "traditional":
            return "neutral" if session_active else "warning"
        if extension_label == "Cargada":
            return "success"
        if extension_label == "Sin carga":
            return "warning"
        if extension_label == "Desactivada":
            return "error"
        return "progress"

    def _build_main_message(
        self,
        flow_engine: str,
        extension_label: str,
        browser_label: str,
        phase: str,
        note: str,
        session_active: bool,
    ) -> str:
        if flow_engine == "traditional":
            if session_active:
                return f"Motor traditional activo. Browser: {browser_label}. Extensión: no usada."
            return "Motor traditional configurado. La extensión no se usa en este flujo."
        if not session_active:
            return "No hay una sesión de navegador activa para mostrar diagnóstico."
        return f"Motor extension. Browser: {browser_label}. Extensión: {extension_label}. Fase: {phase or '--'}. Nota: {note}."

    def _render_phase_history(self, entries: list[dict], engine_entries: list[dict]) -> None:
        normalized: list[str] = []
        for entry in reversed(engine_entries[-2:]):
            normalized.append(
                f"{(entry.get('observedAt') or '--')[-8:]} | {entry.get('phase') or '--'} | {entry.get('source') or 'usada'}"
            )
        for entry in entries[-2:]:
            normalized.append(
                f"{(entry.get('observedAt') or '--')[-8:]} | {entry.get('phase') or '--'} | observada"
            )
        for index, label in enumerate(self._history_rows):
            label.configure(text=normalized[index] if index < len(normalized) else "--")

    def _apply_visual_state(self, state: str) -> None:
        palette = {
            "success": (SUCCESS_SOFT, SUCCESS, SUCCESS),
            "error": (ERROR_SOFT, ERROR, ERROR),
            "progress": (INFO_SOFT, INFO, INFO),
            "warning": (WARNING_SOFT, WARNING, WARNING),
            "neutral": (ACCENT_SOFT, ACCENT, BORDER),
        }
        chip_fg, chip_text, border = palette.get(state, palette["neutral"])
        self.eyebrow.configure(fg_color=chip_fg, text_color=chip_text)
        self.message_card.configure(border_color=border)
        self.details_frame.configure(border_color=border)
        self.extension_chip.configure(text_color=chip_text)

    @staticmethod
    def _truncate(value: str, limit: int = 180) -> str:
        text = " ".join((value or "").split())
        if len(text) <= limit:
            return text or "--"
        return text[: limit - 3] + "..."

    def _build_frame_summary(self, debug: dict) -> str:
        marker_report = debug.get("marker_report") or {}
        ping_report = debug.get("ping_report") or {}
        frame_debug_report = debug.get("frame_debug_report") or {}
        total_frames = int(marker_report.get("total_frames") or 0)
        marker_hits = int(marker_report.get("frames_with_content_marker") or 0)
        ping_hits = int(ping_report.get("frames_with_ping") or 0)
        scanned = len(frame_debug_report.get("frames") or [])
        return f"marker={marker_hits}/{total_frames} | ping={ping_hits} | scan={scanned}"

    def _build_latest_debug_summary(self, debug: dict) -> str:
        phase_history = debug.get("engine_phase_history") or []
        if not phase_history:
            return self._truncate(str(debug.get("note") or "--"), limit=120)
        latest = phase_history[-1]
        return self._truncate(
            f"{latest.get('phase') or '--'} | {latest.get('source') or '--'} | {latest.get('frameRole') or '--'}",
            limit=120,
        )

    def _handle_open_extensions(self) -> None:
        if self._on_open_extensions is not None:
            self._on_open_extensions()

    def _handle_open_browser(self) -> None:
        if self._on_open_browser is not None:
            self._on_open_browser()

    def _handle_export_state(self) -> None:
        if self._on_export_state is not None:
            self._on_export_state()
