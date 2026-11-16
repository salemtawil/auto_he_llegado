"""Pantalla de actividad: quien corre ahora y quien trabajo cuanto.

Dos vistas en una, porque son la misma pregunta vista de cerca y de lejos:
arriba quien esta trabajando en este instante, debajo quien ha trabajado en
el periodo y quien no ha aparecido.

Las filas son solo etiquetas, sin botones: esta pantalla se mira, no se toca.
Eso la hace barata de pintar, que es la leccion que dejo el panel de usuarios.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import customtkinter as ctk

from services.activity_service import (
    ActividadDeAgente,
    ActivityService,
    ResumenDeActividad,
    texto_de_antiguedad,
)
from ui.shared.errors import safe_error_summary
from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_ALT_BG,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    ON_ACCENT,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)

#: Lo que se puede elegir arriba. El numero son dias.
PERIODOS: tuple[tuple[str, int], ...] = (
    ("Hoy", 1),
    ("7 dias", 7),
    ("30 dias", 30),
)


def linea_de_agente(agente: ActividadDeAgente, ahora: datetime | None = None) -> str:
    """La linea de detalle de un agente que si trabajo."""

    partes = [f"hoy {agente.corridas_hoy}", f"periodo {agente.corridas_periodo}"]
    antiguedad = texto_de_antiguedad(agente.ultima_corrida, ahora)
    if antiguedad:
        partes.append(f"ultima {antiguedad}")
    if agente.ultimo_sitio:
        partes.append(agente.ultimo_sitio)
    if agente.ultimo_estado:
        partes.append(agente.ultimo_estado)
    return " | ".join(partes)


def resumen_en_una_linea(resumen: ResumenDeActividad) -> str:
    corriendo = len(resumen.corriendo_ahora)
    trabajaron = len(resumen.trabajaron)
    sin_aparecer = len(resumen.sin_aparecer)
    texto = (
        f"Corriendo ahora {corriendo} | "
        f"Trabajaron en {resumen.dias} dias {trabajaron} | "
        f"Sin aparecer {sin_aparecer}"
    )
    if resumen.sin_identificar:
        texto = f"{texto} | Sin identificar {resumen.sin_identificar}"
    return texto


class ActivityPanel(ctk.CTkFrame):
    _FILAS_POR_TANDA = 25

    def __init__(self, master, *, activity_service: ActivityService | None = None, **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._service = activity_service or ActivityService()
        self._is_loading = False
        self._dias = 7
        self._generacion = 0
        self._pendientes: list[tuple[str, object]] = []
        # Una sola vez, no una por fila: Tk no libera las fuentes al destruir
        # los widgets, y esta pantalla se refresca a menudo.
        self._fuente_seccion = ctk.CTkFont(size=13, weight="bold")
        self._fuente_titulo = ctk.CTkFont(size=12, weight="bold")
        self._fuente_detalle = ctk.CTkFont(size=11)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_list()
        self.refresh()

    # --- construccion ---------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(
            self,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        header.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Actividad",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")
        self.status_label = ctk.CTkLabel(
            header,
            text="Cargando actividad...",
            text_color=TEXT_MUTED,
            font=self._fuente_detalle,
            justify="left",
            wraplength=640,
        )
        self.status_label.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")

        botones = ctk.CTkFrame(header, fg_color="transparent")
        botones.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")
        self._botones_de_periodo: dict[int, ctk.CTkButton] = {}
        for columna, (etiqueta, dias) in enumerate(PERIODOS):
            boton = ctk.CTkButton(
                botones,
                text=etiqueta,
                command=lambda d=dias: self._cambiar_periodo(d),
                height=30,
                width=74,
                corner_radius=9,
                font=self._fuente_detalle,
            )
            boton.grid(row=0, column=columna, padx=(0, 6))
            self._botones_de_periodo[dias] = boton
        self.refresh_button = ctk.CTkButton(
            botones,
            text="Refrescar",
            command=self.refresh,
            height=30,
            width=94,
            corner_radius=9,
            font=self._fuente_detalle,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_button.grid(row=0, column=len(PERIODOS), padx=(6, 0))
        self._pintar_botones_de_periodo()

    def _build_list(self) -> None:
        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=CARD_ALT_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        self.scroll.grid(row=1, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _pintar_botones_de_periodo(self) -> None:
        for dias, boton in self._botones_de_periodo.items():
            elegido = dias == self._dias
            boton.configure(
                fg_color=ACCENT if elegido else NEUTRAL_BUTTON,
                hover_color=ACCENT_HOVER if elegido else NEUTRAL_BUTTON_HOVER,
                text_color=ON_ACCENT if elegido else TEXT_PRIMARY,
            )

    # --- carga ----------------------------------------------------------

    def _cambiar_periodo(self, dias: int) -> None:
        if dias == self._dias or self._is_loading:
            return
        self._dias = dias
        self._pintar_botones_de_periodo()
        self.refresh()

    def refresh(self) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self.refresh_button.configure(state="disabled", text="Cargando...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self) -> None:
        try:
            resumen = self._service.resumen(dias=self._dias)
            self.after(0, lambda actual=resumen: self._aplicar(actual))
        except Exception as exc:
            self.after(0, lambda error=exc: self._mostrar_error(error))

    def _mostrar_error(self, exc: Exception) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_label.configure(text=safe_error_summary(exc), text_color=ERROR)

    # --- pintado --------------------------------------------------------

    def _aplicar(self, resumen: ResumenDeActividad) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_label.configure(text=resumen_en_una_linea(resumen), text_color=TEXT_MUTED)
        self._generacion += 1
        for child in self.scroll.winfo_children():
            child.destroy()

        ahora = datetime.now(timezone.utc)
        pendientes: list[tuple[str, object]] = []
        corriendo = resumen.corriendo_ahora
        pendientes.append(("seccion", f"Corriendo ahora ({len(corriendo)})"))
        if corriendo:
            pendientes.extend(("corriendo", agente) for agente in corriendo)
        else:
            pendientes.append(("nota", "Nadie tiene una corrida abierta en este momento."))

        trabajaron = [a for a in resumen.trabajaron if not a.corriendo]
        pendientes.append(("seccion", f"Trabajaron en {resumen.dias} dias ({len(resumen.trabajaron)})"))
        if trabajaron:
            pendientes.extend(("trabajo", agente) for agente in trabajaron)
        elif not corriendo:
            pendientes.append(("nota", "Nadie registro corridas en este periodo."))

        sin_aparecer = resumen.sin_aparecer
        pendientes.append(("seccion", f"Sin aparecer ({len(sin_aparecer)})"))
        if sin_aparecer:
            pendientes.extend(("ausente", agente) for agente in sin_aparecer)
        else:
            pendientes.append(("nota", "Todos los agentes activos aparecieron."))

        if resumen.sin_identificar:
            pendientes.append(("seccion", "Sin identificar"))
            pendientes.append((
                "nota",
                f"{resumen.sin_identificar} corridas de este periodo no se pueden"
                " atribuir a nadie. Son anteriores a que se guardara el usuario,"
                " y no se pueden repartir a ojo.",
            ))

        self._ahora = ahora
        self._pendientes = pendientes
        self._pintar_tanda(0, self._generacion)

    def _pintar_tanda(self, desde: int, generacion: int) -> None:
        if generacion != self._generacion:
            return
        pendientes = self._pendientes
        if desde >= len(pendientes):
            return
        hasta = min(desde + self._FILAS_POR_TANDA, len(pendientes))
        for indice in range(desde, hasta):
            tipo, dato = pendientes[indice]
            if tipo == "seccion":
                widget = self._fila_de_seccion(str(dato))
            elif tipo == "nota":
                widget = self._fila_de_nota(str(dato))
            else:
                widget = self._fila_de_agente(dato, tipo)
            widget.grid(row=indice, column=0, padx=6, pady=(2, 3), sticky="ew")
        if hasta < len(pendientes):
            self.after(1, lambda s=hasta, g=generacion: self._pintar_tanda(s, g))

    def _fila_de_seccion(self, texto: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            self.scroll,
            text=texto,
            text_color=TEXT_PRIMARY,
            font=self._fuente_seccion,
            anchor="w",
        )

    def _fila_de_nota(self, texto: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            self.scroll,
            text=texto,
            text_color=TEXT_MUTED,
            font=self._fuente_detalle,
            anchor="w",
            justify="left",
            wraplength=820,
        )

    def _fila_de_agente(self, agente: ActividadDeAgente, tipo: str) -> ctk.CTkFrame:
        fila = ctk.CTkFrame(
            self.scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        fila.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            fila,
            text=agente.identificador,
            text_color=TEXT_PRIMARY,
            font=self._fuente_titulo,
            anchor="w",
        ).grid(row=0, column=0, padx=10, pady=(7, 1), sticky="ew")

        if tipo == "corriendo":
            desde = texto_de_antiguedad(agente.corriendo_desde, self._ahora)
            detalle = f"corriendo desde {desde}" if desde else "corriendo"
            if agente.ultimo_sitio:
                detalle = f"{detalle} | {agente.ultimo_sitio}"
            color = SUCCESS
        elif tipo == "ausente":
            detalle = "sin corridas en este periodo"
            color = WARNING
        else:
            detalle = linea_de_agente(agente, self._ahora)
            color = TEXT_MUTED

        ctk.CTkLabel(
            fila,
            text=detalle,
            text_color=color,
            font=self._fuente_detalle,
            anchor="w",
        ).grid(row=1, column=0, padx=10, pady=(0, 7), sticky="ew")

        if agente.firma_distinta:
            ctk.CTkLabel(
                fila,
                text=f"firma las corridas como \"{agente.nombre_escrito}\"",
                text_color=WARNING,
                font=self._fuente_detalle,
                anchor="w",
            ).grid(row=2, column=0, padx=10, pady=(0, 7), sticky="ew")
        return fila
