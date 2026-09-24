#!/usr/bin/env python3
"""Create or verify a versioned, restorable snapshot of the production
dataset (drafts/approved/rejected).

Usage:
    python scripts/dataset_snapshot.py create --name pre_v01_pretraining
    python scripts/dataset_snapshot.py verify --name pre_v01_pretraining
    python scripts/dataset_snapshot.py restore --name pre_v01_pretraining --yes

`create` copies every conversation JSON file verbatim into
data/production/snapshots/<name>/{drafts,approved,rejected}/ and writes a
MANIFEST.json with per-file SHA-256, conversation IDs, quality_status,
timestamp, and the current git commit (plus whether the working tree was
dirty at snapshot time).

`verify` re-checksums the snapshot against its own manifest and confirms
its conversation IDs exactly match whatever is currently live in
data/production/ (a live/manifest mismatch is reported, not an error —
that's expected once you've made changes after snapshotting).

`restore` is destructive: it overwrites the live drafts/approved/rejected
files with the snapshot's contents. Requires --yes. Never run automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import default_base_dir  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402


def _git_info(cwd: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip()
    except Exception:
        commit = None
    try:
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=cwd, text=True).strip())
    except Exception:
        dirty = None
    return commit, dirty


def create_snapshot(base_dir: Path, name: str) -> Path:
    snapshot_dir = base_dir / "snapshots" / name
    if snapshot_dir.exists():
        print(f"REFUSING: snapshot '{name}' already exists at {snapshot_dir}")
        sys.exit(1)

    entries = []
    file_count = 0
    for status_dir in DatasetStore.STATUS_DIRS:
        src_dir = base_dir / status_dir
        dst_dir = snapshot_dir / status_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(src_dir.glob("*.json")):
            data = path.read_bytes()
            sha256 = hashlib.sha256(data).hexdigest()
            (dst_dir / path.name).write_bytes(data)
            record = json.loads(data)
            entries.append({
                "conversation_id": record["id"],
                "status_dir": status_dir,
                "quality_status": record["quality_status"],
                "filename": path.name,
                "sha256": sha256,
            })
            file_count += 1

    project_root = base_dir.parent
    git_commit, git_dirty = _git_info(project_root)

    manifest = {
        "snapshot_name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "file_count": file_count,
        "git_commit": git_commit,
        "git_working_tree_dirty_at_snapshot_time": git_dirty,
        "conversations": entries,
    }
    (snapshot_dir / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snapshot_dir


def verify_snapshot(base_dir: Path, name: str) -> bool:
    snapshot_dir = base_dir / "snapshots" / name
    manifest_path = snapshot_dir / "MANIFEST.json"
    if not manifest_path.exists():
        print(f"No manifest found at {manifest_path}")
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    errors = []
    snap_ids = set()
    for entry in manifest["conversations"]:
        snap_path = snapshot_dir / entry["status_dir"] / entry["filename"]
        if not snap_path.exists():
            errors.append(f"MISSING snapshot file: {snap_path}")
            continue
        actual = hashlib.sha256(snap_path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            errors.append(f"CHECKSUM MISMATCH: {entry['conversation_id']}")
        snap_ids.add(entry["conversation_id"])

    if len(snap_ids) != len(manifest["conversations"]):
        errors.append("duplicate conversation_id in manifest")
    if len(manifest["conversations"]) != manifest["file_count"]:
        errors.append("manifest file_count does not match entry count")

    live_ids = set()
    for status_dir in DatasetStore.STATUS_DIRS:
        for p in (base_dir / status_dir).glob("*.json"):
            live_ids.add(json.loads(p.read_bytes())["id"])

    print(f"Snapshot '{name}': {len(manifest['conversations'])} entries, git_commit={manifest.get('git_commit')}")
    print(f"Live dataset currently has {len(live_ids)} conversations.")
    if snap_ids == live_ids:
        print("Snapshot IDs exactly match the live dataset (no changes since snapshot).")
    else:
        only_snap = snap_ids - live_ids
        only_live = live_ids - snap_ids
        print(
            f"Snapshot and live dataset differ (expected if edits happened after snapshotting): "
            f"{len(only_snap)} only in snapshot, {len(only_live)} only live."
        )

    if errors:
        print("\nERRORS:")
        for e in errors:
            print(" -", e)
        return False
    print("\nAll checksums verified OK — snapshot is intact and restorable.")
    return True


def restore_snapshot(base_dir: Path, name: str, confirmed: bool) -> None:
    if not confirmed:
        print("Restore is destructive and requires --yes. Refusing without it.")
        sys.exit(1)
    snapshot_dir = base_dir / "snapshots" / name
    manifest = json.loads((snapshot_dir / "MANIFEST.json").read_text(encoding="utf-8"))

    for status_dir in DatasetStore.STATUS_DIRS:
        dst = base_dir / status_dir
        for p in dst.glob("*.json"):
            p.unlink()

    for entry in manifest["conversations"]:
        src = snapshot_dir / entry["status_dir"] / entry["filename"]
        dst = base_dir / entry["status_dir"] / entry["filename"]
        shutil.copy2(src, dst)

    print(f"Restored {len(manifest['conversations'])} conversation(s) from snapshot '{name}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["create", "verify", "restore"])
    parser.add_argument("--name", required=True)
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--yes", action="store_true", help="Required to confirm a restore.")
    args = parser.parse_args()

    base_dir = Path(args.base_dir) if args.base_dir else default_base_dir()

    if args.action == "create":
        snapshot_dir = create_snapshot(base_dir, args.name)
        print(f"Snapshot created at {snapshot_dir}")
        ok = verify_snapshot(base_dir, args.name)
        if not ok:
            print("\nSnapshot verification FAILED immediately after creation — investigate.")
            sys.exit(1)
    elif args.action == "verify":
        ok = verify_snapshot(base_dir, args.name)
        sys.exit(0 if ok else 1)
    elif args.action == "restore":
        restore_snapshot(base_dir, args.name, args.yes)


if __name__ == "__main__":
    main()
