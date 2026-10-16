"""Content-addressed blob storage. Files are stored under their SHA-256, never under
the user's filename, which rules out path traversal and gives deduplication for free."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Protocol

_KEY_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}$")


class BlobStore(Protocol):
    def put(self, sha256: str, source: Path) -> str: ...
    def path(self, key: str) -> Path: ...
    def delete(self, key: str) -> None: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key_for(sha256: str) -> str:
        return f"{sha256[:2]}/{sha256}"

    def put(self, sha256: str, source: Path) -> str:
        """Move `source` into the store. If the blob already exists, drop `source`."""
        key = self.key_for(sha256)
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            source.unlink(missing_ok=True)
        else:
            shutil.move(str(source), dest)
        return key

    def path(self, key: str) -> Path:
        if not _KEY_RE.match(key):
            raise ValueError("invalid storage key")
        return self.root / key

    def delete(self, key: str) -> None:
        p = self.path(key)
        if p.exists():
            os.remove(p)
