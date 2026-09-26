#!/usr/bin/env bash
# Back up everything the owner edits at runtime (no secrets, no model weights):
#   knowledge/documents  knowledge/terminology  knowledge/dance  data/production/drafts (Teach Rupsaa)
# The RAG index (knowledge/index) is NOT included — rebuild it with scripts/ingest_knowledge.py.
#
# Usage: bash scripts/backup_knowledge.sh [dest_dir]      (default: backups/)
# Copy the archive OFF the server (it is the only copy of owner edits made since the last git commit).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEST="${1:-$ROOT/backups}"
mkdir -p "$DEST"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$DEST/rupsaa-knowledge-$STAMP.tar.gz"
PATHS=()
for p in knowledge/documents knowledge/terminology knowledge/dance data/production/drafts; do
  [ -e "$p" ] && PATHS+=("$p")
done
tar -czf "$OUT" "${PATHS[@]}"
sha256sum "$OUT" > "$OUT.sha256"
echo "backup: $OUT"
echo "  $(tar -tzf "$OUT" | grep -c 'term-.*\.json$') terminology · $(tar -tzf "$OUT" | grep -c 'dance-.*\.json$') dance · $(tar -tzf "$OUT" | grep -c '^knowledge/documents/.\+') documents"
