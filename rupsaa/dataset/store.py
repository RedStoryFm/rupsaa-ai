"""Physical storage for production conversation records.

One JSON file per conversation, named `<id>.json`, living in one of three
status directories under base_dir: drafts/, approved/, rejected/. Both the
"draft" and "needs_edit" quality_status values live physically in drafts/
(see rupsaa.dataset.taxonomy.STATUS_TO_DIR) — the file's `quality_status`
field is the source of truth for which of the two it is; the directory only
tracks the coarser draft/approved/rejected split, which is what the review
workflow (approve/reject) actually moves between.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.taxonomy import STATUS_TO_DIR

_ID_RE = re.compile(r"^(?P<prefix>[a-zA-Z]+)-(?P<number>\d+)$")


@dataclass
class RecordLocation:
    record: ConversationRecord
    path: Path


class DatasetStore:
    STATUS_DIRS = ("drafts", "approved", "rejected")

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        for d in self.STATUS_DIRS:
            (self.base_dir / d).mkdir(parents=True, exist_ok=True)
        (self.base_dir / "exports").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "reports").mkdir(parents=True, exist_ok=True)

    @property
    def drafts_dir(self) -> Path:
        return self.base_dir / "drafts"

    @property
    def approved_dir(self) -> Path:
        return self.base_dir / "approved"

    @property
    def rejected_dir(self) -> Path:
        return self.base_dir / "rejected"

    @property
    def exports_dir(self) -> Path:
        return self.base_dir / "exports"

    @property
    def reports_dir(self) -> Path:
        return self.base_dir / "reports"

    def _dir_for_status(self, quality_status: str) -> Path:
        return self.base_dir / STATUS_TO_DIR[quality_status]

    def generate_id(self, prefix: str, padding: int) -> str:
        max_n = 0
        for status_dir in self.STATUS_DIRS:
            for path in (self.base_dir / status_dir).glob("*.json"):
                m = _ID_RE.match(path.stem)
                if m and m.group("prefix") == prefix:
                    max_n = max(max_n, int(m.group("number")))
        return f"{prefix}-{str(max_n + 1).zfill(padding)}"

    def save_new(self, record: ConversationRecord) -> Path:
        target_dir = self._dir_for_status(record.quality_status)
        path = target_dir / f"{record.id}.json"
        if path.exists():
            raise FileExistsError(f"record already exists at {path}")
        path.write_text(record.to_json(), encoding="utf-8")
        return path

    def _find_path(self, record_id: str) -> Path | None:
        for status_dir in self.STATUS_DIRS:
            candidate = self.base_dir / status_dir / f"{record_id}.json"
            if candidate.exists():
                return candidate
        return None

    def load(self, record_id: str) -> RecordLocation | None:
        path = self._find_path(record_id)
        if path is None:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return RecordLocation(record=ConversationRecord.from_dict(data), path=path)

    def list_all(self, statuses: set[str] | None = None) -> list[RecordLocation]:
        """statuses filters by quality_status field (draft/needs_edit/approved/
        rejected), not by directory — so e.g. {"draft"} excludes needs_edit
        even though both live in drafts/."""
        results: list[RecordLocation] = []
        for status_dir in self.STATUS_DIRS:
            for path in sorted((self.base_dir / status_dir).glob("*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                record = ConversationRecord.from_dict(data)
                if statuses is None or record.quality_status in statuses:
                    results.append(RecordLocation(record=record, path=path))
        return results

    def save(self, record: ConversationRecord, path: Path) -> None:
        """Overwrite a record in place (same directory) — used when only
        metadata changes without a status transition, e.g. normalization."""
        path.write_text(record.to_json(), encoding="utf-8")

    def move(self, record: ConversationRecord, old_path: Path, new_status: str) -> Path:
        record.quality_status = new_status
        record.touch()
        new_dir = self._dir_for_status(new_status)
        new_path = new_dir / f"{record.id}.json"
        new_path.write_text(record.to_json(), encoding="utf-8")
        if old_path.resolve() != new_path.resolve() and old_path.exists():
            old_path.unlink()
        return new_path
