import hashlib
from pathlib import Path
from typing import Tuple


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | Path) -> str:
    with open(path, "rb") as f:
        return hash_bytes(f.read())
