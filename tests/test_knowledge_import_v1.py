"""Importer fixes for Knowledge V1: truthful approval, lossless sources in every format, stable ids; Terminology
provenance + backups. No network, no GPU."""

import json

import pytest

from rupsaa.rag import general_knowledge_import as gki
from rupsaa.rag.general_knowledge import GeneralKnowledgeStore, KnowledgeError
from rupsaa.rag.terminology import TerminologyStore

SRC = [{"title": "Glossary (Planned Parenthood)", "url": "https://www.plannedparenthood.org/learn/glossary",
        "domain": "plannedparenthood.org", "retrieved_at": "2026-10-01"}]


def _rec(rid, title, **kw):
    return {"id": rid, "title": title, "category": "Sexual Education", "summary": f"About {title}.",
            "aliases": [title.lower() + " mane ki"], "source_type": "import", "verified": False, "approved_by": "",
            "sources": SRC, "enabled": True, **kw}


def _jsonl(*recs) -> bytes:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in recs).encode()


@pytest.fixture
def store(tmp_path):
    return GeneralKnowledgeStore(tmp_path / "gk", embedder=lambda t, q: None)


def test_blank_approval_is_never_turned_into_owner_approval(store, tmp_path):
    gki.commit("pack.jsonl", _jsonl(_rec("gk-testicles", "Testicles and Scrotum"),
                                    _rec("gk-owner_ok", "Owner Ok", approved_by="owner")), store)
    assert store.get("gk-testicles").approved_by == ""  # not reviewed stays not reviewed
    assert store.get("gk-owner_ok").approved_by == "owner"  # explicit approval is kept
    for fmt, exporter in (("csv", gki.export_csv), ("xlsx", gki.export_xlsx)):
        other = GeneralKnowledgeStore(tmp_path / fmt, embedder=lambda t, q: None)
        gki.commit(f"k.{fmt}", exporter(store), other)
        assert other.get("gk-testicles").approved_by == "" and other.get("gk-owner_ok").approved_by == "owner"
    with pytest.raises(KnowledgeError):
        store.create({"title": "X", "summary": "y", "approved_by": "someone"})


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "json"])
def test_sources_survive_import_export_reimport(store, tmp_path, fmt):
    gki.commit("pack.jsonl", _jsonl(_rec("gk-vulva", "Vulva")), store)
    assert store.get("gk-vulva").sources == SRC  # JSONL import is lossless (domain/retrieved_at as supplied)
    exported = {"csv": gki.export_csv, "xlsx": gki.export_xlsx, "json": gki.export_json}[fmt](store)
    other = GeneralKnowledgeStore(tmp_path / "re", embedder=lambda t, q: None)
    result = gki.commit(f"k.{fmt}", exported, other)
    assert result["counts"]["created"] == 1
    assert other.get("gk-vulva").sources == SRC
    if fmt == "csv":
        assert "plannedparenthood.org/learn/glossary" in exported.decode("utf-8-sig")


def test_supplied_ids_are_preserved_and_only_missing_ids_generated(store):
    res = gki.commit("pack.jsonl", _jsonl(_rec("gk-testicles", "Testicles and Scrotum"),
                                          {"title": "No Id Here", "summary": "s"}), store)
    assert res["counts"]["created"] == 2
    assert store.get("gk-testicles").title == "Testicles and Scrotum"  # not gk-testicles_and_scrotum
    assert store.get("gk-no_id_here")


def test_unsafe_and_duplicate_ids_are_rejected(store):
    pv = gki.preview("pack.jsonl", _jsonl(_rec("../etc/passwd", "Bad"), _rec("GK-Upper", "Upper"),
                                          _rec("gk-a", "Alpha"), _rec("gk-a", "Beta")), store)
    st = [r["status"] for r in pv["rows"]]
    assert st[0] == st[1] == "invalid" and st[2] == "valid" and st[3] == "duplicate_in_file"
    gki.commit("pack.jsonl", _jsonl(_rec("gk-a", "Alpha")), store)
    # same id again = update of that record (stable id, revision bump); a new id reusing its title = conflict
    pv = gki.preview("pack.jsonl", _jsonl(_rec("gk-a", "Alpha", summary="New."), _rec("gk-b", "Alpha")), store)
    assert [r["status"] for r in pv["rows"]] == ["existing_match", "duplicate_in_file"]
    pv = gki.preview("pack.jsonl", _jsonl(_rec("gk-b", "Alpha")), store)
    assert pv["rows"][0]["status"] == "invalid"
    gki.commit("pack.jsonl", _jsonl(_rec("gk-a", "Alpha", summary="New.")), store, update_rows={1})
    rec = store.get("gk-a")
    assert rec.summary == "New." and rec.revision == 2 and len(store.list()) == 1
    with pytest.raises(KnowledgeError):
        store.create({"id": "gk-a", "title": "Other", "summary": "x"})


def test_terminology_keeps_sources_and_merge_provenance_with_backup(tmp_path):
    ts = TerminologyStore(tmp_path / "t")
    rec = ts.create({"term": "Consent", "definition": "Permission.", "category": "adult_terminology"})
    merged = ts.update(rec.id, {"aliases": ["sommoti"], "sources": SRC,
                                "merged_from": [{"id": "gk-consent", "source_type": "import", "approved_by": ""}]})
    assert merged.sources == SRC and merged.merged_from[0]["id"] == "gk-consent" and merged.revision == 2
    assert merged.approved_by == ""  # merging unreviewed content never marks the record approved
    assert list((tmp_path / "t" / ".history").glob("term-consent.*.json"))
    assert ts.get(rec.id).sources == SRC  # persisted
    with pytest.raises(Exception):
        ts.update(rec.id, {"sources": [{"url": "http://127.0.0.1/x"}]})


def test_owner_created_records_are_owner_approved(tmp_path, monkeypatch):
    import api.main as main
    import api.owner_routes as owner_routes
    from fastapi.testclient import TestClient

    gk = GeneralKnowledgeStore(tmp_path / "gk", embedder=lambda t, q: None)
    monkeypatch.setattr(owner_routes, "_get_general", lambda: gk)
    c = TestClient(main.app)
    r = c.post("/owner/general", json={"title": "Owner Thing", "summary": "s"}).json()
    assert r["approved_by"] == "owner"  # written by the owner in the Knowledge Manager
    r = c.post("/owner/general", json={"title": "Draft Thing", "summary": "s", "approved_by": ""}).json()
    assert r["approved_by"] == ""
    r = c.put(f"/owner/general/{r['id']}", json={"enabled": False}).json()
    assert r["approved_by"] == "" and r["enabled"] is False  # toggling never approves
