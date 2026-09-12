"""Encrypt CI artifacts before upload; decrypt only on the release owner's machine."""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def transform(source: Path, destination: Path, key: bytes, *, decrypt: bool = False) -> None:
    temporary = destination.with_name(destination.name + ".partial")
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            if decrypt:
                nonce = reader.read(12)
                remaining = source.stat().st_size - 28
                if remaining < 0:
                    raise ValueError("Invalid encrypted artifact")
                reader.seek(-16, 2)
                tag = reader.read(16)
                reader.seek(12)
                context = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
            else:
                nonce = os.urandom(12)
                writer.write(nonce)
                remaining = source.stat().st_size
                context = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
            while remaining:
                block = reader.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("Truncated artifact")
                writer.write(context.update(block))
                remaining -= len(block)
            writer.write(context.finalize())
            if not decrypt:
                writer.write(context.tag)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--decrypt", action="store_true")
    args = parser.parse_args()
    transform(args.source, args.destination, base64.b64decode(os.environ["MACOS_ARTIFACT_KEY_B64"]), decrypt=args.decrypt)
