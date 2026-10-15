"""La revision de fotos esta deshabilitada (2026-10-13).

Decision del responsable del proyecto, "por el momento". El pool se alimenta
mientras tanto con el cargador masivo de JPG, que sigue ACTIVO.

Estas pruebas fijan tres cosas:
  * que la pestaña respeta el interruptor y sigue visible con un aviso;
  * que apagarla no toca el cargador de fotos ni la subida de video;
  * que no se borro nada: reactivar es cambiar una constante.
"""

from __future__ import annotations

import ast
from pathlib import Path

from config import features

RAIZ = Path(__file__).resolve().parents[1]
ADMIN = RAIZ / "ui" / "main_app" / "admin_dialogs.py"


def test_el_interruptor_esta_apagado() -> None:
    assert features.PHOTO_REVIEW_ENABLED is False
    mensaje = features.PHOTO_REVIEW_DISABLED_MESSAGE.lower()
    # El aviso debe explicar que pasa con los videos que ya se suben.
    assert "candidatos" in mensaje
    assert "carga" in mensaje


def test_la_pestana_de_revision_respeta_el_interruptor() -> None:
    texto = ADMIN.read_text(encoding="utf-8")
    cuerpo = texto.split("def _build_photo_review_tab(")[1].split("\n    def ")[0]

    assert "PHOTO_REVIEW_ENABLED" in cuerpo
    # El aviso tiene que ir ANTES de construir el panel real.
    assert cuerpo.index("PHOTO_REVIEW_ENABLED") < cuerpo.index("PhotoReviewPanel(")


def test_la_pestana_sigue_existiendo_con_aviso() -> None:
    """Se eligio avisar, no esconder."""

    texto = ADMIN.read_text(encoding="utf-8")
    assert 'self.tabs.add("Revision fotos")' in texto
    assert "_build_disabled_notice" in texto


def test_el_cargador_de_fotos_sigue_activo() -> None:
    """Lo que se apaga es la revision, NO la carga."""

    texto = ADMIN.read_text(encoding="utf-8")
    carga = texto.split("def _build_upload_tab(")[1].split("\n    def ")[0]
    assert "PHOTO_REVIEW_ENABLED" not in carga, "la pestaña Carga no debe quedar apagada"
    assert "UploaderPanel(" in carga

    uploader = (RAIZ / "app_uploader.py").read_text(encoding="utf-8")
    assert "PHOTO_REVIEW_ENABLED" not in uploader, (
        "AutoHeLlegadoUploader.exe debe seguir funcionando"
    )
    assert "UploaderWindow()" in uploader


def test_la_subida_de_video_sigue_intacta() -> None:
    ventana = (RAIZ / "ui" / "main_app" / "window.py").read_text(encoding="utf-8")
    assert "def open_video_uploader(" in ventana
    assert "PHOTO_REVIEW_ENABLED" not in ventana, (
        "el interruptor no debe condicionar nada de la ventana principal"
    )


def test_el_panel_de_revision_sigue_siendo_funcional_si_se_reactiva() -> None:
    """Deshabilitar no es borrar: el codigo debe seguir intacto y valido."""

    panel = RAIZ / "ui" / "main_app" / "photo_review_panel.py"
    ast.parse(panel.read_text(encoding="utf-8"))
    assert "class PhotoReviewPanel" in panel.read_text(encoding="utf-8")
    assert "from ui.main_app.photo_review_panel import PhotoReviewPanel" in ADMIN.read_text(
        encoding="utf-8"
    )
