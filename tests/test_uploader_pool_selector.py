"""Selector de pool destino en el panel de carga (UI) y contrato de la migracion.

Las pruebas de widgets necesitan un servidor X; se omiten si no lo hay.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


MIGRATION = Path(__file__).resolve().parents[1] / "sql" / "020_multi_photo_pool_buckets.sql"


# ---------------------------------------------------------------------------
# Contrato de la migracion (no necesita display ni Supabase)
# ---------------------------------------------------------------------------


def test_destinations_come_from_real_storage_buckets() -> None:
    """La lista de destinos sale de storage.buckets, no de un literal."""

    sql = MIGRATION.read_text(encoding="utf-8")

    targets = sql.split("function public.photo_pool_upload_targets", 1)[1].split("$$;", 1)[0]
    assert "from storage.buckets b" in targets
    # El bucket activo se marca, pero no filtra la lista.
    assert "is_active" in targets
    assert "where b.id::text = public.active_photo_pool_bucket()" not in targets
    # No hay ninguna lista de buckets escrita a mano como origen de los destinos.
    assert '"photo-pool-v2"' not in targets
    assert "'photo-pool-v2'" not in targets


def test_only_the_exclusion_list_is_seeded_by_hand() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    insert = re.search(
        r"insert into public\.app_settings.*?values\s*\(\s*'photo_pool_excluded_buckets',\s*'(.*?)'::jsonb",
        sql,
        re.S,
    )
    assert insert is not None, "falta el insert de exclusiones"
    # Lo unico sembrado a mano son las EXCLUSIONES, no los destinos.
    assert '"photos"' in insert.group(1)
    assert '"photo-pool"' not in insert.group(1)
    assert '"photo-pool-v2"' not in insert.group(1)


def test_jsonb_guard_lives_inside_the_function_argument() -> None:
    """Regresion: el guard en un WHERE no protege a jsonb_array_elements.

    Con el filtro fuera, un valor que no sea array revienta con
    "cannot extract elements from a scalar" en cuanto el planificador no puede
    bajar el filtro al LATERAL (vista, CTE materializado, OFFSET 0...).
    """

    sql = MIGRATION.read_text(encoding="utf-8")

    body = sql.split("function public.excluded_photo_pool_buckets", 1)[1].split("$$;", 1)[0]
    call = body.split("jsonb_array_elements(", 1)[1]
    guard = call.split(") as elem", 1)[0]
    assert "case" in guard
    assert "jsonb_typeof" in guard
    assert "'[]'::jsonb" in guard


def test_migration_does_not_widen_the_for_all_admin_policy() -> None:
    """Las politicas nuevas son por operacion, no FOR ALL."""

    sql = MIGRATION.read_text(encoding="utf-8")

    for name, operation in (
        ("photo_admin_pool_upload_insert", "for insert"),
        ("photo_admin_pool_upload_select", "for select"),
        ("photo_admin_pool_upload_delete", "for delete"),
    ):
        assert f'create policy "{name}"' in sql
        block = sql.split(f'create policy "{name}"', 1)[1].split(";", 1)[0]
        assert operation in block
        assert "for all" not in block
        # Cada politica sigue exigiendo administrador aprobado.
        assert "is_profile_admin(auth.uid())" in block
        assert "is_allowed_photo_pool_bucket(bucket_id)" in block

    # No se concede UPDATE sobre los pools permitidos: subir es un INSERT.
    assert 'create policy "photo_admin_pool_upload_update"' not in sql
    # La politica FOR ALL preexistente sigue ligada al bucket activo y no se toca.
    assert 'create policy "photo_admin_storage_write"' not in sql


def test_migration_keeps_non_admin_policies_tied_to_the_active_pool() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert 'create policy "photo_candidate_storage_insert"' not in sql
    assert 'create policy "photo_candidate_storage_select"' not in sql
    # Tampoco se redefine el consumo de las corridas.
    assert "create or replace function public.claim_available_photo" not in sql


def test_migration_revokes_definer_functions_from_public() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for function in (
        "public.excluded_photo_pool_buckets()",
        "public.photo_pool_upload_targets()",
        "public.is_allowed_photo_pool_bucket(text)",
        "public.list_photo_pool_buckets()",
    ):
        assert f"revoke all on function {function} from public;" in sql
        assert f"grant execute on function {function} to authenticated;" in sql
        # Ninguna de las tres se expone a anon.
        assert f"grant execute on function {function} to anon" not in sql


def test_migration_validates_the_json_shape() -> None:
    """Un valor JSON incorrecto no debe romper las operaciones de Storage."""

    sql = MIGRATION.read_text(encoding="utf-8")

    assert "jsonb_typeof(s.value) = 'object'" in sql
    assert "jsonb_typeof(s.value -> 'buckets') = 'array'" in sql
    assert "jsonb_typeof(elem) = 'string'" in sql
    # Y el admin solo ve el inventario si es admin aprobado.
    assert "where public.is_profile_admin(auth.uid())" in sql


# ---------------------------------------------------------------------------
# Panel de carga
# ---------------------------------------------------------------------------

needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="requiere un servidor X para construir widgets"
)


class _StubPoolPolicyService:
    def __init__(self, *, allowed, active, excluded=(), migration_applied=True) -> None:
        self._allowed = list(allowed)
        self._active = active
        self._excluded = list(excluded)
        self._migration_applied = migration_applied

    def list_upload_targets(self):
        from services.photo_pool_policy_service import UploadTarget, UploadTargets

        if not self._migration_applied:
            return UploadTargets(targets=(), migration_applied=False, error="PGRST202")
        targets = [
            UploadTarget(bucket=name, is_active=name == self._active, is_eligible=True)
            for name in self._allowed
        ] + [
            UploadTarget(bucket=name, is_active=False, is_eligible=False, reason="legacy")
            for name in self._excluded
        ]
        return UploadTargets(targets=tuple(targets), migration_applied=True)

    def list_allowed_buckets(self):
        return list(self._allowed)

    def get_policy(self):
        class _Policy:
            bucket = self._active
        return _Policy()


class _StubUploaderService:
    def __init__(self) -> None:
        self.calls = []

    def upload_files(self, files, *, target_bucket, delete_local_on_success=False, progress_callback=None):
        self.calls.append((list(files), target_bucket, delete_local_on_success))
        return []


def _pump(root, widget, timeout_s: float = 4.0) -> None:
    """Bombea el bucle de Tk hasta que el panel tenga los destinos cargados.

    Se usa update() en vez de after()/mainloop(): un after pendiente que se
    dispara despues de destroy() rompe pruebas posteriores.
    """

    import time

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        root.update()
        if widget._upload_targets is not None:
            return
        time.sleep(0.02)


@pytest.fixture()
def panel(tmp_path):
    import customtkinter as ctk

    from ui.uploader.panel import UploaderPanel

    root = ctk.CTk()
    root.geometry("1100x700")
    uploader = _StubUploaderService()
    widget = UploaderPanel(
        root,
        uploader_service=uploader,
        pool_policy_service=_StubPoolPolicyService(
            allowed=["photo-pool", "photo-pool-v2"],
            active="photo-pool",
            excluded=["photos"],
        ),
    )
    widget.pack(fill="both", expand=True)
    root.update()
    _pump(root, widget)
    widget._uploader = uploader
    yield widget
    widget.destroy()
    root.update()
    root.destroy()


@needs_display
def test_selector_has_no_default_and_blocks_upload(panel, tmp_path) -> None:
    assert panel._allowed_pools == ["photo-pool", "photo-pool-v2"]
    # Sin preseleccion: el placeholder obliga a elegir.
    assert panel._selected_pool() is None

    source = tmp_path / "foto.jpg"
    source.write_bytes(b"jpg")
    panel._selected_files = [str(source)]
    panel._start_upload()

    assert panel._is_running is False
    assert panel._uploader.calls == []
    assert "Elige el pool destino" in panel.status_label.cget("text")


@needs_display
def test_choosing_a_pool_passes_it_to_the_service(panel, tmp_path) -> None:
    source = tmp_path / "foto.jpg"
    source.write_bytes(b"jpg")
    panel._selected_files = [str(source)]
    panel.pool_menu.set("photo-pool-v2")
    panel._on_pool_selected("photo-pool-v2")

    panel._start_upload()
    panel.master.update()

    assert panel._uploader.calls
    _files, target_bucket, _delete = panel._uploader.calls[0]
    assert target_bucket == "photo-pool-v2"


@needs_display
def test_ui_distinguishes_active_pool_from_upload_destination(panel) -> None:
    assert "Pool activo" in panel.active_pool_label.cget("text")
    assert "photo-pool" in panel.active_pool_label.cget("text")

    panel.pool_menu.set("photo-pool-v2")
    panel._on_pool_selected("photo-pool-v2")
    hint = panel.pool_hint_label.cget("text")
    assert "NO es el pool activo" in hint
    assert "no las consumiran" in hint

    panel.pool_menu.set("photo-pool")
    panel._on_pool_selected("photo-pool")
    assert "coincide con el pool activo" in panel.pool_hint_label.cget("text")


def _build_panel(root, policy_service):
    from ui.uploader.panel import UploaderPanel

    uploader = _StubUploaderService()
    widget = UploaderPanel(
        root, uploader_service=uploader, pool_policy_service=policy_service
    )
    widget.pack(fill="both", expand=True)
    _pump(root, widget)
    widget._uploader = uploader
    return widget


@needs_display
def test_dropdown_lists_every_eligible_storage_bucket(panel) -> None:
    """El desplegable NO se limita al pool activo."""

    values = panel.pool_menu.cget("values")
    assert "photo-pool" in values
    assert "photo-pool-v2" in values
    assert panel._allowed_pools == ["photo-pool", "photo-pool-v2"]
    # El bucket legacy no es seleccionable, pero se nombra en la pista.
    assert "photos" not in panel._allowed_pools
    assert "photos" in panel.pool_hint_label.cget("text")


@needs_display
def test_missing_migration_shows_a_warning_and_blocks_upload(tmp_path) -> None:
    """Sin migracion no se presenta el pool activo como si fuese la lista."""

    import customtkinter as ctk

    root = ctk.CTk()
    root.geometry("1100x700")
    widget = _build_panel(
        root,
        _StubPoolPolicyService(
            allowed=["photo-pool"], active="photo-pool", migration_applied=False
        ),
    )

    hint = widget.pool_hint_label.cget("text")
    assert "FALTA APLICAR LA MIGRACION" in hint
    assert "020" in hint
    # El pool activo no se ofrece como destino.
    assert widget._allowed_pools == []
    assert "photo-pool" not in widget.pool_menu.cget("values")
    assert widget.pool_menu.cget("state") == "disabled"

    source = tmp_path / "f.jpg"
    source.write_bytes(b"jpg")
    widget._selected_files = [str(source)]
    widget._start_upload()
    assert widget._uploader.calls == []
    widget.destroy()
    root.update()
    root.destroy()
