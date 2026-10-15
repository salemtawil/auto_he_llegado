"""reset_photo_pool must apply --bucket / --prefix to the database pass too.

Before this fix the Storage pass honoured both flags while the DB pass was
hardcoded to ``file_path LIKE 'available/%'`` with no bucket filter, so
``--prefix candidates`` deleted only candidate objects yet still marked every
``available/`` row as discarded.
"""

from __future__ import annotations

import pytest

from scripts.reset_photo_pool import (
    _mark_database_reset,
    build_path_filter,
    count_candidate_rows_in_scope,
    count_photo_rows_in_scope,
    normalize_prefix,
)


class _Query:
    def __init__(self, table: str, log: list[dict]) -> None:
        self.entry = {"table": table, "filters": [], "payload": None, "count": None}
        log.append(self.entry)

    def update(self, payload):
        self.entry["payload"] = payload
        return self

    def select(self, _columns, count=None):
        self.entry["count"] = count
        return self

    def eq(self, column, value):
        self.entry["filters"].append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.entry["filters"].append(("neq", column, value))
        return self

    def like(self, column, value):
        self.entry["filters"].append(("like", column, value))
        return self

    def is_(self, column, value):
        self.entry["filters"].append(("is", column, value))
        return self

    def execute(self):
        class _Response:
            count = 7
            data = [{"id": "1"}]

        return _Response()


class _Client:
    def __init__(self) -> None:
        self.log: list[dict] = []

    def table(self, name: str) -> _Query:
        return _Query(name, self.log)


@pytest.fixture()
def client(monkeypatch):
    stub = _Client()
    monkeypatch.setattr(
        "scripts.reset_photo_pool.create_client", lambda _url, _key: stub
    )
    return stub


def test_normalize_prefix_and_path_filter() -> None:
    assert normalize_prefix("/available/") == "available"
    assert normalize_prefix(" candidates ") == "candidates"
    assert build_path_filter("available") == "available/%"
    assert build_path_filter("/candidates/") == "candidates/%"


@pytest.mark.parametrize("prefix", ["", "   ", "/", "///"])
def test_an_empty_prefix_is_refused_instead_of_matching_the_whole_bucket(prefix: str) -> None:
    with pytest.raises(ValueError):
        build_path_filter(prefix)


def test_custom_prefix_does_not_touch_the_other_prefix(client) -> None:
    _mark_database_reset(
        supabase_url="https://example.supabase.co",
        service_role_key="key",
        buckets=("photo-pool",),
        prefixes=("candidates",),
        scope_bucket=True,
    )

    photo_filters = [
        entry["filters"] for entry in client.log if entry["table"] == "photos"
    ]
    assert photo_filters, "the photos table should still be updated"
    for filters in photo_filters:
        assert ("like", "file_path", "candidates/%") in filters
        assert ("like", "file_path", "available/%") not in filters
        assert ("eq", "storage_bucket", "photo-pool") in filters


def test_custom_bucket_is_applied_to_the_database_filter(client) -> None:
    _mark_database_reset(
        supabase_url="https://example.supabase.co",
        service_role_key="key",
        buckets=("mi-bucket",),
        prefixes=("available",),
        scope_bucket=True,
    )

    for entry in client.log:
        assert ("eq", "storage_bucket", "mi-bucket") in entry["filters"], entry


def test_default_run_does_not_filter_by_bucket(client) -> None:
    """The default run also covers the legacy bucket, where storage_bucket may be NULL."""

    _mark_database_reset(
        supabase_url="https://example.supabase.co",
        service_role_key="key",
        buckets=("photo-pool", "photos"),
        prefixes=("available",),
        scope_bucket=False,
    )

    for entry in client.log:
        assert not any(column == "storage_bucket" for _op, column, _value in entry["filters"])


def test_pending_candidates_outside_the_prefix_are_not_touched(client) -> None:
    _mark_database_reset(
        supabase_url="https://example.supabase.co",
        service_role_key="key",
        buckets=("photo-pool",),
        prefixes=("available",),
        scope_bucket=True,
    )

    candidate_entries = [
        entry for entry in client.log if entry["table"] == "photo_candidates"
    ]
    assert candidate_entries, "candidates should still be updated"
    for entry in candidate_entries:
        assert ("eq", "status", "pending") in entry["filters"]
        assert ("like", "storage_path", "available/%") in entry["filters"], (
            "an unscoped candidate update would delete candidates of another prefix"
        )


def test_scope_counts_are_available_before_any_write(client) -> None:
    photos = count_photo_rows_in_scope(
        client,
        photos_table="photos",
        bucket_name="photo-pool",
        prefix="available",
        scope_bucket=True,
    )
    candidates = count_candidate_rows_in_scope(
        client,
        candidates_table="photo_candidates",
        bucket_name="photo-pool",
        prefix="available",
        scope_bucket=True,
    )

    assert photos == 7
    assert candidates == 7
    for entry in client.log:
        assert entry["payload"] is None, "counting must not write anything"
        assert entry["count"] == "exact"


@pytest.mark.parametrize(
    "prefix",
    [
        "a,storage_bucket.neq.x",
        "available%",
        "available)",
        "available(1)",
        "avail able",
        "available;drop",
    ],
)
def test_a_prefix_that_could_alter_the_postgrest_filter_is_rejected(prefix: str) -> None:
    """--prefix lands in a like() executed with the service-role key."""

    with pytest.raises(ValueError):
        normalize_prefix(prefix)


@pytest.mark.parametrize("prefix", ["available", "candidates", "a/b", "foto-2026_01", "x.y"])
def test_ordinary_prefixes_are_accepted(prefix: str) -> None:
    assert normalize_prefix(prefix) == prefix
