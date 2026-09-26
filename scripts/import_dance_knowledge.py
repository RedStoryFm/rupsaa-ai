#!/usr/bin/env python3
"""Import owner dance-style records into knowledge/dance/ (the RAG dance store).

    python scripts/import_dance_knowledge.py <file.csv|.xlsx|.json>          # preview only
    python scripts/import_dance_knowledge.py <file> --yes                    # create new dances
    python scripts/import_dance_knowledge.py <file> --yes --update-existing  # also overwrite matches

Same validation as the owner UI (web/knowledge.html → Dance → Import). Only the
fields in the file are stored; nothing is generated. Required: name, description.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT, get_settings  # noqa: E402
from rupsaa.rag import dance_import  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--yes", action="store_true", help="actually import (default: preview only)")
    ap.add_argument("--update-existing", action="store_true", help="overwrite dances whose name/alias already exists")
    args = ap.parse_args()
    store = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
    content = args.file.read_bytes()
    pv = dance_import.preview(args.file.name, content, store)
    print(json.dumps(pv.counts, indent=1))
    for r in pv.rows:
        if r.errors or r.warnings or r.status != "valid":
            print(f"  row {r.row} [{r.status}] {r.data.get('name')!r}: {'; '.join(r.errors + r.warnings)}")
    if not args.yes:
        print("preview only — re-run with --yes to import")
        return
    updates = {r.row for r in pv.rows if r.status == "existing_match"} if args.update_existing else set()
    res = dance_import.commit(args.file.name, content, store, updates).to_dict()
    print(json.dumps(res["counts"], indent=1))
    for f in res["failed"]:
        print("  FAILED", f)
    print(f"store now holds {len(store.list())} dances in {store.directory.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
