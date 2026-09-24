"""Backup / release / restore tooling. No model, no network: HF access is
never exercised here (upload/download need an account); everything else —
dataset identity, checksums, adapter restore from a local copy, repo audit,
installer syntax, the installation verifier — is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rupsaa.release import dataset_sha256, read_checksums, sha256_file, verify_checksums, write_checksums

ROOT = Path(__file__).resolve().parent.parent
V01_SNAPSHOT = ROOT / "data/production/snapshots/rupsaa_v0.1_training"
V01_SHA = "2df533999559d5f873be9e5dc5350812e874dd18c8e4017741f5b8c18666fa2a"
ADAPTER = ROOT / "adapters/rupsaa-v0.1"


def _run(*cmd, cwd=ROOT):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True)


# --- dataset identity / checksums -----------------------------------------------------------

@pytest.mark.skipif(not V01_SNAPSHOT.exists(), reason="V0.1 snapshot not present")
def test_frozen_v01_dataset_sha256_reproduces():
    from rupsaa.release import snapshot_dataset_sha256

    n, sha = snapshot_dataset_sha256(V01_SNAPSHOT)
    assert (n, sha) == (858, V01_SHA)


def test_dataset_sha256_is_order_independent_and_content_sensitive():
    from rupsaa.dataset.schema import ConversationRecord

    a = ConversationRecord(id="rup-000001", messages=[{"role": "user", "content": "hi"}], created_at="t", updated_at="t")
    b = ConversationRecord(id="rup-000002", messages=[{"role": "user", "content": "yo"}], created_at="t", updated_at="t")
    before = dataset_sha256([a, b])
    assert before == dataset_sha256([b, a])
    b.messages[0]["content"] = "yo!"
    assert dataset_sha256([a, b]) != before


def test_checksum_roundtrip_and_mismatch(tmp_path):
    f1, f2 = tmp_path / "a.txt", tmp_path / "sub" / "b.bin"
    f2.parent.mkdir()
    f1.write_text("alpha")
    f2.write_bytes(b"\x00\x01")
    out = tmp_path / "checksums.sha256"
    entries = write_checksums([f1, f2], out, root=tmp_path)
    assert read_checksums(out) == entries == {"a.txt": sha256_file(f1), "sub/b.bin": sha256_file(f2)}
    assert verify_checksums(out, root=tmp_path) == []
    f1.write_text("tampered")
    f2.unlink()
    assert sorted(verify_checksums(out, root=tmp_path)) == ["checksum mismatch: a.txt", "missing: sub/b.bin"]


# --- release record for V0.1 ----------------------------------------------------------------------

def test_v01_release_record_is_consistent():
    manifest = json.loads((ROOT / "release/rupsaa-v0.1/manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_name"] == "rupsaa-v0.1" and manifest["base_model_id"] == "Qwen/Qwen2.5-7B-Instruct"
    t = manifest["training"]
    assert (t["lora_rank"], t["lora_alpha"]) == (16, 32)
    assert t["target_modules"] == sorted(["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    assert manifest["dataset"]["sha256"] == V01_SHA and manifest["dataset"]["splits"] == {"train": 772, "validation": 43, "test": 43}
    checks = read_checksums(ROOT / "release/rupsaa-v0.1/checksums.sha256")
    assert checks["adapters/rupsaa-v0.1/adapter_model.safetensors"] == manifest["adapter"]["adapter_model_sha256"]
    for key in checks:  # never records checkpoints/optimizer state/base weights
        assert "checkpoint-" not in key and "optimizer" not in key and "training_args.bin" not in key
    # frozen split + configs verify against the committed record
    assert verify_checksums(ROOT / "release/rupsaa-v0.1/checksums.sha256",
                            only_prefix="data/production/exports/rupsaa_v0.1/") == []


def test_release_whitelist_excludes_training_state(tmp_path):
    sys.path.insert(0, str(ROOT))
    from scripts.release_model import release_files, validate_adapter

    d = tmp_path / "adapter"
    (d / "checkpoint-50").mkdir(parents=True)
    for name in ("optimizer.pt", "training_args.bin", "tokenizer.json", "trainer_state.json"):
        (d / name).write_text("x")
    assert validate_adapter(d) == ["missing required file: adapter_config.json",
                                   "missing required file: adapter_model.safetensors"]
    (d / "adapter_config.json").write_text(json.dumps({"peft_type": "LORA", "base_model_name_or_path": "Qwen/x"}))
    (d / "adapter_model.safetensors").write_bytes(b"w")
    assert validate_adapter(d) == []
    assert sorted(p.name for p in release_files(d)) == ["adapter_config.json", "adapter_model.safetensors",
                                                        "trainer_state.json"]


# --- adapter restore -----------------------------------------------------------------------------

@pytest.mark.skipif(not (ADAPTER / "adapter_model.safetensors").exists(), reason="V0.1 adapter not present")
def test_fetch_adapter_restores_from_local_copy_and_verifies(tmp_path):
    dest = tmp_path / "restored"
    env_run = lambda *a: subprocess.run([sys.executable, "scripts/fetch_adapter.py", *a], cwd=ROOT,  # noqa: E731
                                        capture_output=True, text=True,
                                        env={**__import__("os").environ, "RUPSAA_ADAPTER_PATH": str(dest)})
    r = env_run("--check-only")
    assert r.returncode == 1
    r = env_run("--from-dir", str(ADAPTER))
    assert r.returncode == 0, r.stdout + r.stderr
    assert sha256_file(dest / "adapter_model.safetensors") == sha256_file(ADAPTER / "adapter_model.safetensors")
    assert not (dest / "checkpoint-100").exists() and not (dest / "optimizer.pt").exists()
    assert env_run("--check-only").returncode == 0
    (dest / "adapter_config.json").write_text("{}")  # tamper → detected
    assert env_run("--check-only").returncode == 1


def test_fetch_adapter_refuses_corrupt_source(tmp_path):
    src = tmp_path / "bad"
    src.mkdir()
    (src / "adapter_config.json").write_text("{}")
    (src / "adapter_model.safetensors").write_bytes(b"not the adapter")
    r = subprocess.run([sys.executable, "scripts/fetch_adapter.py", "--from-dir", str(src)], cwd=ROOT,
                       capture_output=True, text=True,
                       env={**__import__("os").environ, "RUPSAA_ADAPTER_PATH": str(tmp_path / "dest")})
    assert r.returncode != 0 and "NOT installed" in (r.stdout + r.stderr)
    assert not (tmp_path / "dest").exists()


def test_fetch_adapter_without_source_explains_what_is_missing(tmp_path):
    r = subprocess.run([sys.executable, "scripts/fetch_adapter.py"], cwd=ROOT, capture_output=True, text=True,
                       env={**__import__("os").environ, "RUPSAA_ADAPTER_PATH": str(tmp_path / "none"),
                            "RUPSAA_HF_REPO": ""})
    if r.returncode == 2:  # no hf_repo_id configured yet
        assert "hf_repo_id" in r.stderr and "--from-dir" in r.stderr


# --- repo audit ----------------------------------------------------------------------------------

def test_repo_audit_flags_secrets_and_forbidden_paths(tmp_path):
    sys.path.insert(0, str(ROOT))
    import scripts.repo_audit as ra

    fake_hf = "hf_" + "Ab3" * 12
    fake_gh = "ghp_" + "Zx9" * 12
    files = {
        "notes.md": f"token here {fake_hf}\n",
        "deploy.sh": f"export GH={fake_gh}\n",
        "app.env.example": "OWNER_API_KEY=\n",  # empty placeholder is fine
        "leak.example": "OWNER_API_KEY=Sup3rS3cretValue9\n",
        ".env": "X=1\n",
        "adapters/x/adapter_model.safetensors": "w",
        "cache/run.log": "log",
    }
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    ra.ROOT = tmp_path
    try:
        secrets, other = ra.audit(list(files))
    finally:
        ra.ROOT = ROOT
    joined = " ".join(secrets)
    assert "notes.md" in joined and "deploy.sh" in joined and "leak.example" in joined
    assert "app.env.example" not in joined
    assert fake_hf not in joined and fake_gh not in joined  # values never printed
    flagged = " ".join(other)
    assert ".env" in flagged and "adapter_model.safetensors" in flagged and "cache/run.log" in flagged


def test_repo_audit_passes_on_this_repository():
    r = _run(sys.executable, "scripts/repo_audit.py")
    assert r.returncode == 0, r.stdout


# --- installer / scripts ---------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["setup_rupsaa.sh", "scripts/sync_project.sh", "scripts/start_rupsaa_v01.sh",
                                    "scripts/setup_llamafactory.sh", "scripts/start_llamafactory_gui.sh"])
def test_shell_scripts_parse(script):
    assert _run("bash", "-n", script).returncode == 0


def test_verify_installation_passes_here():
    r = _run(sys.executable, "scripts/verify_installation.py",
             *([] if (ADAPTER / "adapter_model.safetensors").exists() else ["--no-adapter"]))
    assert r.returncode == 0, r.stdout[-3000:]
    assert "RUPSAA INSTALLATION VERIFIED" in r.stdout
