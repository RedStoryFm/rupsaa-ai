import json
import subprocess
import sys
from pathlib import Path

from rupsaa.dataset.schema import ConversationRecord
from rupsaa.dataset.store import DatasetStore

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dataset_snapshot.py"


def make_record(id="rup-000001") -> ConversationRecord:
    return ConversationRecord(
        id=id,
        messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        language="en",
        category="casual_friendly",
        source_type="imported",
        quality_status="draft",
    )


def run(args, base_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--base-dir", str(base_dir)],
        capture_output=True, text=True,
    )


def test_create_and_verify_snapshot(tmp_path):
    base_dir = tmp_path / "production"
    store = DatasetStore(base_dir)
    store.save_new(make_record("rup-000001"))
    store.save_new(make_record("rup-000002"))

    result = run(["create", "--name", "test_snap"], base_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (base_dir / "snapshots" / "test_snap" / "MANIFEST.json").exists()

    manifest = json.loads((base_dir / "snapshots" / "test_snap" / "MANIFEST.json").read_text())
    assert manifest["file_count"] == 2
    assert len(manifest["conversations"]) == 2

    verify_result = run(["verify", "--name", "test_snap"], base_dir)
    assert verify_result.returncode == 0
    assert "verified OK" in verify_result.stdout


def test_verify_detects_checksum_tamper(tmp_path):
    base_dir = tmp_path / "production"
    store = DatasetStore(base_dir)
    store.save_new(make_record("rup-000001"))
    run(["create", "--name", "test_snap"], base_dir)

    snap_file = base_dir / "snapshots" / "test_snap" / "drafts" / "rup-000001.json"
    snap_file.write_text('{"tampered": true}', encoding="utf-8")

    result = run(["verify", "--name", "test_snap"], base_dir)
    assert result.returncode == 1
    assert "CHECKSUM MISMATCH" in result.stdout


def test_restore_requires_yes_flag(tmp_path):
    base_dir = tmp_path / "production"
    store = DatasetStore(base_dir)
    store.save_new(make_record("rup-000001"))
    run(["create", "--name", "test_snap"], base_dir)

    result = run(["restore", "--name", "test_snap"], base_dir)
    assert result.returncode == 1
    assert "requires --yes" in result.stdout


def test_restore_recreates_deleted_conversation(tmp_path):
    base_dir = tmp_path / "production"
    store = DatasetStore(base_dir)
    store.save_new(make_record("rup-000001"))
    run(["create", "--name", "test_snap"], base_dir)

    (base_dir / "drafts" / "rup-000001.json").unlink()
    assert store.load("rup-000001") is None

    result = run(["restore", "--name", "test_snap", "--yes"], base_dir)
    assert result.returncode == 0

    restored_store = DatasetStore(base_dir)
    assert restored_store.load("rup-000001") is not None


def test_create_refuses_to_overwrite_existing_snapshot(tmp_path):
    base_dir = tmp_path / "production"
    store = DatasetStore(base_dir)
    store.save_new(make_record("rup-000001"))
    run(["create", "--name", "test_snap"], base_dir)

    result = run(["create", "--name", "test_snap"], base_dir)
    assert result.returncode == 1
    assert "already exists" in result.stdout
