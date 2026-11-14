from __future__ import annotations

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

    def __init__(self, settings: Settings | None = None, *, user_key: str | None = None) -> None:
        self._settings = settings or get_settings()
        self._user_key = self._limpiar_user_key(user_key)

    @staticmethod
    def _limpiar_user_key(valor: str | None) -> str | None:
        """El identificador del agente, apto para formar un nombre de archivo."""

        if not valor:
            return None
        limpio = "".join(c for c in str(valor) if c.isalnum() or c in "-_")
        return limpio[:64] or None

    def _token_file(self) -> Path | None:
        """Donde se guarda la autorizacion de Google de ESTE agente.

        Era un unico archivo por instalacion, y eso tenia dos consecuencias
        que nadie queria: el primero que autorizaba dejaba su cuenta puesta
        para todos los demas del equipo -sus videos subian a la cuenta de
        otro- y ningun agente posterior volvia a ver la pantalla de
        verificacion, asi que parecia que la app se la saltaba.

        Ahora cada agente tiene la suya. Al actualizar, la primera subida de
        cada uno volvera a pedir la cuenta: eso es lo correcto, no un fallo.
        """

        base = self._settings.google_drive_oauth_token_file
        if base is None or self._user_key is None:
            return base
        return base.with_name(f"{base.stem}_{self._user_key}{base.suffix}")

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
            credentials = flow.run_local_server(port=0)
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
