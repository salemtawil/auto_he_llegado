"""Only unambiguous, object-level "missing" may discard or clean a photo row.

Root cause of the worst finding in the 2026-09-22 audit: the classifier matched
the bare tokens "not found" / "does not exist", which Supabase Storage also
returns for *Bucket not found*, for RLS denials and for several 400-class
replies. One misconfigured bucket discarded up to 500 healthy photos per call.
"""

from __future__ import annotations

import socket

import pytest

from core.storage_errors import is_storage_object_missing


class _StorageApiError(Exception):
    """Shape of the storage client's own error type."""


OBJECT_MISSING = [
    '{"statusCode": 404, "error": "not_found", "message": "Object not found"}',
    "Object not found",
    "no such object: available/abc.jpg",
    "Failed to download file from Supabase Storage: statusCode': 404, not_found",
    "The resource was not found",
    "NoSuchKey",
    "file not found: available/abc.jpg",
]

NOT_EVIDENCE_OF_MISSING = [
    # bucket does not exist
    "Bucket not found",
    '{"statusCode": 404, "error": "Bucket not found", "message": "Bucket not found"}',
    "bucket_not_found",
    # auth
    "401 Unauthorized",
    "403 Forbidden",
    "JWT expired",
    "Invalid API key",
    "permission denied for table photos",
    # RLS
    "new row violates row-level security policy for table photos",
    "row level security policy denies access",
    # transport
    "Read timed out after 30s",
    "Connection aborted: RemoteDisconnected",
    "Temporary failure in name resolution",
    "SSL certificate verify failed",
    # server
    "500 Internal Server Error",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Timeout",
    "429 Too Many Requests",
    # quota
    "402 Payment Required: storage quota exceeded",
    # unattributed
    "not found",
    "does not exist",
    "",
]


@pytest.mark.parametrize("message", OBJECT_MISSING)
def test_object_level_missing_is_recognised(message: str) -> None:
    assert is_storage_object_missing(message) is True


@pytest.mark.parametrize("message", NOT_EVIDENCE_OF_MISSING)
def test_ambiguous_errors_never_count_as_missing(message: str) -> None:
    assert is_storage_object_missing(message) is False


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), ConnectionError("reset"), socket.gaierror("dns"), OSError("io")],
)
def test_transport_exception_types_never_count_as_missing(error: Exception) -> None:
    assert is_storage_object_missing(error) is False


def test_a_storage_api_error_is_judged_by_its_body() -> None:
    assert is_storage_object_missing(_StorageApiError("Object not found")) is True
    assert is_storage_object_missing(_StorageApiError("Bucket not found")) is False


def test_both_services_use_the_shared_classifier() -> None:
    from services.photo_cleanup_service import PhotoCleanupService
    from services.process_photo_service import ProcessPhotoService

    assert ProcessPhotoService._is_storage_missing_error(Exception("Bucket not found")) is False
    assert ProcessPhotoService._is_storage_missing_error(Exception("Object not found")) is True
    assert PhotoCleanupService._is_storage_missing_error("Bucket not found") is False
    assert PhotoCleanupService._is_storage_missing_error("Object not found") is True
    assert PhotoCleanupService._is_storage_missing_error("403 Forbidden") is False


# --------------------------------------------------------------------------
# Regression from the review of the first fix: bare substrings meant a digit run
# inside a real object key ("available/1758500123_foto.jpg" contains "500") made
# a genuine 404 look ambiguous, and "rls" matched the word "urls". Both left a
# genuinely missing object un-cleaned forever.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "Object not found: available/1758500123_foto.jpg",
        "Object not found: available/IMG_5029.jpg",
        "Object not found: available/429e8400-e29b-41d4-a716-446655440000.jpg",
        "Object not found: available/402_403_500.jpg",
        '{"statusCode":"404","error":"not_found","message":"Object not found","urls":["https://x"]}',
        "no such object: candidates/504_1.jpg",
    ],
)
def test_digits_and_words_inside_an_object_key_do_not_hide_a_real_404(message: str) -> None:
    assert is_storage_object_missing(message) is True


@pytest.mark.parametrize(
    "message",
    [
        '{"statusCode": "500", "message": "Internal error"}',
        "HTTP 503 upstream",
        "[429] slow down",
        "429 Too Many Requests",
        "statusCode=403",
        '{"status_code": 401}',
    ],
)
def test_real_status_codes_are_still_recognised_as_ambiguous(message: str) -> None:
    assert is_storage_object_missing(message) is False
