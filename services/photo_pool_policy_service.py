from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from storage.supabase_client import SupabaseClientProvider


@dataclass(frozen=True)
class UploadTarget:
    """Un bucket real de Storage visto como posible destino de carga."""

    bucket: str
    is_active: bool = False
    is_eligible: bool = True
    reason: str | None = None


@dataclass(frozen=True)
class UploadTargets:
    """Resultado de consultar los destinos.

    ``migration_applied=False`` significa que no se pudo saber cuales son los
    buckets reales porque falta la migracion 020: la UI debe avisar, no rellenar
    el hueco con el pool activo.
    """

    targets: tuple[UploadTarget, ...] = ()
    migration_applied: bool = True
    error: str | None = None

    @property
    def eligible(self) -> tuple[UploadTarget, ...]:
        return tuple(target for target in self.targets if target.is_eligible)


@dataclass(frozen=True)
class PhotoPoolPolicy:
    bucket: str
    available_prefix: str = "available"
    candidates_prefix: str = "candidates"
    source: str = "local"


class PhotoPoolPolicyService:
    _DEFAULT_AVAILABLE_PREFIX = "available"
    _DEFAULT_CANDIDATES_PREFIX = "candidates"

    def __init__(
        self,
        client_provider: SupabaseClientProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client_provider = client_provider or SupabaseClientProvider(self._settings)

    def get_policy(self) -> PhotoPoolPolicy:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("get_photo_pool_policy", {})
            )
        except Exception:
            return self._fallback_policy()
        row = dict(rows[0]) if rows else {}
        bucket = self._normalize_bucket(row.get("bucket"))
        if not bucket:
            return self._fallback_policy()
        return PhotoPoolPolicy(
            bucket=bucket,
            available_prefix=self._normalize_prefix(row.get("available_prefix"), self._DEFAULT_AVAILABLE_PREFIX),
            candidates_prefix=self._normalize_prefix(row.get("candidates_prefix"), self._DEFAULT_CANDIDATES_PREFIX),
            source="supabase",
        )

    def update_policy(
        self,
        *,
        bucket: str,
        available_prefix: str = _DEFAULT_AVAILABLE_PREFIX,
        candidates_prefix: str = _DEFAULT_CANDIDATES_PREFIX,
    ) -> PhotoPoolPolicy:
        normalized_bucket = self._normalize_bucket(bucket)
        if not normalized_bucket:
            raise ValueError("Ingresa un bucket valido para el pool.")
        normalized_available = self._normalize_prefix(available_prefix, self._DEFAULT_AVAILABLE_PREFIX)
        normalized_candidates = self._normalize_prefix(candidates_prefix, self._DEFAULT_CANDIDATES_PREFIX)
        payload = {
            "key": "photo_pool",
            "value": {
                "bucket": normalized_bucket,
                "available_prefix": normalized_available,
                "candidates_prefix": normalized_candidates,
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        rows = self._client_provider.execute(
            self._client_provider.client.table("app_settings").upsert(payload)
        )
        if not rows:
            raise RuntimeError("No se actualizo la politica del pool de fotos.")
        return PhotoPoolPolicy(
            bucket=normalized_bucket,
            available_prefix=normalized_available,
            candidates_prefix=normalized_candidates,
            source="supabase",
        )

    def list_upload_targets(self) -> UploadTargets:
        """Destinos de carga: el inventario REAL de Storage, menos exclusiones.

        Nunca inventa la lista ni la deduce del pool activo. Si el RPC no
        existe todavia (migracion 020 sin aplicar), lo dice explicitamente con
        ``migration_applied=False`` para que la UI avise en vez de presentar el
        pool activo como si fuese la lista completa.
        """

        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("photo_pool_upload_targets", {})
            )
        except Exception as exc:  # noqa: BLE001
            return UploadTargets(
                targets=(),
                migration_applied=self._looks_applied(exc),
                error=str(exc),
            )
        if not isinstance(rows, list):
            return UploadTargets(
                targets=(),
                migration_applied=False,
                error="Respuesta inesperada de photo_pool_upload_targets.",
            )
        targets = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = self._normalize_bucket(row.get("bucket") or row.get("id"))
            if not name:
                continue
            targets.append(
                UploadTarget(
                    bucket=name,
                    is_active=bool(row.get("is_active")),
                    is_eligible=bool(row.get("is_eligible")),
                    reason=(row.get("reason") or None),
                )
            )
        return UploadTargets(targets=tuple(targets), migration_applied=True, error=None)

    @staticmethod
    def _looks_applied(exc: Exception) -> bool:
        """Distingue 'la funcion no existe' de un fallo de red o de permisos.

        PostgREST devuelve PGRST202 / 404 cuando la funcion no esta en el
        esquema. Cualquier otro error significa que la migracion podria estar
        aplicada y el problema es otro, asi que no se afirma lo contrario.
        """

        message = str(exc or "").lower()
        missing_markers = (
            "pgrst202",
            "could not find the function",
            "does not exist",
            "no existe",
        )
        return not any(marker in message for marker in missing_markers)

    def list_allowed_buckets(self) -> list[str]:
        """Solo los destinos aptos. Lista vacia si la migracion falta."""

        return [
            target.bucket
            for target in self.list_upload_targets().targets
            if target.is_eligible
        ]

    def is_allowed_bucket(self, bucket: str) -> bool:
        normalized = self._normalize_bucket(bucket)
        if not normalized:
            return False
        return normalized in self.list_allowed_buckets()

    def list_buckets(self) -> list[str]:
        buckets = self._list_buckets_from_rpc()
        if buckets:
            return buckets
        buckets = self._list_buckets_from_storage_api()
        fallback = [
            self._settings.supabase_storage_bucket,
            *self._settings.supabase_legacy_storage_buckets,
        ]
        return self._unique_bucket_names([*buckets, *fallback])

    def _fallback_policy(self) -> PhotoPoolPolicy:
        return PhotoPoolPolicy(
            bucket=self._normalize_bucket(self._settings.supabase_storage_bucket) or "photo-pool",
            available_prefix=self._DEFAULT_AVAILABLE_PREFIX,
            candidates_prefix=self._DEFAULT_CANDIDATES_PREFIX,
            source="local",
        )

    def _list_buckets_from_rpc(self) -> list[str]:
        try:
            rows = self._client_provider.execute(
                self._client_provider.client.rpc("list_photo_pool_buckets", {})
            )
        except Exception:
            return []
        return self._unique_bucket_names(row.get("bucket") or row.get("id") for row in rows)

    def _list_buckets_from_storage_api(self) -> list[str]:
        try:
            buckets = self._client_provider.list_buckets()
        except Exception:
            return []
        return self._unique_bucket_names(self._bucket_name_from_payload(bucket) for bucket in buckets)

    @staticmethod
    def _normalize_bucket(value) -> str:
        return str(value or "").strip().strip("/")

    @staticmethod
    def _normalize_prefix(value, default: str) -> str:
        normalized = str(value or "").strip().strip("/")
        return normalized or default

    @staticmethod
    def _bucket_name_from_payload(payload: dict[str, Any]) -> str:
        return str(payload.get("id") or payload.get("name") or "").strip()

    @classmethod
    def _unique_bucket_names(cls, bucket_names) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for bucket_name in bucket_names:
            normalized = cls._normalize_bucket(bucket_name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
