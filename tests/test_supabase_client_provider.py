from __future__ import annotations

import base64
import json
from types import SimpleNamespace

from services.auth_context import AuthSession, get_current_session, set_current_session
from storage.supabase_client import SupabaseClientProvider


class _Settings:
    supabase_url = "https://example.supabase.co"
    supabase_key = "anon-key"

    def require_supabase(self) -> None:
        return None


class _ExplodingAuth:
    def set_session(self, *_args, **_kwargs) -> None:
        raise AssertionError("set_session must not be called for cached app sessions")


class _FakeClient:
    def __init__(self, auth=None) -> None:
        self.auth = auth or _ExplodingAuth()
        self.options = SimpleNamespace(headers={})
        self._postgrest = object()
        self._storage = object()
        self._functions = object()


class _FakeStorageBucket:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def upload(self, *, path, file, file_options):
        self._sink.setdefault("upload_calls", []).append((path, file, file_options))
        if len(self._sink["upload_calls"]) == 1:
            raise RuntimeError(
                "{'statusCode': 403, 'error': 'Unauthorized', "
                "'message': 'exp claim timestamp check failed'}"
            )
        return {"path": path}


class _SuccessfulStorageBucket:
    def __init__(self, sink: dict) -> None:
        self._sink = sink

    def upload(self, *, path, file, file_options):
        self._sink.setdefault("upload_calls", []).append((path, file, file_options))
        return {"path": path}


class _FakeStorage:
    def __init__(self, sink: dict, *, fail_first_upload: bool = True) -> None:
        self._sink = sink
        self._fail_first_upload = fail_first_upload

    def from_(self, bucket_name: str):
        self._sink.setdefault("bucket_calls", []).append(bucket_name)
        if not self._fail_first_upload:
            return _SuccessfulStorageBucket(self._sink)
        return _FakeStorageBucket(self._sink)


def test_provider_uses_access_token_header_without_consuming_refresh_token(monkeypatch) -> None:
    captured = {}

    def fake_create_client(url, key, options=None):
        captured["url"] = url
        captured["key"] = key
        captured["options"] = options
        return _FakeClient()

    set_current_session(
        AuthSession(
            user_id="user-1",
            email="user@example.com",
            access_token="access-token",
            refresh_token="refresh-token",
        )
    )
    monkeypatch.setattr("storage.supabase_client.create_client", fake_create_client)

    try:
        client = SupabaseClientProvider(_Settings()).client
    finally:
        set_current_session(None)

    assert isinstance(client, _FakeClient)
    assert captured["url"] == _Settings.supabase_url
    assert captured["key"] == _Settings.supabase_key
    assert captured["options"].headers["Authorization"] == "Bearer access-token"
    assert captured["options"].auto_refresh_token is False
    assert captured["options"].persist_session is False


class _RefreshingAuth:
    def __init__(self) -> None:
        self._headers = {}
        self.calls: list[str] = []

    def refresh_session(self, refresh_token: str):
        self.calls.append(refresh_token)
        return SimpleNamespace(
            session=SimpleNamespace(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
            )
        )


class _ExpiringOperation:
    def __init__(self) -> None:
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("{'message': 'JWT expired', 'code': 'PGRST303'}")
        return SimpleNamespace(data=[{"ok": True}])


class _FailingOperation:
    def execute(self):
        raise RuntimeError("{'message': 'JWT expired', 'code': 'PGRST303'}")


class _SuccessfulOperation:
    def execute(self):
        return SimpleNamespace(data=[{"ok": True}])


def _fake_jwt(*, exp: int) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


def test_execute_response_refreshes_expired_jwt_and_retries(monkeypatch) -> None:
    auth = _RefreshingAuth()

    def fake_create_client(_url, _key, options=None):
        client = _FakeClient(auth)
        client.options.headers.update(getattr(options, "headers", {}) if options else {})
        return client

    set_current_session(
        AuthSession(
            user_id="user-1",
            email="user@example.com",
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            role="admin",
        )
    )
    monkeypatch.setattr("storage.supabase_client.create_client", fake_create_client)

    try:
        provider = SupabaseClientProvider(_Settings())
        operation = _ExpiringOperation()
        response = provider.execute_response(operation)
        current_session = get_current_session()
    finally:
        set_current_session(None)

    assert response.data == [{"ok": True}]
    assert operation.calls == 2
    assert auth.calls == ["old-refresh-token"]
    assert current_session is not None
    assert current_session.access_token == "new-access-token"
    assert current_session.refresh_token == "new-refresh-token"
    assert current_session.role == "admin"
    assert provider.client.options.headers["Authorization"] == "Bearer new-access-token"


