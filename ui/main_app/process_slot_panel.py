from __future__ import annotations

import customtkinter as ctk

from ui.main_app.form_panel import FormPanel
from ui.main_app.status_panel import StatusPanel
from ui.main_app.current_result_panel import CurrentResultPanel
from ui.theme import ACCENT, ACCENT_HOVER, BORDER, ERROR, CARD_ALT_BG, NEUTRAL_BUTTON, NEUTRAL_BUTTON_HOVER, ON_ACCENT, TEXT_MUTED, TEXT_PRIMARY


class ProcessSlotPanel(ctk.CTkFrame):
    # Altura minima deseable de la tarjeta. Es un MINIMO que el contenedor reserva
    # (grid_rowconfigure(minsize=...)), nunca una altura fija de la tarjeta: fijarla
    # fue la causa del recorte de los botones.
    _MIN_CARD_HEIGHT = 304
    # Ancho minimo que el formulario necesita para que sus tres botones quepan.
    _FORM_MIN_WIDTH = 330
    # Por debajo de este ancho de tarjeta, el panel de seguimiento pasa debajo del
    # formulario en vez de competir por el ancho con el.
    _STACK_BREAKPOINT = 700

    def __init__(
        self,
        master,
        *,
        title: str,
        on_start,
        on_clear,
        on_export_state,
        on_open_diagnostics=None,
        on_open_extensions=None,
        on_open_browser=None,
        on_owner_selfie_toggle=None,
        on_owner_selfie_select=None,
        on_owner_selfie_remove=None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color=CARD_ALT_BG, corner_radius=18, border_width=1, border_color=BORDER, **kwargs)
        self._compact = False
        self._secondary_visual = False
        self._on_open_diagnostics = on_open_diagnostics
        self._on_open_extensions = on_open_extensions
        self._on_open_browser = on_open_browser

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        # Sin grid_propagate(False) + height fija. Eso hacia que la tarjeta declarase
        # siempre _MIN_CARD_HEIGHT como altura requerida, sin importar lo que midiese
        # su contenido: con fuentes mas grandes (Windows al 125 %) o una ventana baja,
        # el gestor de geometria le daba menos de lo que el contenido necesita y Tk
        # recortaba la ultima fila, la de los botones. Ahora la tarjeta se mide por su
        # contenido y es el contenedor el que decide si hay que desplazarse.
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, padx=10, pady=(8, 2), sticky="ew")
        self.header.grid_columnconfigure(0, weight=1)
        self.header.grid_columnconfigure(1, weight=0)

        self.title_wrap = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_wrap.grid(row=0, column=0, sticky="w")
        self.title_wrap.grid_columnconfigure(1, weight=1)

        self.title_accent = ctk.CTkFrame(self.title_wrap, fg_color=ACCENT, width=5, height=18, corner_radius=999)
        self.title_accent.grid(row=0, column=0, padx=(0, 8), sticky="ns")

        self.eyebrow = ctk.CTkLabel(
            self.title_wrap,
            text=title,
            fg_color="transparent",
            corner_radius=0,
            padx=0,
            pady=0,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=TEXT_PRIMARY,
        )
        self.eyebrow.grid(row=0, column=1, sticky="w")

        self.summary_label = ctk.CTkLabel(
            self.title_wrap,
            text="",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=1),
        )
        self.summary_label.grid(row=1, column=1, pady=0, sticky="w")
        self.summary_label.grid_remove()

        self.process_timer_label = ctk.CTkLabel(
            self.header,
            text="Tiempo: 00:00",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.process_timer_label.grid(row=0, column=1, sticky="e")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="nsew")
        # Sin uniform="slot_body": forzar dos columnas de ancho identico hacia que,
        # en una ventana estrecha, la columna del formulario recibiese la mitad del
        # ancho aunque su contenido necesitase mas, y la fila de botones se cortaba
        # por la derecha ("Iniciar proce...", "...portar debug").
        self.body.grid_columnconfigure(0, weight=3, minsize=self._FORM_MIN_WIDTH)
        self.body.grid_columnconfigure(1, weight=2, minsize=0)
        self.body.grid_rowconfigure(0, weight=1)
        self.body.grid_rowconfigure(1, weight=0)

        self.form_panel = FormPanel(
            self.body,
            on_owner_selfie_toggle=on_owner_selfie_toggle,
            on_owner_selfie_select=on_owner_selfie_select,
            on_owner_selfie_remove=on_owner_selfie_remove,
        )
        self.form_panel.grid(row=0, column=0, sticky="nsew")

        self.status_panel = StatusPanel(self.body)
        self.status_panel.grid(row=0, column=1, padx=(10, 0), sticky="nsew")
        self._stacked_layout: bool | None = None
        # Cada tarjeta se adapta a SU ancho real, no al de la ventana: asi funciona
        # igual en una sola columna, en dos, o dentro del area desplazable.
        # add="+": CustomTkinter ya tiene su propio <Configure> en el widget; sin el
        # "+" el binding no llega y la tarjeta nunca se entera de su ancho real.
        self.bind("<Configure>", self._handle_card_resize, add="+")

        self.actions = self.form_panel.get_actions_container()
        self.actions.grid_columnconfigure(0, weight=1, uniform="primary_actions")
        self.actions.grid_columnconfigure(1, weight=1, uniform="primary_actions")
        self.actions.grid_columnconfigure(2, weight=1, uniform="primary_actions")

        self.run_button = ctk.CTkButton(
            self.actions,
            text="Iniciar proceso",
            command=on_start,
            height=28,
            corner_radius=10,
            fg_color=ACCENT,
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.run_button.grid(row=0, column=0, padx=(0, 5), pady=(0, 2), sticky="ew")
        self._run_button_mode = "start"

        self.clear_button = ctk.CTkButton(
            self.actions,
            text="Limpiar",
            command=on_clear,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.clear_button.grid(row=0, column=1, padx=(0, 5), pady=(0, 2), sticky="ew")

        self.export_debug_button = ctk.CTkButton(
            self.actions,
            text="Exportar debug",
            command=on_export_state,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.export_debug_button.grid(row=0, column=2, pady=(0, 2), sticky="ew")

        self.secondary_actions = ctk.CTkFrame(self.form_panel, fg_color="transparent")
        self.secondary_actions.grid_columnconfigure(0, weight=1)
        self.secondary_actions.grid_columnconfigure(1, weight=1)
        self.secondary_actions.grid_columnconfigure(2, weight=1)
        self.secondary_actions.grid(row=4, column=0, pady=(0, 0), sticky="ew")

        self.diagnostics_button = ctk.CTkButton(
            self.secondary_actions,
            text="Ver diagnóstico",
            command=self._handle_open_diagnostics,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.diagnostics_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.open_extensions_button = ctk.CTkButton(
            self.secondary_actions,
            text="Ver extensión",
            command=self._handle_open_extensions,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.open_extensions_button.grid(row=0, column=1, padx=(0, 6), sticky="ew")

        self.open_browser_button = ctk.CTkButton(
            self.secondary_actions,
            text="Abrir navegador",
            command=self._handle_open_browser,
            height=28,
            corner_radius=10,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.open_browser_button.grid(row=0, column=2, sticky="ew")

        self.result_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.result_wrap.grid_columnconfigure(0, weight=1)
        self.current_result_panel = CurrentResultPanel(self.result_wrap)
        # Aqui se creaba un ExtensionStatusPanel (126 widgets) que NUNCA se
        # colocaba en pantalla con grid/pack y que nadie leia: el diagnostico
        # que ve el operador es el de admin_dialogs.py:948, que si se muestra y
        # se alimenta bajo demanda con su boton "Refrescar".
        self._apply_visual_layout()

    def set_run_button_mode(self, mode: str) -> None:
        """Alterna el boton principal entre iniciar y detener.

        Se reutiliza el mismo boton en vez de anadir uno cuarto: la fila de
        acciones ya va justa de ancho y anadir otro volvia a recortarla en
        ventanas estrechas (ver tests/test_ui_layout.py).
        """

        normalized = "stop" if str(mode).strip().lower() == "stop" else "start"
        if normalized == getattr(self, "_run_button_mode", "start"):
            return
        self._run_button_mode = normalized
        if normalized == "stop":
            self.run_button.configure(
                text="Detener proceso",
                fg_color=ERROR,
                hover_color=ERROR,
            )
        else:
            self.run_button.configure(
                text="Iniciar proceso",
                fg_color=ACCENT,
                hover_color=ACCENT_HOVER,
            )

    def run_button_mode(self) -> str:
        return getattr(self, "_run_button_mode", "start")

    def set_compact_layout(self, compact: bool) -> None:
        self._compact = compact
        self._apply_visual_layout()

    def set_secondary_visual(self, secondary: bool) -> None:
        self._secondary_visual = secondary
        self._apply_visual_layout()

    def _handle_card_resize(self, event) -> None:
        # No se compara event.widget con self: en CustomTkinter el widget del evento
        # es el componente interno, no el envoltorio, asi que esa comparacion siempre
        # fallaba y la tarjeta nunca reaccionaba a su propio ancho.
        width = getattr(event, "width", 0) or self.winfo_width()
        if width > 1:
            self.apply_width_layout(width)

    def apply_width_layout(self, width: int) -> None:
        """Coloca el panel de seguimiento al lado o debajo segun el ancho.

        Es idempotente: solo re-coloca cuando cambia de modo, para no reconstruir el
        layout en cada evento <Configure> del redimensionado.
        """

        stacked = bool(width) and width < self._STACK_BREAKPOINT
        if stacked == self._stacked_layout:
            return
        self._stacked_layout = stacked
        if stacked:
            self.body.grid_columnconfigure(1, weight=0, minsize=0)
            self.form_panel.grid_configure(row=0, column=0, columnspan=2, sticky="nsew")
            self.status_panel.grid_configure(
                row=1, column=0, columnspan=2, padx=(0, 0), pady=(8, 0), sticky="nsew"
            )
            self.body.grid_rowconfigure(1, weight=1)
        else:
            self.body.grid_columnconfigure(1, weight=2, minsize=0)
            self.form_panel.grid_configure(row=0, column=0, columnspan=1, sticky="nsew")
            self.status_panel.grid_configure(
                row=0, column=1, columnspan=1, padx=(10, 0), pady=(0, 0), sticky="nsew"
            )
            self.body.grid_rowconfigure(1, weight=0)

    def natural_height(self) -> int:
        """Altura que la tarjeta necesita para mostrar todo su contenido."""

        self.update_idletasks()
        return max(self.winfo_reqheight(), self._MIN_CARD_HEIGHT)

    def set_summary(self, text: str) -> None:
        self.summary_label.configure(text=text or "")

    def _apply_visual_layout(self) -> None:
        header_padx = 10
        header_pady = (8, 2)
        body_padx = 10
        body_pady = (0, 8)

        self.configure(corner_radius=18)
        self.header.grid_configure(padx=header_padx, pady=header_pady)
        self.body.grid_configure(padx=body_padx, pady=body_pady)
        self.eyebrow.configure(font=ctk.CTkFont(size=12, weight="bold"))
        self.summary_label.configure(font=ctk.CTkFont(size=1))
        self.process_timer_label.configure(font=ctk.CTkFont(size=10, weight="bold"))
        self.run_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.clear_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )
        self.export_debug_button.configure(
            height=28,
            font=ctk.CTkFont(size=10, weight="bold"),
        )

        self.form_panel.set_compact_layout(True)
        self.status_panel.set_compact_layout(False)
        self.current_result_panel.set_compact_layout(True)
        self.secondary_actions.grid_remove()
        self.process_timer_label.grid_configure(row=0, column=1, pady=0, sticky="e")
        self.body.grid_columnconfigure(0, weight=3, minsize=self._FORM_MIN_WIDTH)
        self.body.grid_columnconfigure(1, weight=2)
        # No se fija aqui la posicion del panel de seguimiento: la decide
        # apply_width_layout segun el ancho real de la tarjeta.
        self._stacked_layout = None
        self.apply_width_layout(self.winfo_width())
        self.result_wrap.grid_forget()

    def _handle_open_diagnostics(self) -> None:
        if self._on_open_diagnostics is not None:
            self._on_open_diagnostics()

    def _handle_open_extensions(self) -> None:
        if self._on_open_extensions is not None:
            self._on_open_extensions()

    def _handle_open_browser(self) -> None:
        if self._on_open_browser is not None:
            self._on_open_browser()
