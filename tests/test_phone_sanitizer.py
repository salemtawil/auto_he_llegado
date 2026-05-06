from core.exceptions import ValidationError
from core.validators import sanitize_phone_number, strip_phone_number


def test_strip_phone_number_keeps_only_digits() -> None:
    assert strip_phone_number("+58 (412) 123-45-67") == "584121234567"


def test_sanitize_phone_number_keeps_last_10_digits() -> None:
    assert sanitize_phone_number("+1 (809) 555-1234") == "8095551234"


def test_sanitize_phone_number_rejects_values_without_digits() -> None:
    try:
        sanitize_phone_number("+(---)")
    except ValidationError:
        return
    raise AssertionError("sanitize_phone_number should reject values without digits")


def test_sanitize_phone_number_rejects_values_with_less_than_10_digits() -> None:
    try:
        sanitize_phone_number("5551234")
    except ValidationError:
        return
    raise AssertionError("sanitize_phone_number should reject values with less than 10 digits")
