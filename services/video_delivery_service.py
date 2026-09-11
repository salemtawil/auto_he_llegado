from __future__ import annotations

from dataclasses import dataclass
import mimetypes
from pathlib import Path

from config.settings import Settings, get_settings


@dataclass(frozen=True)
class VideoDeliveryResult:
    provider: str
    file_id: str
    url: str


class GoogleDriveVideoDeliveryService:
    _SCOPES = ("https://www.googleapis.com/auth/drive.file",)

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

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
            raise RuntimeError("Falta configurar GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE.")
        if not credentials_path.exists() or not credentials_path.is_file():
            raise RuntimeError(f"No existe GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE: {credentials_path}")
        return service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=list(self._SCOPES),
        )

    def _oauth_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        client_file = self._settings.google_drive_oauth_client_file
        token_file = self._settings.google_drive_oauth_token_file
        if client_file is None:
            raise RuntimeError("Falta configurar GOOGLE_DRIVE_OAUTH_CLIENT_FILE.")
        if not client_file.exists() or not client_file.is_file():
            raise RuntimeError(f"No existe GOOGLE_DRIVE_OAUTH_CLIENT_FILE: {client_file}")
        if token_file is None:
            raise RuntimeError("Falta configurar GOOGLE_DRIVE_OAUTH_TOKEN_FILE.")

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
            raise FileNotFoundError(f"Video no encontrado: {video_path}")
        if not self._settings.google_drive_folder_id:
            raise RuntimeError("Falta configurar GOOGLE_DRIVE_FOLDER_ID.")
