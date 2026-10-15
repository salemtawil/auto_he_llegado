"""Strict classification of Supabase Storage errors.

Reading "the object is gone" out of a storage error is destructive: the callers
of this module mark photo rows as DISCARDED or write ``storage_deleted_at``. A
loose match was the root cause of the worst bug found in the 2026-09-22 audit —
the bare tokens ``"not found"`` and ``"does not exist"`` also appear in
*Bucket not found*, in RLS denials and in several 400-class replies, so one
misconfigured bucket discarded up to 500 perfectly good photos per call.

The rule here is: only an unambiguous, object-level "missing" wins. Anything
that could be a bucket, auth, policy, timeout, network or server problem is
treated as "unknown" — the caller must then retry or fail loudly instead of
destroying data.

Everything is matched with word/number boundaries. A first pass at this module
used bare substrings, which had the opposite failure mode: the digits of a real
object key made a genuine 404 look ambiguous (``Object not found:
available/1758500123_foto.jpg`` contains "500"), and ``"rls"`` matched the word
"urls". Both meant a genuinely missing object was never cleaned up.
"""

from __future__ import annotations

import re
import socket

# --------------------------------------------------------------------------
# Ambiguous signals: if any matches, the error is NOT evidence that the object
# is missing, whatever else the message says.
# --------------------------------------------------------------------------

_AMBIGUOUS_PHRASES = (
    # bucket-level
    "bucket not found",
    "bucket_not_found",
    "bucket does not exist",
    "no such bucket",
    "invalid bucket",
    # auth / policy
    "unauthorized",
    "not authorized",
    "forbidden",
    "permission denied",
    "insufficient",
    "violates row-level security",
    "row level security",
    "row-level security",
    "policy",
    "jwt",
    "invalid api key",
    "invalid_api_key",
    "apikey",
    "signature verification",
    # transport / availability
    "timeout",
    "timed out",
    "connection refused",
    "connection reset",
    "connection aborted",
    "connection error",
    "connectionerror",
    "network is unreachable",
    "network error",
    "unreachable",
    "name resolution",
    "temporary failure",
    "temporarily unavailable",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "internal server error",
    "too many requests",
    "rate limit",
    "ssl",
    "certificate",
    # quota
    "quota",
    "payment required",
)

# Short tokens that need a word boundary: "rls" is a substring of "urls".
_AMBIGUOUS_WORDS_RE = re.compile(r"\b(rls|dns)\b")

# HTTP status codes that mean "not a missing object". Matched with digit
# boundaries so a number inside an object key, a timestamp or a UUID cannot
# trigger them.
_AMBIGUOUS_STATUS_RE = re.compile(
    r"(?:"
    r"status(?:_?code)?[\"']?\s*[:=]\s*[\"']?(401|402|403|429|5\d\d)"
    r"|\b(?:http\s+|error\s+)(401|402|403|429|5\d\d)\b"
    r"|[\[(](401|402|403|429|5\d\d)[\])]"
    r"|^\s*(401|402|403|429|5\d\d)\b"
    r")"
)

# --------------------------------------------------------------------------
# Positive signals: unambiguous, object-level "the stored file is not there".
# --------------------------------------------------------------------------

_OBJECT_MISSING_PHRASES = (
    "object not found",
    "no such object",
    "missing object",
    "object_not_found",
    "the resource was not found",
    "key does not exist",
    "file not found",
    "no such file",
    "nosuchkey",
)

# A 404 is object-level evidence once nothing ambiguous is present. Same digit
# boundaries as above.
_NOT_FOUND_STATUS_RE = re.compile(
    r"(?:"
    r"status(?:_?code)?[\"']?\s*[:=]\s*[\"']?404\b"
    r"|\b(?:http\s+|error\s+)404\b"
    r"|[\[(]404[\])]"
    r"|^\s*404\b"
    r")"
)

_NOT_FOUND_WORD_RE = re.compile(r"\bnot_found\b")

# A bare "not found" / "does not exist" needs one of these nearby to count.
_OBJECT_QUALIFIER_RE = re.compile(r"\b(object|file|key|resource|path|photo|image)s?\b")
_BARE_MISSING_RE = re.compile(r"\b(not found|does not exist)\b")

# Exception types that are never evidence of a missing object.
_NEVER_MISSING_TYPES = (TimeoutError, ConnectionError, socket.timeout, socket.gaierror, OSError)


def is_storage_object_missing(error: object) -> bool:
    """True only when the error unambiguously means *this object* is gone.

    Anything else — a missing bucket, an auth or RLS denial, a timeout, a
    network failure, a 5xx — returns False, because acting on it would destroy
    rows whose objects are intact.
    """

    if isinstance(error, _NEVER_MISSING_TYPES) and not _is_storage_api_error(error):
        return False

    text = str(error or "").strip().lower()
    if not text:
        return False

    if any(phrase in text for phrase in _AMBIGUOUS_PHRASES):
        return False
    if _AMBIGUOUS_WORDS_RE.search(text):
        return False
    if _AMBIGUOUS_STATUS_RE.search(text):
        return False

    if any(phrase in text for phrase in _OBJECT_MISSING_PHRASES):
        return True
    if _NOT_FOUND_STATUS_RE.search(text):
        return True
    if _NOT_FOUND_WORD_RE.search(text):
        return True

    if _BARE_MISSING_RE.search(text):
        # "Bucket not found" is already excluded above; still require an
        # object-level word so a bare, unattributed "not found" never counts.
        return bool(_OBJECT_QUALIFIER_RE.search(text))

    return False


def _is_storage_api_error(error: object) -> bool:
    """A storage client error may subclass OSError while carrying a real HTTP body."""

    name = type(error).__name__.lower()
    return "storage" in name or "api" in name or "http" in name
