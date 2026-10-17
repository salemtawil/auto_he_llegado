from __future__ import annotations

import hashlib
import io
import json
import ssl
from pathlib import Path

import pytest

import updater.release_update_client as ruc
from updater.release_update_client import (
    ReleaseUpdateError,
    download_release_asset,
    normalize_github_release,
    select_release_asset,
)


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._stream = io.BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_select_release_asset_prefers_matching_platform_dict() -> None:
    manifest = {
        "revision": "2026.06.19.1",
        "assets": {
            "windows": {
                "url": "https://example.test/windows.zip",
                "sha256": "abc",
                "file_name": "AutoHeLlegado_Windows_Update.zip",
            },
            "macos-x86_64": {
                "url": "https://example.test/mac.zip",
                "sha256": "def",
                "file_name": "AutoHeLlegado_Mac_x86_64_Update.zip",
            },
        },
    }

    asset = select_release_asset(manifest, sys_platform="darwin", machine="x86_64")

    assert asset.platform_key == "macos-x86_64"
    assert asset.file_name == "AutoHeLlegado_Mac_x86_64_Update.zip"


def test_select_release_asset_accepts_legacy_manifest_url() -> None:
    manifest = {
        "revision": "2026.06.19.1",
        "url": "https://example.test/AutoHeLlegado_Update.zip",
        "sha256": "abc",
    }

    asset = select_release_asset(manifest, sys_platform="win32", machine="amd64")

    assert asset.platform_key == "windows"
    assert asset.file_name == "AutoHeLlegado_Update.zip"


def test_normalize_github_release_uses_browser_download_url_and_digest() -> None:
    payload = {
        "tag_name": "2026.06.19.1",
        "assets": [
            {
                "name": "AutoHeLlegado_Windows_Update.zip",
                "browser_download_url": "https://example.test/update.zip",
                "digest": "sha256:" + "a" * 64,
            }
        ],
    }

    manifest = normalize_github_release(payload)

    assert manifest["revision"] == "2026.06.19.1"
    assert manifest["assets"] == [
        {
            "name": "AutoHeLlegado_Windows_Update.zip",
            "url": "https://example.test/update.zip",
            "sha256": "a" * 64,
        }
    ]


def test_download_release_asset_writes_zip_when_sha_matches(tmp_path: Path) -> None:
    payload = b"zip-content"
    manifest = {
        "revision": "2026.06.19.1",
        "url": "https://example.test/AutoHeLlegado_Update.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    asset = select_release_asset(manifest, sys_platform="win32", machine="amd64")

    downloaded = download_release_asset(
        asset,
        target_dir=tmp_path,
        urlopen_func=lambda _request, timeout=120: _FakeResponse(payload),
    )

    assert downloaded.path == tmp_path / "AutoHeLlegado_Update.zip"
    assert downloaded.path.read_bytes() == payload


def test_download_release_asset_rejects_placeholder_sha(tmp_path: Path) -> None:
    asset = select_release_asset(
        {
            "revision": "2026.06.19.1",
            "url": "https://example.test/AutoHeLlegado_Update.zip",
            "sha256": "REEMPLAZAR_CON_SHA256_REAL",
        },
        sys_platform="win32",
        machine="amd64",
    )

    with pytest.raises(ReleaseUpdateError, match="sha256 real"):
        download_release_asset(
            asset,
            target_dir=tmp_path,
            urlopen_func=lambda _request, timeout=120: _FakeResponse(b"zip-content"),
        )


# ---------------------------------------------------------------------------
# Certificados.
#
# Fallo real en el Mac Mini, 2026-10-17, al pulsar "Actualizar app":
#
#   No se pudo consultar GitHub: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]
#   certificate verify failed: unable to get local issuer certificate>
#
# El resto de la app hablaba con Supabase sin problema. La diferencia: todo lo
# demas usa httpx, que trae certifi incorporado, y el actualizador usaba
# urlopen pelado, que depende del almacen de OpenSSL. En una app empaquetada de
# macOS ese almacen no apunta a ningun sitio.
# ---------------------------------------------------------------------------


def test_el_contexto_tls_trae_certificados_raiz() -> None:
    contexto = ruc._contexto_con_certificados()

    # Sin autoridades cargadas, cualquier HTTPS falla con CERTIFICATE_VERIFY_FAILED.
    assert contexto.get_ca_certs(), "El contexto TLS no cargo ninguna autoridad raiz."
    assert contexto.verify_mode == ssl.CERT_REQUIRED


def test_sin_certifi_se_cae_al_contexto_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    # Quedarse sin certifi debe degradar al comportamiento anterior, nunca
    # reventar: el actualizador corre con la app ya cerrandose.
    import builtins

    real_import = builtins.__import__

    def _sin_certifi(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("certifi no disponible")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _sin_certifi)

    assert isinstance(ruc._contexto_con_certificados(), ssl.SSLContext)


def test_las_entradas_publicas_usan_el_urlopen_verificado() -> None:
    # Si alguna vuelve a urlopen pelado, el fallo solo aparece en una app
    # empaquetada: en desarrollo no se nota porque ahi el sistema si tiene
    # certificados.
    import inspect

    for funcion in (
        ruc.fetch_json,
        ruc.load_latest_manifest,
        ruc.download_release_asset,
        ruc.prepare_release_update,
    ):
        defecto = inspect.signature(funcion).parameters["urlopen_func"].default
        assert defecto is ruc.urlopen_verificado, f"{funcion.__name__} no verifica certificados."
