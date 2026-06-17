from __future__ import annotations

import base64
import ctypes
import json
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from config.settings import Settings, get_settings


@dataclass(frozen=True)
class RememberedLogin:
    identifier: str = ""
    password: str = ""


class LoginCredentialsStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._path = self._settings.local_data_dir / "remembered_login.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RememberedLogin:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return RememberedLogin()
        identifier = str(data.get("identifier") or "")
        encrypted_password = str(data.get("password_dpapi") or "")
        password = self._decrypt(encrypted_password) if encrypted_password else ""
        return RememberedLogin(identifier=identifier, password=password)

    def save(self, *, identifier: str, password: str) -> None:
        normalized_identifier = identifier.strip()
        if not normalized_identifier:
            self.clear()
            return
        payload = {"identifier": normalized_identifier}
        encrypted_password = self._encrypt(password)
        if encrypted_password:
            payload["password_dpapi"] = encrypted_password
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def clear(self) -> None:
        try:
            self._path.unlink()
        except FileNotFoundError:
            return

    @classmethod
    def _encrypt(cls, value: str) -> str:
        if not value:
            return ""
        protected = cls._crypt_protect(value.encode("utf-8"))
        return base64.b64encode(protected).decode("ascii") if protected else ""

    @classmethod
    def _decrypt(cls, value: str) -> str:
        try:
            encrypted = base64.b64decode(value.encode("ascii"))
            decrypted = cls._crypt_unprotect(encrypted)
            return decrypted.decode("utf-8") if decrypted else ""
        except Exception:
            return ""

    @staticmethod
    def _crypt_protect(data: bytes) -> bytes:
        if sys.platform != "win32":
            return b""

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        input_buffer = ctypes.create_string_buffer(data)
        input_blob = DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_char)))
        output_blob = DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            return b""
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)

    @staticmethod
    def _crypt_unprotect(data: bytes) -> bytes:
        if sys.platform != "win32":
            return b""

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        input_buffer = ctypes.create_string_buffer(data)
        input_blob = DataBlob(len(data), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_char)))
        output_blob = DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(output_blob),
        ):
            return b""
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(output_blob.pbData)
