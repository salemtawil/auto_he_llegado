from __future__ import annotations

import threading
import tkinter as tk
from contextlib import suppress
from concurrent.futures import ThreadPoolExecutor

import customtkinter as ctk

from datetime import datetime, timedelta

from services.access_service import AccessService
from services.auth_context import get_current_session
from services.user_access_admin_service import UserAccessAdminService, UserAccessRecord
from services.access_service import VideoRequirementPolicy
from services.photo_pool_policy_service import PhotoPoolPolicy
from ui.shared.dialogs import confirm_destructive_action
from ui.shared.plazos import DIAS_DE_AVISO, texto_de_plazo
from ui.shared.errors import safe_error_summary
from ui.theme import (
    ACCENT,
    ON_ACCENT,
    ACCENT_HOVER,
    BORDER,
    CARD_ALT_BG,
    CARD_BG,
    ERROR,
    NEUTRAL_BUTTON,
    NEUTRAL_BUTTON_HOVER,
    SUCCESS,
    TEXT_MUTED,
    TEXT_PRIMARY,
    WARNING,
)


def texto_buscable(user: UserAccessRecord) -> str:
    """Todo lo que el buscador considera de un usuario, en minusculas."""

    estado = "deshabilitado" if user.disabled else ("aprobado" if user.approved else "pendiente")
    partes = [
        user.display_name,
        user.email,
        user.login_id,
        user.role,
        estado,
        "exento" if user.video_exempt else "",
        user.weekly_video.status if user.weekly_video is not None else "sin video",
    ]
    return " ".join(parte for parte in partes if parte).lower()


#: Claves de color que devuelve `texto_de_vencimiento`. El calculo no sabe
#: nada de la paleta: el panel traduce la clave a un color.
COLOR_NEUTRO = "neutro"
COLOR_AL_DIA = "al_dia"
COLOR_POR_VENCER = "por_vencer"
COLOR_VENCIDO = "vencido"

