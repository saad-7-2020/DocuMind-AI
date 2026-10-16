"""Upload validation. Uploads are untrusted: the type is decided from the bytes,
never from the filename or the client's Content-Type."""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from charset_normalizer import from_bytes

from documind.domain.errors import EmptyFile, FileTooLarge, UnsupportedFileType
from documind.domain.models import MIME_PDF, MIME_TXT

_KNOWN_BINARY = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF8": "image/gif",
    b"PK\x03\x04": "application/zip",  # DOCX is a ZIP too; DOCX support lands in Phase 3
    b"\x7fELF": "application/x-executable",
    b"MZ": "application/x-msdownload",
}

SNIFF_BYTES = 8192


def sniff_mime(head: bytes) -> str:
    """Return the allowed MIME type for these leading bytes, or raise UnsupportedFileType."""
    if not head:
        raise EmptyFile()
    # PDF spec allows junk before the header; readers accept it within the first 1 KB.
    if b"%PDF-" in head[:1024]:
        return MIME_PDF
    for magic, mime in _KNOWN_BINARY.items():
        if head.startswith(magic):
            raise UnsupportedFileType(f"Detected type '{mime}'; allowed in this version: pdf, txt.")
    if b"\x00" in head:
        raise UnsupportedFileType("Binary content detected; allowed in this version: pdf, txt.")
    best = from_bytes(head).best()
    if best is None:
        raise UnsupportedFileType("Content is neither PDF nor readable text.")
    return MIME_TXT


@dataclass(frozen=True)
class SpooledUpload:
    path: Path
    size_bytes: int
    sha256: str
    mime_type: str


def spool_upload(stream: BinaryIO, max_bytes: int, tmp_dir: Path | None = None) -> SpooledUpload:
    """Copy the upload to a temp file while hashing it and enforcing the size limit.

    Reading in fixed-size blocks means a huge upload is rejected after `max_bytes`,
    without ever holding it in memory.
    """
    digest = hashlib.sha256()
    size = 0
    head = b""
    tmp = tempfile.NamedTemporaryFile(delete=False, dir=tmp_dir, prefix="upload-", suffix=".bin")
    path = Path(tmp.name)
    try:
        with tmp:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > max_bytes:
                    raise FileTooLarge(f"Maximum upload size is {max_bytes} bytes.")
                if len(head) < SNIFF_BYTES:
                    head += block[: SNIFF_BYTES - len(head)]
                digest.update(block)
                tmp.write(block)
        mime = sniff_mime(head)
        return SpooledUpload(path=path, size_bytes=size, sha256=digest.hexdigest(), mime_type=mime)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
