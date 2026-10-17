"""Blob storage for uploaded files, addressed by content (SHA-256), never by the user's filename.

That rules out path traversal and gives deduplication for free. Two implementations behind one
interface: the local disk (development) and Supabase Storage (production, where the web server's
disk is ephemeral and shared by nothing).

Processing code never assumes a local path: it asks for `open_local(key)`, a context manager that
yields a real file for the duration of the block (the local store returns the file itself; the
Supabase store downloads to a temporary file and removes it afterwards).
"""

from __future__ import annotations

import os
import random
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from documind.domain.errors import StorageError

_KEY_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}$")


def blob_key(sha256: str) -> str:
    return f"{sha256[:2]}/{sha256}"


class BlobStore(Protocol):
    def put(self, sha256: str, source: Path, content_type: str = ...) -> str: ...
    def open_local(self, key: str) -> AbstractContextManager[Path]: ...
    def delete(self, key: str) -> None: ...


class LocalBlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    key_for = staticmethod(blob_key)

    def put(self, sha256: str, source: Path, content_type: str = "application/octet-stream") -> str:
        """Move `source` into the store. If the blob already exists, drop `source`."""
        key = blob_key(sha256)
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

    @contextmanager
    def open_local(self, key: str) -> Iterator[Path]:
        yield self.path(key)

    def delete(self, key: str) -> None:
        p = self.path(key)
        if p.exists():
            os.remove(p)


class SupabaseBlobStore:
    """Supabase Storage through its REST API, authenticated with the server-side service key.

    The bucket must be PRIVATE: files are only ever read back by this server, and users reach
    them through the API's own access checks.
    """

    def __init__(
        self,
        url: str,
        service_key: str,
        bucket: str,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.bucket = bucket
        self.max_retries = max_retries
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=f"{url.rstrip('/')}/storage/v1",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            transport=transport,
        )

    key_for = staticmethod(blob_key)

    def _object_path(self, key: str, prefix: str = "object") -> str:
        if not _KEY_RE.match(key):
            raise ValueError("invalid storage key")
        return f"/{prefix}/{quote(self.bucket, safe='')}/{key}"

    def _send(self, make_request: Callable[[], httpx.Response], action: str) -> httpx.Response:
        """Run a request with bounded retries on timeouts, network errors and 5xx/429."""
        last = f"{action} failed"
        for attempt in range(1, self.max_retries + 1):
            try:
                response = make_request()
                if response.status_code < 500 and response.status_code != 429:
                    return response
                last = f"{action}: storage returned HTTP {response.status_code}"
            except httpx.TimeoutException:
                last = f"{action}: storage timed out"
            except httpx.TransportError:
                last = f"{action}: network error talking to storage"
            if attempt < self.max_retries:
                self._sleep(1.0 * 2 ** (attempt - 1) * (0.5 + random.random()))
        raise StorageError(last)

    def put(self, sha256: str, source: Path, content_type: str = "application/octet-stream") -> str:
        key = blob_key(sha256)
        size = source.stat().st_size

        def upload() -> httpx.Response:
            def chunks() -> Iterator[bytes]:
                with source.open("rb") as f:
                    while block := f.read(1024 * 1024):
                        yield block

            # Explicit Content-Length: stream from disk instead of loading the file into memory,
            # without falling back to chunked transfer encoding.
            return self._client.post(
                self._object_path(key),
                content=chunks(),
                headers={"Content-Type": content_type, "Content-Length": str(size), "x-upsert": "true"},
            )

        response = self._send(upload, "upload")
        if response.status_code not in (200, 201):
            raise StorageError(f"upload: storage returned HTTP {response.status_code}")
        return key

    @contextmanager
    def open_local(self, key: str) -> Iterator[Path]:
        tmp = Path(tempfile.NamedTemporaryFile(delete=False, prefix="blob-", suffix=".bin").name)
        try:
            def download() -> httpx.Response:
                return self._client.get(self._object_path(key, "object/authenticated"))

            response = self._send(download, "download")
            if response.status_code != 200:
                raise StorageError(f"download: storage returned HTTP {response.status_code}")
            tmp.write_bytes(response.content)
            yield tmp
        finally:
            tmp.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        # Same call the official client uses to remove objects (bulk form with a list of paths).
        def remove() -> httpx.Response:
            return self._client.request(
                "DELETE", f"/object/{quote(self.bucket, safe='')}", json={"prefixes": [key]}
            )

        response = self._send(remove, "delete")
        if response.status_code not in (200, 204, 404):
            raise StorageError(f"delete: storage returned HTTP {response.status_code}")
