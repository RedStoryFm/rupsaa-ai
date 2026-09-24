"""Owner-facing CRUD over knowledge/documents/, for the "Rupsaa Knowledge"
web tool.

Deliberately separate from document_loader.py, which only *reads* files for
RAG ingestion — this module manages the files themselves plus a lightweight
JSON sidecar (`.metadata.json`) for title/category/ownership/timestamps. It
never touches the FAISS index; after any change, call
rupsaa.rag.pipeline.RagPipeline().ingest() to rebuild it (same ingestion
path scripts/ingest_knowledge.py already uses — no second RAG system).

Document files themselves stay pure Markdown/text content with no
frontmatter, so retrieved RAG context never leaks metadata plumbing into
what Rupsaa sees.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_CATEGORIES = [
    "rupsaa_identity",
    "creator_knowledge",
    "terminology",
    "platform_knowledge",
    "faq",
    "guides",
    "product_knowledge",
    "general_reference",
]


class DocumentManagerError(ValueError):
    pass


@dataclass
class KnowledgeDocumentMeta:
    filename: str
    title: str
    category: str
    source_notes: str = ""
    owner_created: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def _slugify(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_only).strip("_").lower()
    return slug or "document"


class DocumentManager:
    def __init__(self, docs_dir: Path):
        self.docs_dir = Path(docs_dir)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.docs_dir / ".metadata.json"

    def _load_metadata(self) -> dict:
        if not self.metadata_path.exists():
            return {}
        return json.loads(self.metadata_path.read_text(encoding="utf-8"))

    def _save_metadata(self, data: dict) -> None:
        self.metadata_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_documents(self) -> list[KnowledgeDocumentMeta]:
        metadata = self._load_metadata()
        results = []
        for path in sorted(self.docs_dir.iterdir()):
            if path.name.startswith(".") or not path.is_file():
                continue
            if path.suffix.lower() not in (".md", ".txt", ".json"):
                continue
            meta = metadata.get(path.name)
            if meta:
                results.append(KnowledgeDocumentMeta(**meta))
            else:
                # A file that exists but has no metadata entry (e.g. seeded
                # before the Knowledge Manager existed) — report it
                # honestly as not owner-created, so it's listed but not
                # editable/deletable through this tool without a human
                # explicitly deciding to adopt it.
                results.append(KnowledgeDocumentMeta(
                    filename=path.name,
                    title=path.stem,
                    category="general_reference",
                    source_notes="(pre-existing file, no Knowledge Manager metadata)",
                    owner_created=False,
                    created_at="",
                    updated_at="",
                ))
        return results

    def read_content(self, filename: str) -> str:
        path = self._safe_path(filename)
        if not path.exists():
            raise DocumentManagerError(f"no such document: {filename}")
        return path.read_text(encoding="utf-8")

    def _safe_path(self, filename: str) -> Path:
        # Reject path traversal — filename must resolve to a direct child
        # of docs_dir, nothing else.
        candidate = (self.docs_dir / filename).resolve()
        if candidate.parent != self.docs_dir.resolve():
            raise DocumentManagerError(f"invalid filename: {filename}")
        return candidate

    def create_document(self, *, title: str, category: str, content: str, source_notes: str = "") -> KnowledgeDocumentMeta:
        title = title.strip()
        content = content.strip()
        if not title:
            raise DocumentManagerError("title is required")
        if not content:
            raise DocumentManagerError("content is required")
        if category not in KNOWLEDGE_CATEGORIES:
            raise DocumentManagerError(f"unknown category '{category}' (allowed: {KNOWLEDGE_CATEGORIES})")

        base_slug = _slugify(title)
        filename = f"{base_slug}.md"
        path = self.docs_dir / filename
        suffix = 2
        while path.exists():
            filename = f"{base_slug}_{suffix}.md"
            path = self.docs_dir / filename
            suffix += 1

        path.write_text(content, encoding="utf-8")

        metadata = self._load_metadata()
        meta = KnowledgeDocumentMeta(
            filename=filename, title=title, category=category, source_notes=source_notes, owner_created=True,
        )
        metadata[filename] = asdict(meta)
        self._save_metadata(metadata)
        return meta

    def update_document(
        self, filename: str, *, content: str | None = None, title: str | None = None,
        category: str | None = None, source_notes: str | None = None,
    ) -> KnowledgeDocumentMeta:
        metadata = self._load_metadata()
        existing = metadata.get(filename)
        if not existing:
            raise DocumentManagerError(f"no Knowledge Manager metadata for '{filename}' — cannot edit a document this tool didn't create")
        if not existing.get("owner_created", False):
            raise DocumentManagerError(f"'{filename}' is not owner-created — editing through this tool is not allowed")

        path = self._safe_path(filename)
        if not path.exists():
            raise DocumentManagerError(f"metadata exists but file is missing: {filename}")

        if content is not None:
            content = content.strip()
            if not content:
                raise DocumentManagerError("content cannot be emptied")
            path.write_text(content, encoding="utf-8")
        if title is not None and title.strip():
            existing["title"] = title.strip()
        if category is not None:
            if category not in KNOWLEDGE_CATEGORIES:
                raise DocumentManagerError(f"unknown category '{category}'")
            existing["category"] = category
        if source_notes is not None:
            existing["source_notes"] = source_notes
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()

        metadata[filename] = existing
        self._save_metadata(metadata)
        return KnowledgeDocumentMeta(**existing)

    def delete_document(self, filename: str, *, confirm: bool) -> None:
        if not confirm:
            raise DocumentManagerError("deletion requires confirm=true")
        path = self._safe_path(filename)
        if not path.exists():
            raise DocumentManagerError(f"no such document: {filename}")
        path.unlink()
        metadata = self._load_metadata()
        metadata.pop(filename, None)
        self._save_metadata(metadata)
