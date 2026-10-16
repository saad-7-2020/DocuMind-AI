import numpy as np

from documind.embedding.fake import HashEmbedder
from documind.observability.logging import redact


def test_hash_embedder_is_normalized_and_accent_insensitive():
    e = HashEmbedder(1024)
    v = e.embed_documents(["Résiliation du contrat", "resiliation du contrat"])
    assert v.shape == (2, 1024)
    assert np.allclose(np.linalg.norm(v, axis=1), 1.0)
    assert np.allclose(v[0], v[1])


def test_hash_embedder_ranks_word_overlap_higher():
    e = HashEmbedder(1024)
    q = e.embed_query("préavis de résiliation")
    docs = e.embed_documents(["Le préavis de résiliation est de 30 jours.", "Le prix est de 12 000 euros."])
    scores = docs @ q
    assert scores[0] > scores[1]


def test_redaction_removes_content_fields():
    event = {"event": "x", "question": "secret?", "text": "doc body", "job_id": "123", "Authorization": "Bearer k"}
    out = redact(None, "info", event)
    assert out["question"] == out["text"] == out["Authorization"] == "[redacted]"
    assert out["job_id"] == "123"
