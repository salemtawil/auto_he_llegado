from __future__ import annotations

from core.validators import validate_image_path


def test_validate_image_path_keeps_storage_separator_forward_slash() -> None:
    assert validate_image_path(r"available\photo.jpg") == "available/photo.jpg"
