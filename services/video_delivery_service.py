from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import mimetypes
from pathlib import Path

from config.settings import Settings, get_settings
from core.errors import ErrorParaElAgente


@dataclass(frozen=True)
class VideoDeliveryResult:
    provider: str
    file_id: str
    url: str


class GoogleDriveVideoDeliveryService:
    _SCOPES = ("https://www.googleapis.com/auth/drive.file",)
    # Cuanto se espera a que la persona termine en el navegador. Tres minutos
    # sobran para autorizar y evitan que un descuido cuelgue la subida.
    AUTORIZACION_TIMEOUT_S = 180

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _token_file(self) -> Path | None:
        """Donde se guarda la autorizacion de Google.

        UNA por instalacion, a proposito: los videos van todos a la misma
        carpeta de Drive de la empresa, asi que la cuenta que autoriza tiene
        que ser la que tiene permiso sobre esa carpeta. Si cada agente
        autorizara la suya, la mayoria no podria escribir alli.

        Consecuencia buscada: se autoriza una vez y los demas agentes no
        vuelven a ver la pantalla. Cuando hace falta repetirla -alguien cerro
        la ventana sin querer, el navegador no abrio- se usa
        `olvidar_autorizacion()`, no se pide a cada subida.
        """

        return self._settings.google_drive_oauth_token_file

    def olvidar_autorizacion(self) -> bool:
        """Borra la autorizacion guardada para que la proxima subida la pida.

        Es la salida cuando el paso de Google se quedo a medias: la ventana
        se cerro antes de tiempo, el navegador no llego a abrirse, o la
        cuenta que se autorizo no era la que toca. Sin esto, la app creia
        tener una autorizacion -o ninguna- y no habia forma de volver a
        empezar sin entrar a mano en la carpeta de datos.

        Devuelve True si habia algo que olvidar.
        """

        token_file = self._token_file()
        if token_file is None or not token_file.exists():
            return False
        # Se renombra en vez de borrarse: si la nueva autorizacion falla,
        # la anterior todavia se puede recuperar a mano.
        respaldo = token_file.with_suffix(token_file.suffix + ".anterior")
        with suppress(Exception):
            respaldo.unlink()
        try:
            token_file.rename(respaldo)
        except Exception:  # noqa: BLE001 - si no se puede renombrar, se borra
            token_file.unlink(missing_ok=True)
        return True

    def upload_video(self, video_path: str | Path, *, display_name: str) -> VideoDeliveryResult:
        path = Path(video_path)
        self._validate_config(path)

        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        credentials = self._credentials()
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        media = MediaFileUpload(str(path), mimetype=mime_type, resumable=True)
        metadata = {
            "name": display_name,
            "parents": [self._settings.google_drive_folder_id],
        }
        request = drive.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink,webContentLink",
            supportsAllDrives=True,
        )
        response = None
        while response is None:
            _status, response = request.next_chunk()

        file_id = str(response.get("id") or "")
        if not file_id:
            raise RuntimeError("Google Drive no devolvio id del archivo subido.")

        if self._settings.google_drive_share_anyone:
            drive.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id",
                supportsAllDrives=True,
            ).execute()

        url = str(response.get("webViewLink") or response.get("webContentLink") or "")
        if not url:
            file_response = drive.files().get(
                fileId=file_id,
                fields="webViewLink,webContentLink",
                supportsAllDrives=True,
            ).execute()
            url = str(file_response.get("webViewLink") or file_response.get("webContentLink") or "")
        return VideoDeliveryResult(provider="google_drive", file_id=file_id, url=url)

    def _credentials(self):
        if self._settings.google_drive_auth_mode == "service_account":
            return self._service_account_credentials()
        if self._settings.google_drive_auth_mode != "oauth":
            raise RuntimeError(
                "GOOGLE_DRIVE_AUTH_MODE debe ser 'oauth' o 'service_account'."
            )
        return self._oauth_credentials()

    def _service_account_credentials(self):
        from google.oauth2 import service_account

        credentials_path = self._settings.google_drive_service_account_file
        if credentials_path is None:
            raise ErrorParaElAgente(
                "La cuenta de Google para subir videos no esta configurada en esta"
                " instalacion. Avisa al administrador."
            )
        if not credentials_path.exists() or not credentials_path.is_file():
            raise ErrorParaElAgente(
                "Falta el archivo de la cuenta de Google en esta instalacion."
                " Avisa al administrador."
            )
        return service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=list(self._SCOPES),
        )

    def _oauth_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_file = self._settings.google_drive_oauth_client_file
        token_file = self._token_file()
        if client_file is None:
            raise ErrorParaElAgente(
                "La cuenta de Google para subir videos no esta configurada en esta"
                " instalacion. Avisa al administrador."
            )
        if not client_file.exists() or not client_file.is_file():
            raise ErrorParaElAgente(
                "Falta el archivo de configuracion de Google en esta instalacion."
                " Avisa al administrador."
            )
        if token_file is None:
            raise ErrorParaElAgente(
                "Falta configurar donde se guarda la autorizacion de Google."
                " Avisa al administrador."
            )

        credentials = None
        if token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(token_file),
                scopes=list(self._SCOPES),
            )
        if credentials and credentials.valid:
            return credentials
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_file),
                scopes=list(self._SCOPES),
            )
            # CON TIMEOUT. Sin el, `run_local_server` se queda esperando el
            # redirect para siempre: si el agente cierra la ventana del
            # navegador sin autorizar -o el navegador nunca llega a abrirse-
            # el hilo de la subida queda colgado y en pantalla no pasa nada.
            try:
                credentials = flow.run_local_server(
                    port=0, timeout_seconds=self.AUTORIZACION_TIMEOUT_S
                )
            except Exception as exc:  # noqa: BLE001 - incluye el timeout
                raise ErrorParaElAgente(
                    "No se completo la verificacion de la cuenta de Google."
                    " Si la ventana no llego a abrirse o la cerraste sin"
                    " terminar, usa 'Reiniciar verificacion de Google' en"
                    " Ajustes y vuelve a subir el video."
                ) from exc
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        return credentials

    def _validate_config(self, video_path: Path) -> None:
        if not video_path.exists() or not video_path.is_file():
            raise ErrorParaElAgente("No se encontro el video que elegiste.")
        if not self._settings.google_drive_folder_id:
            raise ErrorParaElAgente(
                "Falta configurar la carpeta de Drive donde se guardan los videos."
                " Avisa al administrador."
            )
