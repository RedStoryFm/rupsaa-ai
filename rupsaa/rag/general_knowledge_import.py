"""Bulk import / export of General Knowledge records (CSV / XLSX / JSON).

Same preview → commit flow and safety limits as the terminology and dance importers (file size, row limit, cell
length, formula-looking cells kept as plain text, duplicate-in-file detection, existing records SKIPPED unless the
owner explicitly chooses UPDATE for that row). List fields use "|" between items (key points, steps, aliases …).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field

from rupsaa.rag.general_knowledge import (
    CATEGORIES,
    LANGUAGES,
    SOURCE_TYPES,
    GeneralKnowledgeStore,
    KnowledgeError,
    KnowledgeRecord,
    validate,
)
from rupsaa.rag.terminology import normalize
from rupsaa.rag.terminology_import import MAX_CELL_CHARS, MAX_FILE_BYTES, ImportFileError, _cell, _read_csv, _read_xlsx

COLUMNS = ["id", "title", "category", "subcategory", "aliases", "summary", "description", "key_points", "steps", "do", "dont",
           "answer_guidance", "languages", "tags", "enabled", "source", "source_type", "verified", "approved_by",
           "sources"]
STRUCTURED_COLUMNS = ("sources",)  # list of {title, url, domain, retrieved_at}; a JSON string inside CSV/XLSX cells
BOOL_COLUMNS = ("enabled", "verified")
LIST_COLUMNS = ("aliases", "key_points", "steps", "do", "dont", "languages", "tags")
SUPPORTED_EXTENSIONS = (".csv", ".xlsx", ".jsonl", ".json")
MAX_ROWS = 1000
HEADER_SYNONYMS = {
    "id": ["id", "record_id"], "title": ["title", "topic", "name", "concept", "term"], "category": ["category", "section"],
    "subcategory": ["subcategory", "sub_category", "subtopic"], "aliases": ["aliases", "alias", "also_known_as", "aka"],
    "summary": ["summary", "short", "short_answer"], "description": ["description", "details", "knowledge", "content"],
    "key_points": ["key_points", "points", "keypoints"], "steps": ["steps", "how_to", "instructions"], "do": ["do", "dos"],
    "dont": ["dont", "don_t", "donts", "avoid"], "answer_guidance": ["answer_guidance", "guidance"],
    "languages": ["languages", "language"], "tags": ["tags", "tag"], "enabled": ["enabled", "active"],
    "source": ["source", "notes"], "source_type": ["source_type", "provenance"], "verified": ["verified"],
    "approved_by": ["approved_by"], "sources": ["sources", "references"],
}
_HEADER_MAP = {normalize(s).replace(" ", "_"): canon for canon, syns in HEADER_SYNONYMS.items() for s in syns}
_TRUE, _FALSE = {"true", "yes", "y", "1"}, {"false", "no", "n", "0"}


@dataclass
class Row:
    row: int
    status: str  # valid | warning | invalid | duplicate_in_file | existing_match
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    existing_id: str | None = None


def _ext(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    ext = next((e for e in SUPPORTED_EXTENSIONS if name.endswith(e)), None)
    if ext is None:
        raise ImportFileError("Unsupported file type — upload a .csv, .xlsx, .json or .jsonl file.")
    if not content:
        raise ImportFileError("The file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ImportFileError(f"File is too large (max {MAX_FILE_BYTES // (1024 * 1024)} MB).")
    return ext


def _raw_rows(ext: str, content: bytes) -> list[dict]:
    if ext == ".jsonl":
        data = []
        try:
            for n, line in enumerate(content.decode("utf-8-sig").splitlines(), start=1):
                if line.strip():
                    data.append(json.loads(line))
        except UnicodeDecodeError as e:
            raise ImportFileError(f"Could not read JSONL: {e}")
        except json.JSONDecodeError as e:
            raise ImportFileError(f"Could not parse JSONL line {n}: {e}")
    if ext == ".json":
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportFileError(f"Could not parse JSON: {e}")
    if ext in (".json", ".jsonl"):
        if isinstance(data, dict):
            data = data.get("records") or data.get("knowledge") or data.get("items")
        if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
            raise ImportFileError('JSON must be a list of objects (or {"records": [...]}).')
        return [{_HEADER_MAP.get(normalize(k).replace(" ", "_")): v for k, v in o.items()} for o in data]
    table = _read_csv(content) if ext == ".csv" else _read_xlsx(content)
    if not table:
        raise ImportFileError("The file has no header row.")
    header = [_HEADER_MAP.get(normalize(h).replace(" ", "_")) for h in table[0]]
    if "title" not in header:
        raise ImportFileError("No 'title' column found (accepted: " + ", ".join(HEADER_SYNONYMS["title"]) + ").")
    return [{header[i]: vals[i] for i in range(min(len(header), len(vals))) if header[i]} for vals in table[1:]]


def _text(v) -> str:
    return " | ".join(str(x) for x in v) if isinstance(v, list) else _cell(v)


def _parse(n: int, raw: dict) -> Row:
    errors, warnings = [], []
    cells = {k: _text(raw.get(k)).strip() for k in COLUMNS if k not in STRUCTURED_COLUMNS}
    for k, v in cells.items():
        if len(v) > MAX_CELL_CHARS:
            errors.append(f"{k} is longer than {MAX_CELL_CHARS} characters")
        if v.startswith("="):
            warnings.append(f"{k} starts with '=' — treated as plain text")
    data = {k: cells[k] for k in COLUMNS if k not in LIST_COLUMNS and k not in BOOL_COLUMNS and k not in STRUCTURED_COLUMNS}
    for k in LIST_COLUMNS:
        data[k] = [x.strip() for x in cells[k].split("|") if x.strip()]
    if data["category"] and data["category"] not in CATEGORIES:
        match = next((c for c in CATEGORIES if normalize(c) == normalize(data["category"])), None)
        if match:
            data["category"] = match
        else:
            warnings.append(f"Unknown category {data['category']!r} → stored as Custom")
            data["category"] = "Custom"
    data["languages"] = [x for x in data["languages"] if x in LANGUAGES] or list(LANGUAGES)
    for k, default in (("enabled", True), ("verified", False)):
        v = cells[k].lower()
        data[k] = default if not v else (True if v in _TRUE else (False if v in _FALSE else None))
        if data[k] is None:
            errors.append(f"Invalid {k} value {cells[k]!r}")
            data[k] = default
    if data["source_type"] and data["source_type"] not in SOURCE_TYPES:
        warnings.append(f"Unknown source_type {data['source_type']!r} → stored as import")
    if data["source_type"] not in SOURCE_TYPES:
        data["source_type"] = "import"
    # approved_by is kept exactly as supplied: a blank (not reviewed) record is never marked owner-approved.
    if not data["id"]:
        data.pop("id")  # the store generates one from the title
    raw_sources = raw.get("sources")
    if isinstance(raw_sources, str) and raw_sources.strip():  # CSV/XLSX: JSON array string
        try:
            raw_sources = json.loads(raw_sources)
        except json.JSONDecodeError:
            errors.append("sources is not a valid JSON array")
            raw_sources = []
    data["sources"] = raw_sources if isinstance(raw_sources, list) else []
    errors += validate(data)
    return Row(row=n, status="invalid" if errors else ("warning" if warnings else "valid"), data=data, errors=errors,
               warnings=warnings)


def preview(filename: str, content: bytes, store: GeneralKnowledgeStore) -> dict:
    ext = _ext(filename, content)
    raws = _raw_rows(ext, content)
    first = 1 if ext in (".json", ".jsonl") else 2
    rows: list[Row] = []
    for i, raw in enumerate(raws, start=first):
        if not any(_text(v).strip() for v in raw.values() if v is not None):
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(f"Too many rows — the limit is {MAX_ROWS} per file.")
        rows.append(_parse(i, {k: v for k, v in raw.items() if k}))
    existing = store.list()
    by_id = {e.id: e for e in existing}
    seen: dict[str, int] = {}
    seen_ids: dict[str, int] = {}
    for r in rows:
        if r.status == "invalid":
            continue
        rid = r.data.get("id")
        if rid and rid in seen_ids:
            r.status = "duplicate_in_file"
            r.errors.append(f"Duplicate id {rid} (row {seen_ids[rid]})")
            continue
        keys = KnowledgeRecord(id="gk-x", title=r.data["title"], aliases=r.data["aliases"]).keys()
        clash = next((seen[k] for k in keys if k in seen), None)
        if clash is not None:
            r.status = "duplicate_in_file"
            r.errors.append(f"Duplicate of row {clash} in this file (same title or alias)")
            continue
        for k in keys:
            seen[k] = r.row
        if rid:
            seen_ids[rid] = r.row
        matches = [e for e in existing if keys & e.keys()]
        if rid and rid in by_id:  # same stable id: an update of that record
            others = [m for m in matches if m.id != rid]
            if others:
                r.status = "invalid"
                r.errors.append("Title/aliases already used by " + ", ".join(f"{m.id} ({m.title})" for m in others))
            else:
                r.status, r.existing_id = "existing_match", rid
            continue
        if rid and matches:
            r.status = "invalid"
            r.errors.append(f"New id {rid} but its title/aliases are already used by "
                            + ", ".join(f"{m.id} ({m.title})" for m in matches))
            continue
        if len(matches) == 1:
            r.status, r.existing_id = "existing_match", matches[0].id
        elif len(matches) > 1:
            r.status = "invalid"
            r.errors.append("Title/aliases match several existing records: " + ", ".join(m.title for m in matches))
    counts = {s: sum(r.status == s for r in rows) for s in ("valid", "warning", "invalid", "duplicate_in_file", "existing_match")}
    return {"file_type": ext.lstrip("."), "total": len(rows), "counts": counts, "rows": [asdict(r) for r in rows]}


def commit(filename: str, content: bytes, store: GeneralKnowledgeStore, update_rows: set[int] | None = None) -> dict:
    update_rows = set(update_rows or ())
    out = {"created": [], "updated": [], "skipped": [], "failed": []}
    for r in preview(filename, content, store)["rows"]:
        d = r["data"]
        if r["status"] in ("invalid", "duplicate_in_file"):
            out["skipped"].append({"row": r["row"], "title": d.get("title"), "reason": "; ".join(r["errors"])})
            continue
        try:
            if r["status"] == "existing_match":
                if r["row"] not in update_rows:
                    out["skipped"].append({"row": r["row"], "title": d["title"], "reason": f"exists as {r['existing_id']} (SKIP)"})
                    continue
                rec = store.update(r["existing_id"], d)
                out["updated"].append({"row": r["row"], "id": rec.id, "title": rec.title})
            else:
                rec = store.create({**d, "source": d.get("source") or f"import:{filename}"})
                out["created"].append({"row": r["row"], "id": rec.id, "title": rec.title})
        except KnowledgeError as e:
            out["failed"].append({"row": r["row"], "title": d.get("title"), "error": str(e)})
    out["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    return out


def export_json(store: GeneralKnowledgeStore) -> bytes:
    return json.dumps({"records": [asdict(r) for r in store.list()]}, ensure_ascii=False, indent=2).encode("utf-8")


def _row(r: KnowledgeRecord) -> dict:
    d = asdict(r)
    out = {}
    for k in COLUMNS:
        if k in LIST_COLUMNS:
            out[k] = " | ".join(d[k])
        elif k in BOOL_COLUMNS:
            out[k] = "true" if d[k] else "false"
        elif k in STRUCTURED_COLUMNS:
            out[k] = json.dumps(d[k], ensure_ascii=False) if d[k] else ""
        else:
            out[k] = d[k]
    return out


def export_csv(store: GeneralKnowledgeStore) -> bytes:
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\r\n")
    w.writeheader()
    for r in store.list():
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] and v[0] in "=+-@" else v) for k, v in _row(r).items()})
    return ("﻿" + buf.getvalue()).encode("utf-8")


def export_xlsx(store: GeneralKnowledgeStore) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "General Knowledge"
    ws.append(COLUMNS)
    for r in store.list():
        ws.append([("'" + v if isinstance(v, str) and v[:1] and v[0] in "=+-@" else v) for v in _row(r).values()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