def test_execute_response_factory_rebuilds_operation_after_refresh(monkeypatch) -> None:
    auth = _RefreshingAuth()
    operations = [_FailingOperation(), _SuccessfulOperation()]
    factory_calls: list[int] = []

    def fake_create_client(_url, _key, options=None):
        client = _FakeClient(auth)
        client.options.headers.update(getattr(options, "headers", {}) if options else {})
        return client

    set_current_session(
        AuthSession(
            user_id="user-1",
            email="user@example.com",
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            role="admin",
        )
    )
    monkeypatch.setattr("storage.supabase_client.create_client", fake_create_client)

    try:
        provider = SupabaseClientProvider(_Settings())
        response = provider.execute_response_factory(lambda: factory_calls.append(1) or operations.pop(0))
        current_session = get_current_session()
    finally:
        set_current_session(None)

    assert response.data == [{"ok": True}]
    assert len(factory_calls) == 2
    assert auth.calls == ["old-refresh-token"]
    assert current_session is not None
    assert current_session.access_token == "new-access-token"


def test_storage_upload_refreshes_expired_jwt_and_retries(monkeypatch) -> None:
    auth = _RefreshingAuth()
    sink: dict = {}

    def fake_create_client(_url, _key, options=None):
        client = _FakeClient(auth)
        client.options.headers.update(getattr(options, "headers", {}) if options else {})
        client.storage = _FakeStorage(sink)
        return client

    set_current_session(
        AuthSession(
            user_id="user-1",
            email="user@example.com",
            access_token="old-access-token",
            refresh_token="old-refresh-token",
            role="admin",
        )
    )
    monkeypatch.setattr("storage.supabase_client.create_client", fake_create_client)

    try:
        provider = SupabaseClientProvider(_Settings())
        provider.upload_binary(
            bucket_name="photo-pool",
            storage_path="available/example.jpg",
            content=b"jpg-data",
        )
        current_session = get_current_session()
    finally:
        set_current_session(None)

    assert sink["bucket_calls"] == ["photo-pool", "photo-pool"]
    assert sink["upload_calls"] == [
        (
            "available/example.jpg",
            b"jpg-data",
            {"content-type": "image/jpeg", "upsert": False},
        ),
        (
            "available/example.jpg",
            b"jpg-data",
            {"content-type": "image/jpeg", "upsert": False},
        ),
    ]
    assert auth.calls == ["old-refresh-token"]
    assert current_session is not None
    assert current_session.access_token == "new-access-token"
    assert provider.client.options.headers["Authorization"] == "Bearer new-access-token"


def test_storage_upload_refreshes_nearly_expired_jwt_before_upload(monkeypatch) -> None:
    auth = _RefreshingAuth()
    sink: dict = {}

    def fake_create_client(_url, _key, options=None):
        client = _FakeClient(auth)
        client.options.headers.update(getattr(options, "headers", {}) if options else {})
        client.storage = _FakeStorage(sink, fail_first_upload=False)
        return client

    monkeypatch.setattr("storage.supabase_client.time.time", lambda: 1_000.0)
    set_current_session(
        AuthSession(
            user_id="user-1",
            email="user@example.com",
            access_token=_fake_jwt(exp=1_120),
            refresh_token="old-refresh-token",
            role="admin",
        )
    )
    monkeypatch.setattr("storage.supabase_client.create_client", fake_create_client)

    try:
        provider = SupabaseClientProvider(_Settings())
        provider.upload_binary(
            bucket_name="photo-pool",
            storage_path="available/example.jpg",
            content=b"jpg-data",
        )
        current_session = get_current_session()
    finally:
        set_current_session(None)

    assert sink["bucket_calls"] == ["photo-pool"]
    assert len(sink["upload_calls"]) == 1
    assert auth.calls == ["old-refresh-token"]
    assert current_session is not None
    assert current_session.access_token == "new-access-token"
    assert provider.client.options.headers["Authorization"] == "Bearer new-access-token"
