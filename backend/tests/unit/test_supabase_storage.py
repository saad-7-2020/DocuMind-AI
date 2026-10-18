import hashlib
import json
from pathlib import Path

import httpx
import pytest

from documind.domain.errors import StorageError
from documind.ingestion.storage import SupabaseBlobStore, blob_key

SERVICE_KEY = "service-role-key"
SHA = hashlib.sha256(b"contenu du fichier").hexdigest()


class FakeSupabase:
    """In-memory stand-in for the Supabase Storage REST API (private bucket 'documents')."""

    def __init__(self, fail_first: int = 0, fail_status: int = 503, valid_key: str = SERVICE_KEY,
                 require_bearer: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.fail_first, self.fail_status = fail_first, fail_status
        self.valid_key, self.require_bearer = valid_key, require_bearer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("apikey") != self.valid_key:
            return httpx.Response(401, json={"error": "Unauthorized"})
        if self.require_bearer and request.headers.get("authorization") != f"Bearer {self.valid_key}":
            return httpx.Response(401, json={"error": "Unauthorized"})
        if self.fail_first > 0:
            self.fail_first -= 1
            return httpx.Response(self.fail_status)
        path, base = request.url.path, "/storage/v1/object"
        if request.method == "POST" and path.startswith(f"{base}/documents/"):
            self.objects[path.removeprefix(f"{base}/documents/")] = request.content
            return httpx.Response(200, json={"Key": path})
        if request.method == "GET" and path.startswith(f"{base}/authenticated/documents/"):
            key = path.removeprefix(f"{base}/authenticated/documents/")
            if key not in self.objects:
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, content=self.objects[key])
        if request.method == "DELETE" and path == f"{base}/documents":
            for prefix in json.loads(request.content)["prefixes"]:
                self.objects.pop(prefix, None)
            return httpx.Response(200, json=[])
        return httpx.Response(400)


def make(fake: FakeSupabase, key: str = SERVICE_KEY, **kw) -> SupabaseBlobStore:
    return SupabaseBlobStore(
        "https://abc123.supabase.co/", key, "documents",
        transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw,
    )


def test_upload_download_delete_roundtrip(tmp_path: Path):
    fake = FakeSupabase()
    store = make(fake)
    src = tmp_path / "upload.bin"
    src.write_bytes(b"contenu du fichier")

    key = store.put(SHA, src, "application/pdf")
    assert key == blob_key(SHA) and fake.objects[key] == b"contenu du fichier"

    post = fake.requests[0]
    assert str(post.url) == f"https://abc123.supabase.co/storage/v1/object/documents/{key}"
    assert post.headers["x-upsert"] == "true" and post.headers["content-type"] == "application/pdf"
    assert post.headers["content-length"] == str(len(b"contenu du fichier")), "streamed, not chunked"
    assert "transfer-encoding" not in post.headers

    with store.open_local(key) as local:
        assert local.read_bytes() == b"contenu du fichier"
    assert not local.exists(), "temporary download is removed after use"

    store.delete(key)
    assert key not in fake.objects
    store.delete(key)  # deleting something already gone is not an error


def test_download_of_a_missing_object_raises_and_cleans_up():
    store = make(FakeSupabase())
    with pytest.raises(StorageError), store.open_local(blob_key(SHA)):
        pass


def test_transient_server_errors_are_retried(tmp_path: Path):
    fake = FakeSupabase(fail_first=2)
    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    assert make(fake, max_retries=3).put(SHA, src) == blob_key(SHA)
    assert len(fake.requests) == 3


def test_persistent_failure_raises_storage_error_after_bounded_retries(tmp_path: Path):
    fake = FakeSupabase(fail_first=99)
    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    with pytest.raises(StorageError):
        make(fake, max_retries=3).put(SHA, src)
    assert len(fake.requests) == 3


def test_keys_are_validated_so_user_input_cannot_choose_a_path():
    store = make(FakeSupabase())
    for bad in ("../../etc/passwd", "ab/../cd", "ab/" + "z" * 64, ""):
        with pytest.raises(ValueError), store.open_local(bad):
            pass


NEW_KEY = "sb_secret_Abc123Def456Ghi789"


def uploaded(store: SupabaseBlobStore, tmp_path: Path) -> str:
    src = tmp_path / "f.bin"
    src.write_bytes(b"x")
    return store.put(SHA, src)


def test_legacy_jwt_style_key_is_sent_in_both_headers(tmp_path: Path):
    fake = FakeSupabase(valid_key="eyJlegacy.jwt.key", require_bearer=True)
    uploaded(make(fake, key="eyJlegacy.jwt.key"), tmp_path)
    assert len(fake.requests) == 1, "no wasted round trip for legacy keys"
    assert fake.requests[0].headers["authorization"] == "Bearer eyJlegacy.jwt.key"


def test_new_sb_secret_key_goes_in_the_apikey_header_only(tmp_path: Path):
    fake = FakeSupabase(valid_key=NEW_KEY)
    uploaded(make(fake, key=NEW_KEY), tmp_path)
    assert fake.requests[0].headers["apikey"] == NEW_KEY
    assert all("authorization" not in r.headers for r in fake.requests)


def test_if_apikey_only_is_refused_it_falls_back_to_bearer_once_and_remembers(tmp_path: Path):
    fake = FakeSupabase(valid_key=NEW_KEY, require_bearer=True)
    store = make(fake, key=NEW_KEY)
    key = uploaded(store, tmp_path)
    assert [("authorization" in r.headers) for r in fake.requests] == [False, True]

    with store.open_local(key):
        pass
    assert all("authorization" in r.headers for r in fake.requests[2:]), "the fallback is remembered"


def test_a_wrong_key_fails_after_a_single_fallback_attempt(tmp_path: Path):
    fake = FakeSupabase(valid_key="the-real-key")
    with pytest.raises(StorageError, match="HTTP 401"):
        uploaded(make(fake, key=NEW_KEY), tmp_path)
    assert len(fake.requests) == 2
