"""Quien esta usando la app: quien corre ahora y quien trabajo cuanto.

Los datos salen de `actividad_de_agentes`, que parte de `profiles` y no de
`process_logs`: asi aparece tambien quien NO ha trabajado, que es la mitad de
la pregunta que el panel viene a responder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.settings import Settings, get_settings
from storage.supabase_client import SupabaseClientProvider

DIAS_POR_DEFECTO = 7
MINUTOS_EN_CURSO_POR_DEFECTO = 120


@dataclass(frozen=True)
class ActividadDeAgente:
    user_id: str
    email: str
    display_name: str
    login_id: str
    role: str
    disabled: bool
    corriendo: bool
    corriendo_desde: datetime | None
    ultima_corrida: datetime | None
    ultimo_sitio: str
    ultimo_estado: str
    nombre_escrito: str
    corridas_hoy: int
    corridas_periodo: int

    @property
    def identificador(self) -> str:
        """Como llamar a este agente en pantalla."""

        if self.display_name and self.email:
            return f"{self.display_name} | {self.email}"
        return self.display_name or self.email or self.login_id or self.user_id

    @property
    def firma_distinta(self) -> bool:
        """Si firmo las corridas con un nombre que no es el suyo.

        No es necesariamente un engaño -mucha gente escribe un apodo-, pero
        es lo unico que antes no se podia ni ver, porque el nombre escrito era
        el unico dato que habia.
        """

        escrito = self.nombre_escrito.strip().lower()
        if not escrito:
            return False
        propios = {
            self.display_name.strip().lower(),
            self.login_id.strip().lower(),
            self.email.strip().lower(),
            self.email.partition("@")[0].strip().lower(),
        }
        return escrito not in {valor for valor in propios if valor}


@dataclass(frozen=True)
class ResumenDeActividad:
    agentes: list[ActividadDeAgente]
    sin_identificar: int
    dias: int

    @property
    def corriendo_ahora(self) -> list[ActividadDeAgente]:
        return [agente for agente in self.agentes if agente.corriendo]

    @property
    def trabajaron(self) -> list[ActividadDeAgente]:
        return [agente for agente in self.agentes if agente.corridas_periodo > 0]

    @property
    def sin_aparecer(self) -> list[ActividadDeAgente]:
        return [
            agente
            for agente in self.agentes
            if agente.corridas_periodo == 0 and not agente.disabled
        ]


def _a_fecha(valor) -> datetime | None:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    try:
        fecha = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _a_entero(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def texto_de_antiguedad(fecha: datetime | None, ahora: datetime | None = None) -> str:
    """Hace cuanto fue algo, en palabras. Vacio si no se sabe."""

    if fecha is None:
        return ""
    transcurrido = (ahora or datetime.now(timezone.utc)) - fecha
    if transcurrido < timedelta(0):
        return "ahora mismo"
    segundos = int(transcurrido.total_seconds())
    if segundos < 120:
        return "hace un momento"
    minutos = segundos // 60
    if minutos < 60:
        return f"hace {minutos} min"
    horas = segundos // 3600
    if horas < 24:
        return "hace 1 hora" if horas == 1 else f"hace {horas} horas"
    dias = segundos // 86400
    return "hace 1 dia" if dias == 1 else f"hace {dias} dias"


class ActivityService:
    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)

    def resumen(
        self,
        *,
        dias: int = DIAS_POR_DEFECTO,
        minutos_en_curso: int = MINUTOS_EN_CURSO_POR_DEFECTO,
    ) -> ResumenDeActividad:
        filas = self._client_provider.execute(
            self._client_provider.client.rpc(
                "actividad_de_agentes",
                {"p_dias": dias, "p_minutos_en_curso": minutos_en_curso},
            )
        )
        agentes = [self._desde_fila(dict(fila)) for fila in filas]
        return ResumenDeActividad(
            agentes=agentes,
            sin_identificar=self._sin_identificar(dias),
            dias=dias,
        )

    def _sin_identificar(self, dias: int) -> int:
        """Corridas que no se pueden atribuir a nadie.

        Si esta funcion todavia no existe en Supabase no se rompe la pantalla
        entera por un contador: se devuelve cero y el resto se pinta igual.
        """

        try:
            filas = self._client_provider.execute(
                self._client_provider.client.rpc(
                    "corridas_sin_identificar",
                    {"p_dias": dias},
                )
            )
        except Exception:
            return 0
        if not filas:
            return 0
        primera = filas[0]
        if isinstance(primera, dict):
            return _a_entero(next(iter(primera.values()), 0))
        return _a_entero(primera)

    @staticmethod
    def _desde_fila(fila: dict) -> ActividadDeAgente:
        return ActividadDeAgente(
            user_id=str(fila.get("user_id") or ""),
            email=str(fila.get("email") or ""),
            display_name=str(fila.get("display_name") or ""),
            login_id=str(fila.get("login_id") or ""),
            role=str(fila.get("role") or "member"),
            disabled=bool(fila.get("disabled")),
            corriendo=bool(fila.get("corriendo")),
            corriendo_desde=_a_fecha(fila.get("corriendo_desde")),
            ultima_corrida=_a_fecha(fila.get("ultima_corrida")),
            ultimo_sitio=str(fila.get("ultimo_sitio") or ""),
            ultimo_estado=str(fila.get("ultimo_estado") or ""),
            nombre_escrito=str(fila.get("nombre_escrito") or ""),
            corridas_hoy=_a_entero(fila.get("corridas_hoy")),
            corridas_periodo=_a_entero(fila.get("corridas_periodo")),
        )
