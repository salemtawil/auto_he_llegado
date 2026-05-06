from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, TypeVar
from uuid import UUID

from core.exceptions import ValidationError


T = TypeVar("T")

PHONE_DIGITS_PATTERN = re.compile(r"\D+")


def validate_non_empty_string(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError(f"'{field_name}' cannot be empty.")
    return normalized


def validate_optional_string(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def validate_positive_int(value: int, field_name: str) -> int:
    if value <= 0:
        raise ValidationError(f"'{field_name}' must be greater than zero.")
    return value


def validate_limit(value: int, *, maximum: int = 500) -> int:
    if value <= 0 or value > maximum:
        raise ValidationError(
            f"'limit' must be between 1 and {maximum}. Received: {value}."
        )
    return value


def validate_uuid(value: str, field_name: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValidationError(f"'{field_name}' must be a valid UUID.") from exc


def validate_choice(value: T, allowed_values: Iterable[T], field_name: str) -> T:
    if value not in allowed_values:
        allowed = ", ".join(str(item) for item in allowed_values)
        raise ValidationError(f"'{field_name}' must be one of: {allowed}.")
    return value


def strip_phone_number(value: str) -> str:
    return PHONE_DIGITS_PATTERN.sub("", value)


def sanitize_phone_number(value: str) -> str:
    digits = strip_phone_number(value)
    if not digits:
        raise ValidationError("Phone number must contain at least one digit.")
    if len(digits) < 10:
        raise ValidationError("Phone number must contain at least 10 digits.")
    return digits[-10:]


def validate_image_path(path_value: str | Path, field_name: str = "file_path") -> str:
    path = Path(path_value)
    if not path.suffix:
        raise ValidationError(f"'{field_name}' must include a file extension.")
    return str(path)
