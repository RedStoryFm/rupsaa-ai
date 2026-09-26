#!/usr/bin/env bash
# Restore owner knowledge from a backup made by scripts/backup_knowledge.sh.
# Always takes a fresh safety backup of the CURRENT state first. Restart Rupsaa afterwards is not
# required for terminology/dance (read live from disk); rebuild the RAG index if documents changed.
#
# Usage: bash scripts/restore_knowledge.sh backups/rupsaa-knowledge-<stamp>.tar.gz --yes
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ARCHIVE="${1:?usage: restore_knowledge.sh <archive.tar.gz> --yes}"
[ -f "$ARCHIVE" ] || { echo "no such archive: $ARCHIVE" >&2; exit 1; }
if [ -f "$ARCHIVE.sha256" ]; then sha256sum -c "$ARCHIVE.sha256" >/dev/null || { echo "checksum mismatch" >&2; exit 1; }; fi
# Only the expected directories may be written (no absolute paths / .. in the archive).
BAD="$(tar -tzf "$ARCHIVE" | grep -vE '^(knowledge/(documents|terminology|dance)|data/production/drafts)(/|$)' || true)"
[ -z "$BAD" ] || { echo "archive contains unexpected paths:"; echo "$BAD"; exit 1; } >&2
[ "${2:-}" = "--yes" ] || { echo "dry run — archive is valid. Re-run with --yes to restore (a safety backup is taken first)."; exit 0; }
bash scripts/backup_knowledge.sh "$ROOT/backups/pre-restore"
tar -xzf "$ARCHIVE" -C "$ROOT"
echo "restored from $ARCHIVE"
