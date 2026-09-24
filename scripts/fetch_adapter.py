#!/usr/bin/env python3
"""Restore a Rupsaa LoRA adapter into the path the app expects and verify it.

    python scripts/fetch_adapter.py                       # current release from configs/release.yaml
    python scripts/fetch_adapter.py --release rupsaa-v0.1
    python scripts/fetch_adapter.py --from-dir /backup/rupsaa-v0.1   # offline restore from a copy
    python scripts/fetch_adapter.py --check-only          # just verify what's on disk

Resolution order for the source (first match wins):
  1. --from-dir DIR (a local copy of the adapter folder, e.g. an offline backup)
  2. the local adapter dir already present AND matching the release checksums → nothing to do
  3. Hugging Face: repo = $RUPSAA_HF_REPO or configs/release.yaml hf_repo_id,
     revision = $RUPSAA_HF_REVISION or the release's tag, files from the
     release's subfolder. Private repos need `hf auth login` (or $HF_TOKEN).

Destination: $RUPSAA_ADAPTER_PATH or the release's local_adapter_path
(adapters/rupsaa-v0.1). Every restored file is checked against
release/<name>/checksums.sha256; a mismatch is a hard failure and the
download is not moved into place. Only adapter files are downloaded —
never base-model weights.

Exit codes: 0 ok, 1 verification/download failure, 2 source not configured.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.release import ADAPTER_OPTIONAL_FILES, ADAPTER_REQUIRED_FILES, read_checksums, sha256_file  # noqa: E402


def release_config(name: str | None) -> tuple[str, dict, dict]:
    cfg = yaml.safe_load((PROJECT_ROOT / "configs/release.yaml").read_text(encoding="utf-8")) or {}
    name = name or cfg.get("current_release")
    rel = (cfg.get("releases") or {}).get(name)
    if not rel:
        sys.exit(f"Unknown release {name!r} in configs/release.yaml")
    return name, cfg, rel


def expected_adapter_checksums(rel: dict) -> tuple[str, dict[str, str]]:
    """{filename: sha256} for the adapter files of this release."""
    checks = read_checksums(PROJECT_ROOT / rel["checksums"])
    prefix = rel["local_adapter_path"].rstrip("/") + "/"
    return prefix, {k[len(prefix):]: v for k, v in checks.items() if k.startswith(prefix)}


def verify_dir(directory: Path, expected: dict[str, str]) -> list[str]:
    problems = []
    for fname in ADAPTER_REQUIRED_FILES:
        if not (directory / fname).is_file():
            problems.append(f"missing required file {fname}")
    for fname, digest in expected.items():
        p = directory / fname
        if not p.is_file():
            if fname in ADAPTER_REQUIRED_FILES:
                continue  # already reported
            problems.append(f"missing {fname}")
        elif sha256_file(p) != digest:
            problems.append(f"checksum mismatch: {fname}")
    return problems


def install(src: Path, dest: Path, expected: dict[str, str]) -> None:
    """Copy verified files into dest atomically-ish (staging dir + rename per file).
    Never deletes other files in dest (e.g. local checkpoints)."""
    problems = verify_dir(src, expected)
    if problems:
        sys.exit("Source adapter failed verification — NOT installed:\n  " + "\n  ".join(problems))
    dest.mkdir(parents=True, exist_ok=True)
    for fname in expected:
        tmp = dest / f".{fname}.partial"
        shutil.copy2(src / fname, tmp)
        tmp.replace(dest / fname)


def download_from_hub(repo: str, revision: str, subfolder: str, files: list[str], workdir: Path) -> Path:
    from huggingface_hub import hf_hub_download
    from huggingface_hub.utils import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

    out = workdir / "download"
    out.mkdir()
    for fname in files:
        try:
            path = hf_hub_download(repo_id=repo, filename=f"{subfolder}/{fname}" if subfolder else fname,
                                   revision=revision, local_dir=str(out))
        except (RepositoryNotFoundError, GatedRepoError):
            sys.exit(f"Cannot access Hugging Face repo {repo!r} (revision {revision!r}). If it is private, run "
                     f"`hf auth login` with an account that can read it, then re-run setup.")
        except HfHubHTTPError as e:
            sys.exit(f"Download of {fname} from {repo}@{revision} failed: {e}")
        final = out / fname
        if Path(path) != final:
            shutil.move(path, final)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--release")
    ap.add_argument("--from-dir", type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="re-download even if the local copy verifies")
    args = ap.parse_args()

    name, cfg, rel = release_config(args.release)
    _, expected = expected_adapter_checksums(rel)
    dest = Path(os.environ.get("RUPSAA_ADAPTER_PATH") or rel["local_adapter_path"])
    dest = dest if dest.is_absolute() else PROJECT_ROOT / dest
    print(f"[fetch_adapter] release {name} → {dest}")

    local_problems = verify_dir(dest, expected) if dest.exists() else ["not present"]
    if args.check_only:
        if local_problems:
            print("  NOT OK: " + "; ".join(local_problems))
            sys.exit(1)
        print(f"  OK: {len(expected)} files match release checksums")
        return

    if args.from_dir:
        install(args.from_dir.resolve(), dest, expected)
        print(f"  restored from {args.from_dir} and verified ({len(expected)} files)")
        return

    if not local_problems and not args.force:
        print(f"  already present and verified ({len(expected)} files) — nothing to download")
        return

    repo = os.environ.get("RUPSAA_HF_REPO") or cfg.get("hf_repo_id")
    if not repo:
        print("  Adapter not present locally and no Hugging Face repo configured.\n"
              "  Set hf_repo_id in configs/release.yaml (or export RUPSAA_HF_REPO=<user>/<repo>),\n"
              "  or restore from a local copy: python scripts/fetch_adapter.py --from-dir <dir>", file=sys.stderr)
        sys.exit(2)
    revision = os.environ.get("RUPSAA_HF_REVISION") or rel.get("revision") or "main"
    subfolder = rel.get("subfolder", "")
    files = [f for f in ADAPTER_REQUIRED_FILES + ADAPTER_OPTIONAL_FILES if f in expected]
    print(f"  downloading {len(files)} adapter file(s) from {repo}@{revision}/{subfolder} (no base-model weights)")
    with tempfile.TemporaryDirectory() as tmp:
        src = download_from_hub(repo, revision, subfolder, files, Path(tmp))
        install(src, dest, expected)
    print(f"  downloaded and verified ({len(expected)} files)")


if __name__ == "__main__":
    main()
