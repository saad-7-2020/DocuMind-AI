"""Describe a freshly indexed document: a short summary, keywords and questions worth asking.

Uses the small, fast model on the beginning of the document only. Description is a nicety: it never
fails an upload, and a document without one is still fully searchable.
"""

from __future__ import annotations

import json
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from documind.db.session import transaction
from documind.db.tables import Document, DocumentPage
from documind.generation.llm.base import LLMProvider

log = structlog.get_logger(__name__)

EXCERPT_CHARS = 6000
MAX_KEYWORDS, MAX_QUESTIONS = 6, 3

DESCRIBE_SYSTEM = (
    "Tu présentes un document à son propriétaire. Réponds uniquement en JSON. "
    "Écris dans la langue du document. Sois factuel : n'invente rien qui ne figure pas dans l'extrait. "
    "summary : 2 à 3 phrases (type de document, sujet, informations principales). "
    f"keywords : {MAX_KEYWORDS} mots-clés ou expressions courtes au plus. "
    f"suggested_questions : exactement {MAX_QUESTIONS} questions précises auxquelles ce document permet de répondre, "
    "formulées comme le ferait l'utilisateur."
)
DESCRIBE_USER = "Nom du fichier : {filename}\n\nTexte du document :\n{text}"

DESCRIBE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "suggested_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "keywords", "suggested_questions"],
    "additionalProperties": False,
}


def _clean_list(raw: object, limit: int, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    items: list[str] = []
    for x in raw:
        item = str(x).strip()[:max_len]
        if item and item.lower() not in {i.lower() for i in items}:
            items.append(item)
    return items[:limit]


class DocumentDescriber:
    def __init__(self, llm: LLMProvider, sf: sessionmaker[Session]) -> None:
        self.llm = llm
        self.sf = sf

    def describe(self, document_id: uuid.UUID) -> bool:
        """Generate and store the description. Returns False (and logs) on any failure; never raises."""
        try:
            with self.sf() as s:
                doc = s.get(Document, document_id)
                if doc is None:
                    return False
                filename = doc.filename
                pages = s.scalars(
                    select(DocumentPage.text).where(DocumentPage.document_id == document_id)
                    .order_by(DocumentPage.page_number)
                )
                excerpt = ""
                for text in pages:
                    excerpt += text + "\n"
                    if len(excerpt) >= EXCERPT_CHARS:
                        break
            excerpt = excerpt[:EXCERPT_CHARS].strip()
            if not excerpt:
                return False
            result = self.llm.generate(
                [{"role": "system", "content": DESCRIBE_SYSTEM},
                 {"role": "user", "content": DESCRIBE_USER.format(filename=filename, text=excerpt)}],
                "document_description", DESCRIBE_SCHEMA,
            )
            data = json.loads(result.content)
            summary = str(data.get("summary", "")).strip()[:1200]
            if not summary:
                return False
            keywords = _clean_list(data.get("keywords"), MAX_KEYWORDS, 60)
            questions = _clean_list(data.get("suggested_questions"), MAX_QUESTIONS, 200)
            with transaction(self.sf) as s:
                doc = s.get(Document, document_id)
                if doc is None:
                    return False
                doc.summary, doc.keywords, doc.suggested_questions = summary, keywords, questions
            return True
        except Exception as e:
            log.warning("describe_failed", error_type=type(e).__name__)
            return False
