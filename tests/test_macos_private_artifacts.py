import importlib.util
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

spec = importlib.util.spec_from_file_location(
    "private_artifacts", Path(__file__).parents[1] / "packaging/macos/private_artifacts.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_roundtrip_and_tampered_artifact_does_not_replace_destination(tmp_path):
    original = tmp_path / "source.pkg"
    sealed = tmp_path / "source.pkg.enc"
    restored = tmp_path / "restored.pkg"
    original.write_bytes(b"private installer" * 100000)
    key = b"a" * 32
    module.transform(original, sealed, key)
    module.transform(sealed, restored, key, decrypt=True)
    assert restored.read_bytes() == original.read_bytes()
    encrypted = bytearray(sealed.read_bytes())
    encrypted[20] ^= 1
    sealed.write_bytes(encrypted)
    restored.write_bytes(b"existing installer")
    with pytest.raises(InvalidTag):
        module.transform(sealed, restored, key, decrypt=True)
    assert restored.read_bytes() == b"existing installer"
    assert not restored.with_name(restored.name + ".partial").exists()