def texto_de_vencimiento(
    user: UserAccessRecord,
    policy: VideoRequirementPolicy | None,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Cuanto le queda al video de este agente, en una linea.

    La cuenta sale de `AccessService.tiempo_restante_del_video`, la misma que
    decide si la app le deja entrar. No se recalcula aqui a proposito: dos
    formulas parecidas acabarian discrepando, y no hay nada peor que un panel
    que dice "te quedan 2 dias" el mismo dia que la app te deja fuera.
    """

    if user.disabled:
        return "sin vencimiento: el acceso esta deshabilitado", COLOR_NEUTRO
    if user.video_exempt:
        return "sin vencimiento: exento del video", COLOR_NEUTRO
    if str(user.role).strip().lower() == "admin":
        return "sin vencimiento: es admin", COLOR_NEUTRO
    if policy is not None and not policy.enabled:
        return "sin vencimiento: el video no se exige ahora", COLOR_NEUTRO

    video = user.weekly_video
    if video is None:
        return "sin video: no puede usar la app", COLOR_VENCIDO
    if str(video.status).strip().lower() == "rejected":
        return "video rechazado: tiene que subir otro", COLOR_VENCIDO

    dias = policy.days_for_duration(video.video_duration_seconds) if policy is not None else 7
    restante = AccessService.tiempo_restante_del_video(video.created_at, dias, now=now)
    if restante is None:
        return f"vence a los {dias} dias, pero no hay fecha del video", COLOR_NEUTRO
    if restante <= timedelta(0):
        vencido_hace = -restante
        return f"vencido hace {texto_de_plazo(vencido_hace)}", COLOR_VENCIDO
    color = COLOR_POR_VENCER if restante < timedelta(days=DIAS_DE_AVISO) else COLOR_AL_DIA
    return f"le quedan {texto_de_plazo(restante)}", color


def filtrar_usuarios(
    usuarios: list[UserAccessRecord],
    filtro: str,
    extra: dict[str, str] | None = None,
) -> list[UserAccessRecord]:
    """Filtra en memoria. Escribir en el buscador no toca la red.

    `extra` añade texto buscable por usuario que no sale de sus propios
    campos: lo usa el panel para que "vencido" encuentre a quien tiene el
    video caducado, que es un calculo, no un dato guardado.

    Vive fuera de la clase a proposito: asi tiene pruebas que corren en
    Windows, donde las de interfaz se saltan por no haber DISPLAY.
    """

    normalizado = (filtro or "").strip().lower()
    if not normalizado:
        return list(usuarios)
    terminos = normalizado.split()
    anadidos = extra or {}
    return [
        usuario
        for usuario in usuarios
        if all(
            termino in (texto_buscable(usuario) + " " + anadidos.get(usuario.id, "").lower())
            for termino in terminos
        )
    ]


class UserAccessPanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        access_admin_service: UserAccessAdminService | None = None,
        **kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self._service = access_admin_service or UserAccessAdminService()
        self._is_loading = False
        self._pool_bucket_values: list[str] = []
        # Cada fila de usuario creaba 11 objetos CTkFont. Con 100 usuarios son
        # 1.100 fuentes nuevas por refresco, y Tk no las libera al destruir los
        # widgets: era la mayor parte del tiempo que tardaba en abrir el panel.
        # Son todas iguales, asi que se crean una vez.
        self._fuente_titulo = ctk.CTkFont(size=12, weight="bold")
        self._fuente_etiqueta = ctk.CTkFont(size=12)
        self._fuente_campo = ctk.CTkFont(size=11, weight="bold")
        self._pendientes_de_pintar: list[UserAccessRecord] = []
        # La lista completa que vino de Supabase. El buscador filtra sobre
        # esto, en memoria: no se vuelve a pedir nada a la red por escribir.
        self._todos_los_usuarios: list[UserAccessRecord] = []
        # La politica vigente, para poder calcular cuanto le queda al video de
        # cada agente sin volver a preguntarla una vez por fila.
        self._politica_de_video: VideoRequirementPolicy | None = None
        # Texto de vencimiento ya calculado, por usuario: lo pinta la fila y
        # ademas lo busca el buscador ("vencido" encuentra a los caducados).
        self._vencimientos: dict[str, tuple[str, str]] = {}
        self._filtro = ""
        self._trabajo_de_busqueda: str | None = None
        # Solo un usuario desplegado a la vez. Los controles son el 80% del
        # coste de una fila, asi que como mucho existe un juego de ellos.
        self._desplegado = ""
        self._controles_desplegados: tuple[ctk.CTkFrame, ctk.CTkButton] | None = None
        # Pintar por tandas deja llamadas en cola. Si entretanto cambia el
        # filtro, las tandas viejas pintarian sobre la lista nueva.
        self._generacion = 0
        # Para no ofrecer borrarse a uno mismo: la politica de la base tambien
        # lo impide, pero un boton que siempre falla es un boton roto.
        sesion = get_current_session()
        self._mi_user_id = str(getattr(sesion, "user_id", "") or "")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build_header()
        self._build_controls()
        self._build_list()
        self.refresh()

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
            text="Usuarios",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(12, 2), sticky="w")

        self.status_label = ctk.CTkLabel(
            header,
            text="Cargando usuarios...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            justify="left",
        )
        self.status_label.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="w")

        self.refresh_button = ctk.CTkButton(
            header,
            text="Refrescar",
            command=self.refresh,
            height=34,
            width=104,
            corner_radius=10,
            font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.refresh_button.grid(row=0, column=1, rowspan=2, padx=14, pady=12, sticky="e")

    def _build_controls(self) -> None:
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=1, column=0, pady=(0, 8), sticky="ew")
        self.controls_frame.grid_columnconfigure(0, weight=1, uniform="settings")
        self.controls_frame.grid_columnconfigure(1, weight=1, uniform="settings")
        self._build_policy_panel()
        self._build_pool_policy_panel()

    def _build_policy_panel(self) -> None:
        panel = ctk.CTkFrame(
            self.controls_frame,
            fg_color=CARD_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        panel.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        panel.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(
            panel,
            text="Politica de video",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        self.policy_status_label = ctk.CTkLabel(
            panel,
            text="Cargando politica...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.policy_status_label.grid(row=1, column=0, columnspan=5, padx=14, pady=(0, 8), sticky="ew")
        self.video_required_var = tk.BooleanVar(value=True)
        self.video_required_switch = ctk.CTkSwitch(
            panel,
            text="Exigir video",
            variable=self.video_required_var,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12),
        )
        self.video_required_switch.grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        self.video_duration_based_var = tk.BooleanVar(value=False)
        self.video_duration_based_switch = ctk.CTkSwitch(
            panel,
            text="Por duracion",
            variable=self.video_duration_based_var,
            command=self._sync_duration_policy_controls,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            text_color=TEXT_PRIMARY,
            font=ctk.CTkFont(size=12),
        )
        self.video_duration_based_switch.grid(row=3, column=0, padx=14, pady=(0, 12), sticky="w")
        ctk.CTkLabel(
            panel,
            text="Menor a",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=1, padx=(6, 5), pady=(0, 6), sticky="e")
        self.video_threshold_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="25",
        )
        self.video_threshold_entry.grid(row=2, column=2, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="s: cada",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=3, padx=(5, 5), pady=(0, 6), sticky="w")
        self.video_days_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="7",
        )
        self.video_days_entry.grid(row=2, column=4, pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="dias",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=5, padx=(5, 8), pady=(0, 6), sticky="w")
        ctk.CTkLabel(
            panel,
            text="Desde ese tiempo: cada",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=1, columnspan=3, padx=(6, 5), pady=(0, 12), sticky="e")
        self.video_long_days_entry = ctk.CTkEntry(
            panel,
            height=30,
            width=58,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            placeholder_text="14",
        )
        self.video_long_days_entry.grid(row=3, column=4, pady=(0, 12), sticky="w")
        ctk.CTkLabel(
            panel,
            text="dias",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=5, padx=(5, 8), pady=(0, 12), sticky="w")
        self.save_policy_button = ctk.CTkButton(
            panel,
            text="Guardar",
            command=self._save_video_policy,
            height=32,
            width=96,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.save_policy_button.grid(row=2, column=6, rowspan=2, padx=14, pady=(0, 12), sticky="e")

    def _build_pool_policy_panel(self) -> None:
        panel = ctk.CTkFrame(
            self.controls_frame,
            fg_color=CARD_BG,
            corner_radius=14,
            border_width=1,
            border_color=BORDER,
        )
        panel.grid(row=0, column=1, padx=(6, 0), sticky="nsew")
        panel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            panel,
            text="Pool activo",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        self.pool_policy_status_label = ctk.CTkLabel(
            panel,
            text="Cargando pool activo...",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.pool_policy_status_label.grid(row=1, column=0, columnspan=3, padx=14, pady=(0, 8), sticky="ew")
        ctk.CTkLabel(
            panel,
            text="Bucket",
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, padx=14, pady=(0, 12), sticky="w")
        self.pool_bucket_var = tk.StringVar(value="")
        self.pool_bucket_menu = ctk.CTkOptionMenu(
            panel,
            values=["Cargando..."],
            variable=self.pool_bucket_var,
            height=32,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            dropdown_font=ctk.CTkFont(size=12),
            fg_color=NEUTRAL_BUTTON,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            dropdown_fg_color=CARD_BG,
            dropdown_hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.pool_bucket_menu.grid(row=2, column=1, padx=(0, 10), pady=(0, 12), sticky="ew")
        self.save_pool_policy_button = ctk.CTkButton(
            panel,
            text="Guardar",
            command=self._save_pool_policy,
            height=32,
            width=96,
            corner_radius=9,
            font=ctk.CTkFont(size=12),
            fg_color=ACCENT,
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
        )
        self.save_pool_policy_button.grid(row=2, column=2, padx=14, pady=(0, 12), sticky="e")

    def _build_list(self) -> None:
        buscador = ctk.CTkFrame(self, fg_color="transparent")
        buscador.grid(row=2, column=0, pady=(0, 8), sticky="ew")
        buscador.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            buscador,
            text="Buscar",
            text_color=TEXT_MUTED,
            font=self._fuente_campo,
        ).grid(row=0, column=0, padx=(2, 8), sticky="w")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._busqueda_cambiada)
        self.search_entry = ctk.CTkEntry(
            buscador,
            textvariable=self.search_var,
            height=32,
            corner_radius=9,
            font=self._fuente_etiqueta,
            placeholder_text="nombre, correo, usuario, rol o estado",
        )
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.clear_search_button = ctk.CTkButton(
            buscador,
            text="Limpiar",
            command=self._limpiar_busqueda,
            height=32,
            width=84,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        self.clear_search_button.grid(row=0, column=2, padx=(8, 2), sticky="e")

        self.scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=CARD_ALT_BG,
            corner_radius=12,
            border_width=1,
            border_color=BORDER,
        )
        self.scroll.grid(row=3, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

    def _busqueda_cambiada(self, *_args) -> None:
        # Repintar en cada tecla seria repintar la lista entera cinco veces
        # por palabra. Se espera a que pare de escribir.
        if self._trabajo_de_busqueda is not None:
            with suppress(Exception):
                self.after_cancel(self._trabajo_de_busqueda)
        self._trabajo_de_busqueda = self.after(180, self._aplicar_busqueda)

    def _aplicar_busqueda(self) -> None:
        self._trabajo_de_busqueda = None
        nuevo = self.search_var.get().strip().lower()
        if nuevo == self._filtro:
            return
        self._filtro = nuevo
        self._repintar_lista()

    def _limpiar_busqueda(self) -> None:
        self.search_var.set("")

    def refresh(self) -> None:
        if self._is_loading:
            return
        self._is_loading = True
        self.refresh_button.configure(state="disabled", text="Cargando...")
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        """Trae todo lo que pinta el panel.

        Antes eran seis idas y vueltas a Supabase EN FILA antes de dibujar
        nada: politica de video, politica de pool, lista de buckets, y dentro
        de `list_users` otra vez la politica de video mas los perfiles mas los
        lotes. Con una conexion domestica eso son varios segundos de pantalla
        vacia. Las tres primeras son independientes entre si, asi que van a la
        vez, y la politica ya consultada se le pasa a `list_users` para no
        pedirla dos veces.
        """

        try:
            with ThreadPoolExecutor(max_workers=3) as grupo:
                tarea_politica = grupo.submit(self._service.get_video_requirement_policy)
                tarea_pool = grupo.submit(self._service.get_photo_pool_policy)
                tarea_buckets = grupo.submit(self._service.list_photo_pool_buckets)
                policy = tarea_politica.result()
                pool_policy = tarea_pool.result()
                pool_buckets = tarea_buckets.result()
            users = self._service.list_users(policy=policy)
            self.after(0, lambda: self._apply_refresh(users, policy, pool_policy, pool_buckets))
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _apply_refresh(
        self,
        users: list[UserAccessRecord],
        policy: VideoRequirementPolicy,
        pool_policy: PhotoPoolPolicy,
        pool_buckets: list[str],
    ) -> None:
        # La politica primero: `_apply_users` la necesita para calcular los
        # vencimientos, y si llegara despues la primera pintada saldria con la
        # politica de antes.
        self._politica_de_video = policy
        self._apply_policy(policy)
        self._apply_pool_policy(pool_policy, pool_buckets)
        self._apply_users(users)

    def _apply_policy(self, policy: VideoRequirementPolicy) -> None:
        self.video_required_var.set(policy.enabled)
        self.video_duration_based_var.set(policy.duration_based)
        self.video_days_entry.delete(0, "end")
        self.video_days_entry.insert(0, str(policy.days))
        self.video_long_days_entry.delete(0, "end")
        self.video_long_days_entry.insert(0, str(policy.long_video_days))
        self.video_threshold_entry.delete(0, "end")
        threshold = policy.long_video_min_duration_seconds
        threshold_text = f"{threshold:.0f}" if float(threshold).is_integer() else f"{threshold:.1f}"
        self.video_threshold_entry.insert(0, threshold_text)
        state_text = "activo" if policy.enabled else "desactivado"
        mode_text = (
            f"Videos cortos cada {policy.days} dia(s); videos de {threshold_text}s o mas cada {policy.long_video_days}."
            if policy.duration_based
            else f"Frecuencia fija: cada {policy.days} dia(s), sin importar la duracion."
        )
        self.policy_status_label.configure(
            text=f"Requisito {state_text}. {mode_text}",
            text_color=SUCCESS if policy.enabled else WARNING,
        )
        self._sync_duration_policy_controls()

    def _apply_pool_policy(self, policy: PhotoPoolPolicy, buckets: list[str] | None = None) -> None:
        values = self._bucket_menu_values(policy.bucket, buckets or self._pool_bucket_values)
        self._pool_bucket_values = values
        self.pool_bucket_menu.configure(values=values)
        self.pool_bucket_var.set(policy.bucket)
        self.pool_policy_status_label.configure(
            text=f"Activo: {policy.bucket}",
            text_color=SUCCESS if policy.source == "supabase" else WARNING,
        )

    def _apply_users(self, users: list[UserAccessRecord]) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self._todos_los_usuarios = list(users)
        self._vencimientos = {
            usuario.id: texto_de_vencimiento(usuario, self._politica_de_video)
            for usuario in users
        }
        self._repintar_lista()

    def _usuarios_filtrados(self) -> list[UserAccessRecord]:
        buscable = {uid: texto for uid, (texto, _) in self._vencimientos.items()}
        return filtrar_usuarios(self._todos_los_usuarios, self._filtro, buscable)

    def _repintar_lista(self) -> None:
        usuarios = self._usuarios_filtrados()
        self._actualizar_contadores(usuarios)
        self._generacion += 1
        self._desplegado = ""
        self._controles_desplegados = None
        for child in self.scroll.winfo_children():
            child.destroy()
        if not self._todos_los_usuarios:
            self._mensaje_en_la_lista("No hay perfiles registrados.")
            return
        if not usuarios:
            self._mensaje_en_la_lista("Ningun usuario coincide con la busqueda.")
            return
        self._pendientes_de_pintar = usuarios
        self._pintar_siguiente_tanda(0, self._generacion)

    def _mensaje_en_la_lista(self, texto: str) -> None:
        ctk.CTkLabel(
            self.scroll,
            text=texto,
            text_color=TEXT_MUTED,
            font=self._fuente_etiqueta,
        ).grid(row=0, column=0, padx=12, pady=12, sticky="w")

    def _actualizar_contadores(self, mostrados: list[UserAccessRecord]) -> None:
        todos = self._todos_los_usuarios
        approved = sum(1 for user in todos if user.approved and not user.disabled)
        pending = sum(1 for user in todos if not user.approved and not user.disabled)
        disabled = sum(1 for user in todos if user.disabled)
        texto = f"Aprobados {approved} | Pendientes {pending} | Deshabilitados {disabled}"
        if self._filtro:
            texto = f"{texto} | mostrando {len(mostrados)} de {len(todos)}"
        self.status_label.configure(text=texto, text_color=TEXT_MUTED)

    _COLORES_DE_VENCIMIENTO = {
        COLOR_AL_DIA: SUCCESS,
        COLOR_POR_VENCER: WARNING,
        COLOR_VENCIDO: ERROR,
        COLOR_NEUTRO: TEXT_MUTED,
    }

    # Una fila plegada son 5 widgets; desplegada pasa de 40. Medido en el
    # contenedor: 67 ms por fila completa contra ~12 ms plegada, y con 100
    # usuarios eso era pintar el panel en 8,6 s sin haber tocado la red.
    _FILAS_POR_TANDA = 15

    def _pintar_siguiente_tanda(self, desde: int, generacion: int) -> None:
        if generacion != self._generacion:
            return
        pendientes = self._pendientes_de_pintar
        if desde >= len(pendientes):
            return
        hasta = min(desde + self._FILAS_POR_TANDA, len(pendientes))
        for indice in range(desde, hasta):
            self._fila_plegada(pendientes[indice]).grid(
                row=indice, column=0, padx=6, pady=5, sticky="ew"
            )
        if hasta < len(pendientes):
            self.after(
                1,
                lambda siguiente=hasta, gen=generacion: self._pintar_siguiente_tanda(siguiente, gen),
            )

    @staticmethod
    def _titulo_de(user: UserAccessRecord) -> str:
        identifier = user.email if "@" in user.email else ""
        if user.login_id:
            identifier = f"{identifier} | usuario: {user.login_id}" if identifier else f"usuario: {user.login_id}"
        title = identifier or user.email or user.id
        if user.display_name:
            title = f"{user.display_name} | {title}"
        return title

    @staticmethod
    def _estado_de(user: UserAccessRecord) -> tuple[str, object]:
        state = "deshabilitado" if user.disabled else ("aprobado" if user.approved else "pendiente")
        color = ERROR if user.disabled else (SUCCESS if user.approved else WARNING)
        exento = " | exento de video" if user.video_exempt else ""
        return f"{state} | rol {user.role}{exento}", color

    def _fila_plegada(self, user: UserAccessRecord) -> ctk.CTkFrame:
        row = ctk.CTkFrame(
            self.scroll,
            fg_color=CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            row,
            text=self._titulo_de(user),
            text_color=TEXT_PRIMARY,
            font=self._fuente_titulo,
            anchor="w",
        ).grid(row=0, column=0, padx=10, pady=(8, 1), sticky="ew")
        estado_texto, estado_color = self._estado_de(user)
        ctk.CTkLabel(
            row,
            text=estado_texto,
            text_color=estado_color,
            font=self._fuente_etiqueta,
            anchor="w",
        ).grid(row=1, column=0, padx=10, pady=(0, 7), sticky="ew")
        video_text, video_color = self._weekly_video_text(user)
        ctk.CTkLabel(
            row,
            text=video_text,
            text_color=video_color,
            font=self._fuente_etiqueta,
            anchor="w",
            justify="left",
        ).grid(row=2, column=0, padx=10, pady=(0, 2), sticky="ew")
        vencimiento, clave = self._vencimientos.get(
            user.id,
            texto_de_vencimiento(user, self._politica_de_video),
        )
        ctk.CTkLabel(
            row,
            text=vencimiento,
            text_color=self._COLORES_DE_VENCIMIENTO.get(clave, TEXT_MUTED),
            font=self._fuente_etiqueta,
            anchor="w",
        ).grid(row=3, column=0, padx=10, pady=(0, 8), sticky="ew")
        boton = ctk.CTkButton(
            row,
            text="Acciones",
            height=30,
            width=96,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        )
        boton.configure(
            command=lambda actual=user, fila=row, b=boton: self._alternar_controles(actual, fila, b)
        )
        boton.grid(row=0, column=1, rowspan=4, padx=10, pady=8, sticky="e")
        return row

    def _alternar_controles(
        self,
        user: UserAccessRecord,
        row: ctk.CTkFrame,
        boton: ctk.CTkButton,
    ) -> None:
        ya_estaba = self._desplegado == user.id
        if self._controles_desplegados is not None:
            marco_anterior, boton_anterior = self._controles_desplegados
            with suppress(Exception):
                marco_anterior.destroy()
            with suppress(Exception):
                boton_anterior.configure(text="Acciones")
            self._controles_desplegados = None
            self._desplegado = ""
        if ya_estaba:
            return
        marco = self._construir_controles(user, row)
        marco.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        boton.configure(text="Cerrar")
        self._desplegado = user.id
        self._controles_desplegados = (marco, boton)

    def _construir_controles(self, user: UserAccessRecord, row: ctk.CTkFrame) -> ctk.CTkFrame:
        """Lo caro de una fila: el campo de usuario y los ocho botones.

        Se construye solo cuando el admin abre esa fila, y solo hay uno
        abierto a la vez. Antes se construia para los cien usuarios al abrir
        el panel, se pulsara o no.
        """

        contenedor = ctk.CTkFrame(row, fg_color="transparent")
        contenedor.grid_columnconfigure(0, weight=1)

        login_frame = ctk.CTkFrame(contenedor, fg_color="transparent")
        login_frame.grid(row=0, column=0, pady=(0, 8), sticky="ew")
        login_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            login_frame,
            text="Usuario",
            text_color=TEXT_MUTED,
            font=self._fuente_campo,
        ).grid(row=0, column=0, padx=(0, 7), sticky="w")
        login_entry = ctk.CTkEntry(
            login_frame,
            height=28,
            corner_radius=8,
            font=self._fuente_etiqueta,
            placeholder_text="ej: salem",
        )
        login_entry.insert(0, user.login_id)
        login_entry.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(
            login_frame,
            text="Guardar",
            command=lambda current=user, entry=login_entry: self._run_login_id_update(current, entry.get()),
            height=28,
            width=72,
            corner_radius=8,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=2, padx=(7, 0), sticky="e")

        actions = ctk.CTkFrame(contenedor, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            actions,
            text="Aprobar",
            command=lambda current=user: self._run_action("approve", current),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=ACCENT,
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if user.approved and not user.disabled else "normal",
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Deshabilitar" if not user.disabled else "Habilitar",
            command=lambda current=user: self._run_action("disable" if not user.disabled else "enable", current),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
        ).grid(row=0, column=1, sticky="ew")
        has_video = user.weekly_video is not None
        video_accepted = has_video and user.weekly_video.status == "accepted"
        video_rejected = has_video and user.weekly_video.status == "rejected"
        ctk.CTkButton(
            actions,
            text="Aprobar video",
            command=lambda current=user: self._run_action("approve_video", current),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=ACCENT,
            text_color=ON_ACCENT,
            hover_color=ACCENT_HOVER,
            state="disabled" if not has_video or video_accepted else "normal",
        ).grid(row=1, column=0, padx=(0, 8), pady=(8, 0), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Rechazar video",
            command=lambda current=user: self._run_action("reject_video", current),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state="disabled" if not has_video or video_rejected else "normal",
        ).grid(row=1, column=1, pady=(8, 0), sticky="ew")
        ctk.CTkButton(
            actions,
            text="Exigir video" if user.video_exempt else "Eximir video",
            command=lambda current=user: self._run_action(
                "require_video" if current.video_exempt else "exempt_video",
                current,
            ),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state="disabled" if user.disabled or str(user.role).strip().lower() == "admin" else "normal",
        ).grid(row=2, column=0, columnspan=2, pady=(8, 0), sticky="ew")
        es_admin = str(user.role).strip().lower() == "admin"
        ctk.CTkButton(
            actions,
            text="Quitar admin" if es_admin else "Hacer admin",
            command=lambda current=user, admin=es_admin: self._run_action(
                "revoke_admin" if admin else "make_admin",
                current,
            ),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=NEUTRAL_BUTTON,
            hover_color=NEUTRAL_BUTTON_HOVER,
            text_color=TEXT_PRIMARY,
            state="disabled" if user.disabled else "normal",
        ).grid(row=3, column=0, padx=(0, 8), pady=(8, 0), sticky="ew")
        soy_yo = bool(self._mi_user_id) and user.id == self._mi_user_id
        ctk.CTkButton(
            actions,
            text="Borrar",
            command=lambda current=user: self._run_action("delete", current),
            height=30,
            corner_radius=9,
            font=self._fuente_etiqueta,
            fg_color=ERROR,
            hover_color=ERROR,
            text_color=ON_ACCENT,
            state="disabled" if soy_yo else "normal",
        ).grid(row=3, column=1, pady=(8, 0), sticky="ew")
        return contenedor

    def _run_login_id_update(self, user: UserAccessRecord, login_id: str) -> None:
        self.status_label.configure(text="Guardando usuario...", text_color=TEXT_MUTED)
        threading.Thread(
            target=lambda: self._login_id_worker(user, login_id),
            daemon=True,
        ).start()

    def _login_id_worker(self, user: UserAccessRecord, login_id: str) -> None:
        try:
            self._service.update_login_id(user.id, login_id)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    # Both of these are reversible from this same panel, so the dialog must not
    # claim otherwise.
    _CONFIRMATIONS = {
        "disable": (
            "Deshabilitar usuario",
            "{who} perdera el acceso a la aplicacion de inmediato.",
            "Puedes volver a habilitarlo con 'Aprobar' en esta misma lista.",
        ),
        "reject_video": (
            "Rechazar video",
            "Se rechazara el video de {who}; quedara sin acceso hasta que suba otro.",
            "Puedes aprobar el siguiente video que suba, o eximirlo del requisito.",
        ),
        "revoke_admin": (
            "Quitar administrador",
            "{who} dejara de ser administrador y perdera el panel de admin.",
            "Puedes volver a darselo con 'Hacer admin' en esta misma lista.",
        ),
    }

    # Este NO es reversible desde el panel, y por eso va aparte: el dialogo no
    # debe decir que se puede deshacer.
    _CONFIRMACION_BORRADO = (
        "Borrar usuario",
        "Se borrara el perfil de {who} y sus videos requeridos. Perdera el "
        "acceso de inmediato.\n\nSu cuenta seguira existiendo en Supabase "
        "(la app no puede borrarla), asi que ese email quedara ocupado y no "
        "podra volver a registrarse con el mismo correo.",
    )

    def _run_action(self, action: str, user: UserAccessRecord) -> None:
        who = user.login_id or user.email or user.id
        if action == "delete":
            title, template = self._CONFIRMACION_BORRADO
            if not confirm_destructive_action(
                title=title,
                what=template.format(who=who),
                reversible=False,
                parent=self,
            ):
                return
            self.status_label.configure(text="Borrando usuario...", text_color=TEXT_MUTED)
            threading.Thread(
                target=lambda: self._action_worker(action, user),
                daemon=True,
            ).start()
            return
        confirmation = self._CONFIRMATIONS.get(action)
        if confirmation is not None:
            title, template, undo_hint = confirmation
            who = user.login_id or user.email or user.id
            if not confirm_destructive_action(
                title=title,
                what=template.format(who=who),
                reversible=True,
                undo_hint=undo_hint,
                parent=self,
            ):
                return
        self.status_label.configure(text="Actualizando usuario...", text_color=TEXT_MUTED)
        threading.Thread(target=lambda: self._action_worker(action, user), daemon=True).start()

    def _action_worker(self, action: str, user: UserAccessRecord) -> None:
        try:
            if action == "approve":
                self._service.approve_user(user.id)
            elif action == "disable":
                self._service.disable_user(user.id)
            elif action == "approve_video":
                self._service.approve_weekly_video(user.id)
            elif action == "reject_video":
                self._service.reject_weekly_video(user.id)
            elif action == "exempt_video":
                self._service.set_video_exempt(user.id, True)
            elif action == "require_video":
                self._service.set_video_exempt(user.id, False)
            elif action == "make_admin":
                self._service.make_admin(user.id)
            elif action == "revoke_admin":
                self._service.revoke_admin(user.id)
            elif action == "delete":
                self._service.delete_user(user.id)
            else:
                self._service.enable_user(user.id)
            self.after(0, self.refresh)
        except Exception as exc:
            self.after(0, lambda error=exc: self._show_error(error))

    def _save_video_policy(self) -> None:
        raw_days = self.video_days_entry.get().strip()
        raw_long_days = self.video_long_days_entry.get().strip()
        raw_threshold = self.video_threshold_entry.get().strip()
        try:
            days = int(raw_days)
            long_days = int(raw_long_days)
            threshold = float(raw_threshold.replace(",", "."))
        except ValueError:
            self.policy_status_label.configure(text="Ingresa dias y segundos validos.", text_color=ERROR)
            return
        enabled = bool(self.video_required_var.get())
        duration_based = bool(self.video_duration_based_var.get())
        self.save_policy_button.configure(state="disabled", text="Guardando...")
        self.policy_status_label.configure(text="Guardando politica en Supabase...", text_color=TEXT_MUTED)
        threading.Thread(
            target=lambda: self._save_video_policy_worker(enabled, days, duration_based, long_days, threshold),
            daemon=True,
        ).start()

    def _save_video_policy_worker(
        self,
        enabled: bool,
        days: int,
        duration_based: bool,
        long_days: int,
        threshold: float,
    ) -> None:
        try:
            policy = self._service.update_video_requirement_policy(
                enabled=enabled,
                days=days,
                duration_based=duration_based,
                long_video_days=long_days,
                long_video_min_duration_seconds=threshold,
            )
            self.after(0, lambda current=policy: self._finish_video_policy_save(current))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_video_policy_error(error))

    def _finish_video_policy_save(self, policy: VideoRequirementPolicy) -> None:
        self.save_policy_button.configure(state="normal", text="Guardar")
        self._apply_policy(policy)
        self.refresh()

    def _finish_video_policy_error(self, exc: Exception) -> None:
        self.save_policy_button.configure(state="normal", text="Guardar")
        self.policy_status_label.configure(text=f"No se pudo guardar la política. Revisa tu conexión y vuelve a pulsar Guardar. ({safe_error_summary(exc, context='politica de video')})", text_color=ERROR)

    def _sync_duration_policy_controls(self) -> None:
        state = "normal" if bool(self.video_duration_based_var.get()) else "disabled"
        for widget in (self.video_threshold_entry, self.video_long_days_entry):
            widget.configure(state=state)

    def _save_pool_policy(self) -> None:
        bucket = self.pool_bucket_var.get().strip()
        if not bucket:
            self.pool_policy_status_label.configure(text="Selecciona un bucket valido.", text_color=ERROR)
            return
        self.save_pool_policy_button.configure(state="disabled", text="Guardando...")
        self.pool_policy_status_label.configure(text="Guardando pool activo en Supabase...", text_color=TEXT_MUTED)
        threading.Thread(target=lambda: self._save_pool_policy_worker(bucket), daemon=True).start()

    def _save_pool_policy_worker(self, bucket: str) -> None:
        try:
            policy = self._service.update_photo_pool_policy(bucket=bucket)
            self.after(0, lambda current=policy: self._finish_pool_policy_save(current))
        except Exception as exc:
            self.after(0, lambda error=exc: self._finish_pool_policy_error(error))

    def _finish_pool_policy_save(self, policy: PhotoPoolPolicy) -> None:
        self.save_pool_policy_button.configure(state="normal", text="Guardar")
        self._apply_pool_policy(policy)
        self.refresh()

    def _finish_pool_policy_error(self, exc: Exception) -> None:
        self.save_pool_policy_button.configure(state="normal", text="Guardar")
        self.pool_policy_status_label.configure(text=f"No se pudo guardar la política del pool. Revisa tu conexión y vuelve a pulsar Guardar. ({safe_error_summary(exc, context='politica del pool')})", text_color=ERROR)

    def _show_error(self, exc: Exception) -> None:
        self._is_loading = False
        self.refresh_button.configure(state="normal", text="Refrescar")
        self.status_label.configure(text=f"No se pudo cargar la lista de usuarios. Revisa tu conexión y pulsa Refrescar. ({safe_error_summary(exc, context='lista de usuarios')})", text_color=ERROR)

    @staticmethod
    def _bucket_menu_values(active_bucket: str, buckets: list[str]) -> list[str]:
        values: list[str] = []
        for bucket in [active_bucket, *buckets]:
            normalized = str(bucket or "").strip()
            if normalized and normalized not in values:
                values.append(normalized)
        return values or ["photo-pool"]

    @staticmethod
    def _weekly_video_text(user: UserAccessRecord) -> tuple[str, object]:
        video = user.weekly_video
        if video is None:
            return "Video requerido: no cargado | fotos extraidas: 0", WARNING
        color = SUCCESS if video.status == "accepted" else (ERROR if video.status == "rejected" else WARNING)
        text = (
            f"Video requerido: {video.status} | "
            f"extraidas {video.frames_extracted} | "
            f"candidatas {video.candidates_uploaded} | "
            f"fotos aprobadas {video.approved_count} | "
            f"rechazadas {video.rejected_count}"
        )
        if video.original_video_name:
            text = f"{text} | {video.original_video_name}"
        return text, color
