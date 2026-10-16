import hashlib
import io
from pathlib import Path

import pytest

from documind.domain.errors import EmptyFile, FileTooLarge, UnsupportedFileType
from documind.domain.models import MIME_PDF, MIME_TXT
from documind.ingestion.extractors import split_logical_pages
from documind.ingestion.validation import sniff_mime, spool_upload


def test_pdf_detected_by_magic_bytes():
    assert sniff_mime(b"%PDF-1.7\n...") == MIME_PDF


@pytest.mark.parametrize("head", [
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,   # an image renamed to .pdf
    b"PK\x03\x04" + b"\x00" * 20,          # zip / docx (Phase 3)
    b"MZ\x90\x00",                          # Windows executable
    b"abc\x00def",                          # binary with NUL bytes
])
def test_binary_types_rejected(head: bytes):
    with pytest.raises(UnsupportedFileType):
        sniff_mime(head)


def test_text_in_utf8_and_latin1_accepted():
    assert sniff_mime("Résiliation du contrat : préavis de trente jours.".encode()) == MIME_TXT
    assert sniff_mime("Résiliation du contrat : préavis de trente jours.".encode("latin-1")) == MIME_TXT


def test_empty_rejected():
    with pytest.raises(EmptyFile):
        sniff_mime(b"")


def test_spool_hashes_and_enforces_limit(tmp_path: Path):
    data = b"%PDF-1.4\n" + b"x" * 5000
    up = spool_upload(io.BytesIO(data), max_bytes=10_000, tmp_dir=tmp_path)
    assert up.sha256 == hashlib.sha256(data).hexdigest()
    assert up.size_bytes == len(data) and up.path.read_bytes() == data

    with pytest.raises(FileTooLarge):
        spool_upload(io.BytesIO(data), max_bytes=1000, tmp_dir=tmp_path)
    assert list(tmp_path.iterdir()) == [up.path], "rejected upload must not leave a temp file"


def test_txt_logical_pages_lose_no_text():
    text = "\n\n".join(f"Paragraphe {i}. " + "mot " * 100 for i in range(20))
    parts = split_logical_pages(text, target_chars=1500)
    assert len(parts) > 1 and "".join(parts) == text
    assert split_logical_pages("page un\fpage deux") == ["page un", "page deux"]
