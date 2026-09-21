"""Document extraction for the RAG knowledge base.

Supports .txt, .md, .json, .pdf (configs/rag.yaml documents.supported_extensions).
PDF support uses pypdf, a maintained pure-Python dependency — no system
package required.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger("rupsaa.rag.document_loader")


@dataclass
class RawDocument:
    source_filename: str
    text: str


def _load_txt_or_md(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_json(path: Path) -> str:
    """A JSON knowledge doc may be either a plain string, a list of strings,
    or an object with a "text"/"content" field — extract text pragmatically
    rather than assuming one schema."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, str):
        return data
    if isinstance(data, list):
        return "\n\n".join(str(item) for item in data)
    if isinstance(data, dict):
        for key in ("text", "content", "body"):
            if key in data:
                return str(data[key])
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


_LOADERS = {
    ".txt": _load_txt_or_md,
    ".md": _load_txt_or_md,
    ".json": _load_json,
    ".pdf": _load_pdf,
}


def load_document(path: Path) -> RawDocument | None:
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        logger.warning("Skipping unsupported file type: %s", path)
        return None
    try:
        text = loader(path)
    except Exception:
        logger.exception("Failed to extract text from %s", path)
        return None
    text = text.strip()
    if not text:
        logger.warning("No extractable text in %s", path)
        return None
    return RawDocument(source_filename=path.name, text=text)


def load_documents_from_dir(source_dir: Path, supported_extensions: list[str]) -> list[RawDocument]:
    docs: list[RawDocument] = []
    if not source_dir.exists():
        logger.warning("Knowledge source directory does not exist: %s", source_dir)
        return docs
    for path in sorted(source_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in supported_extensions:
            doc = load_document(path)
            if doc:
                docs.append(doc)
    return docs
