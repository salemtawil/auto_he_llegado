from __future__ import annotations

from enum import StrEnum


class PhotoStatus(StrEnum):
    PENDING = "pending"
    AVAILABLE = "available"
    RESERVED = "reserved"
    CONSUMED = "consumed"
    UPLOADED = "uploaded"
    FAILED = "failed"
    ARCHIVED = "archived"


class ProcessStatus(StrEnum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class ProcessLogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
