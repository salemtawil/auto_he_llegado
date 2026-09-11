from __future__ import annotations

import json
from urllib import parse, request

from config.settings import Settings, get_settings


class TelegramNotificationService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.telegram_bot_token and self._settings.telegram_chat_id)

    def send_video_received(
        self,
        *,
        user_label: str,
        original_name: str,
        size_bytes: int,
        duration_seconds: float,
        drive_url: str,
        duplicate_score: float | None = None,
    ) -> None:
        if not self.is_configured:
            return
        lines = [
            "Nuevo video recibido",
            "",
            f"Usuario: {user_label}",
            f"Archivo: {original_name}",
            f"Tamano: {self._format_bytes(size_bytes)}",
            f"Duracion: {self._format_duration(duration_seconds)}",
            f"Drive: {drive_url or 'sin enlace'}",
        ]
        if duplicate_score is not None:
            lines.append(f"Similitud visual: {duplicate_score:.0%}")
        self.send_message("\n".join(lines))

    def send_message(self, text: str) -> None:
        if not self.is_configured:
            return
        endpoint = f"https://api.telegram.org/bot{self._settings.telegram_bot_token}/sendMessage"
        body = parse.urlencode(
            {
                "chat_id": self._settings.telegram_chat_id,
                "text": text[:4096],
                "disable_web_page_preview": "false",
            }
        ).encode("utf-8")
        req = request.Request(endpoint, data=body, method="POST")
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram rechazo el mensaje: {payload}")

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        value = float(max(int(size_bytes), 0))
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:.1f} GB"

    @staticmethod
    def _format_duration(duration_seconds: float) -> str:
        total = max(int(round(duration_seconds)), 0)
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
