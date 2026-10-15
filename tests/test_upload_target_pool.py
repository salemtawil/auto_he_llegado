"""Seleccion explicita del pool destino en la carga de fotos.

Cubre: ambos destinos permitidos, rechazo de 'photos' (legacy) y de buckets
fuera de la lista blanca, cambio del pool activo durante un lote, rollback en
el bucket correcto y ausencia de consumo desde un pool inactivo.
"""

from pathlib import Path

import pytest

from services.uploader_service import UploaderService
from tests.test_uploader_service import (
    StubClientProvider,
    StubPhotosRepository,
    StubPoolPolicyService,
    build_settings,
)


ALLOWED = ["photo-pool", "photo-pool-v2"]


def build_service(tmp_path, *, policy_service, client_provider=None, repository=None):
    return UploaderService(
        photos_repository=repository or StubPhotosRepository(),
        client_provider=client_provider or StubClientProvider(),
        pool_policy_service=policy_service,
        settings=build_settings(tmp_path),
    )


def make_source(tmp_path, name: str = "foto.jpg") -> Path:
    source = tmp_path / name
    source.write_bytes(b"jpg-data")
    return source


@pytest.mark.parametrize("target", ALLOWED)
def test_upload_uses_the_chosen_bucket(tmp_path, target) -> None:
    source = make_source(tmp_path)
    client_provider = StubClientProvider()
    repository = StubPhotosRepository()
    service = build_service(
        tmp_path,
        policy_service=StubPoolPolicyService(active="photo-pool"),
        client_provider=client_provider,
        repository=repository,
    )

    result = service.upload_file(source, target_bucket=target)

    assert result.success is True
    assert result.storage_bucket == target
    assert [call[0] for call in client_provider.upload_calls] == [target]
    assert repository.created_photos[0].storage_bucket == target


def test_legacy_photos_bucket_is_rejected(tmp_path) -> None:
    source = make_source(tmp_path)
    client_provider = StubClientProvider()
    service = build_service(
        tmp_path,
        policy_service=StubPoolPolicyService(),
        client_provider=client_provider,
    )

    with pytest.raises(ValueError) as excinfo:
        service.upload_files([source], target_bucket="photos")

    assert "no esta permitido" in str(excinfo.value)
    assert client_provider.upload_calls == []


@pytest.mark.parametrize("target", ["", None, "otro-bucket", "photo-pool-v3"])
def test_missing_or_unlisted_bucket_aborts_before_uploading(tmp_path, target) -> None:
    source = make_source(tmp_path)
    client_provider = StubClientProvider()
    service = build_service(
        tmp_path,
        policy_service=StubPoolPolicyService(),
        client_provider=client_provider,
    )

    with pytest.raises(ValueError):
        service.upload_files([source], target_bucket=target)

    # Nada llego a Storage: la validacion ocurre antes de subir el primer archivo.
    assert client_provider.upload_calls == []


def test_active_pool_change_midway_does_not_move_the_batch(tmp_path) -> None:
    """El bucket queda congelado al inicio del lote."""

    sources = [make_source(tmp_path, f"foto_{index}.jpg") for index in range(3)]
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository()
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )

    original_upload = client_provider.upload_binary

    def upload_and_flip(**kwargs):
        # Otro administrador cambia el pool activo tras el primer archivo.
        policy_service.active = "photo-pool-v2"
        return original_upload(**kwargs)

    client_provider.upload_binary = upload_and_flip

    results = service.upload_files(sources, target_bucket="photo-pool")

    assert all(item.success for item in results)
    assert {call[0] for call in client_provider.upload_calls} == {"photo-pool"}
    assert {item.storage_bucket for item in results} == {"photo-pool"}
    assert {photo.storage_bucket for photo in repository.bulk_created_photos[0]} == {
        "photo-pool"
    }


def test_rollback_removes_from_the_chosen_bucket(tmp_path) -> None:
    source = make_source(tmp_path)
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository(create_error=RuntimeError("db caida"))
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )

    result = service.upload_file(source, target_bucket="photo-pool-v2")

    assert result.success is False
    assert result.database_error == "db caida"
    # El rollback borra del bucket al que se subio, no del pool activo.
    assert [call[0] for call in client_provider.remove_calls] == ["photo-pool-v2"]


def test_rollback_ignores_an_active_pool_change(tmp_path) -> None:
    source = make_source(tmp_path)
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository(create_error=RuntimeError("db caida"))
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )
    policy_service.active = "photo-pool-v2"

    result = service.upload_file(source, target_bucket="photo-pool")

    assert result.success is False
    assert [call[0] for call in client_provider.remove_calls] == ["photo-pool"]


def test_upload_to_inactive_pool_leaves_the_active_pool_untouched(tmp_path) -> None:
    source = make_source(tmp_path)
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository()
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )

    service.upload_files([source], target_bucket="photo-pool-v2")

    # El pool activo no cambia por subir a otro pool...
    assert policy_service.active == "photo-pool"
    # ...y la fila queda marcada con el pool inactivo, que es lo que impide que
    # claim_available_photo (filtrado por el bucket activo) la reclame.
    photos = repository.bulk_created_photos[0]
    assert {photo.storage_bucket for photo in photos} == {"photo-pool-v2"}
    assert "photo-pool" not in {photo.storage_bucket for photo in photos}


def test_the_active_pool_does_not_restrict_the_destinations(tmp_path) -> None:
    """Se puede subir a un bucket que no es el activo, y a la inversa."""

    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    service = build_service(
        tmp_path, policy_service=policy_service, client_provider=client_provider
    )

    service.upload_file(make_source(tmp_path, "a.jpg"), target_bucket="photo-pool-v2")
    policy_service.active = "photo-pool-v2"
    service.upload_file(make_source(tmp_path, "b.jpg"), target_bucket="photo-pool")

    assert [call[0] for call in client_provider.upload_calls] == [
        "photo-pool-v2",
        "photo-pool",
    ]


def test_destination_persists_across_a_multi_flush_batch(tmp_path) -> None:
    """El destino sobrevive a varios vaciados del lote de inserts."""

    sources = [make_source(tmp_path, f"f{i}.jpg") for i in range(60)]
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository()
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )

    results = service.upload_files(sources, target_bucket="photo-pool-v2")

    # _DB_BATCH_SIZE es 25, asi que hubo mas de un flush.
    assert len(repository.bulk_created_photos) >= 2
    assert {call[0] for call in client_provider.upload_calls} == {"photo-pool-v2"}
    assert {item.storage_bucket for item in results} == {"photo-pool-v2"}
    for batch in repository.bulk_created_photos:
        assert {photo.storage_bucket for photo in batch} == {"photo-pool-v2"}


def test_rollback_in_a_later_flush_uses_the_frozen_bucket(tmp_path) -> None:
    sources = [make_source(tmp_path, f"g{i}.jpg") for i in range(30)]
    policy_service = StubPoolPolicyService(active="photo-pool")
    client_provider = StubClientProvider()
    repository = StubPhotosRepository(create_error=RuntimeError("db caida"))
    service = build_service(
        tmp_path,
        policy_service=policy_service,
        client_provider=client_provider,
        repository=repository,
    )
    policy_service.active = "photo-pool"

    service.upload_files(sources, target_bucket="photo-pool-v2")

    assert client_provider.remove_calls
    assert {call[0] for call in client_provider.remove_calls} == {"photo-pool-v2"}
