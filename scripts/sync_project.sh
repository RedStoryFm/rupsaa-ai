#!/usr/bin/env bash
# Safe GitHub sync for Rupsaa. Never pushes unless you ask, never force-pushes.
#
#   bash scripts/sync_project.sh                      # status + tests + audits (read-only)
#   bash scripts/sync_project.sh --commit "message"   # …then stage everything not ignored and commit
#   bash scripts/sync_project.sh --push               # …then push the current branch (asks to confirm)
#   bash scripts/sync_project.sh --commit "msg" --push --yes   # non-interactive confirm
#   add --skip-tests to skip pytest
#
# Pushing requires a configured remote (git remote add origin <url>) and
# GitHub authentication (gh auth login, or a credential helper). No
# credentials are stored or printed by this script.

set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${RUPSAA_PYTHON:-python3}"

COMMIT_MSG="" DO_PUSH=0 YES=0 SKIP_TESTS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --commit) COMMIT_MSG="${2:?--commit needs a message}"; shift 2 ;;
    --push) DO_PUSH=1; shift ;;
    --yes) YES=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
die() { echo "SYNC STOPPED: $*" >&2; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "== Repository: $ROOT"
echo "   branch: $BRANCH   head: $(git log -1 --format='%h %s' 2>/dev/null || echo '(no commits)')"
echo "   remotes: $(git remote -v | awk '{print $1" "$2}' | sort -u | tr '\n' ';' || true)"
echo
echo "== Pending changes"
git status --short | awk '{print $1}' | sort | uniq -c | sed 's/^/   /'
echo "   ($(git status --short | wc -l) paths — full list: git status)"

if [ "$SKIP_TESTS" = "0" ]; then
  echo; echo "== Unit tests"
  GRADIO_ANALYTICS_ENABLED=False "$PY" -m pytest -q -p no:cacheprovider | tail -2 || die "tests failed"
fi

echo; echo "== Secret / large-file / forbidden-path audit (files git would commit)"
"$PY" scripts/repo_audit.py || die "audit failed — fix the listed files or add them to .gitignore"

if [ -n "$COMMIT_MSG" ]; then
  echo; echo "== Commit"
  git add -A
  "$PY" scripts/repo_audit.py --staged || { git reset -q; die "staged audit failed — nothing committed"; }
  git diff --cached --stat | tail -3
  git commit -q -m "$COMMIT_MSG" && echo "   committed $(git rev-parse --short HEAD)"
fi

if [ "$DO_PUSH" = "1" ]; then
  echo; echo "== Push"
  REMOTE="$(git config "branch.$BRANCH.remote" || git remote | head -1 || true)"
  [ -n "$REMOTE" ] || die "no git remote configured — run: git remote add origin <your GitHub repo URL>"
  URL="$(git remote get-url "$REMOTE")"
  if [ "$YES" != "1" ]; then
    read -r -p "   Push branch '$BRANCH' (and tags) to $REMOTE ($URL)? [y/N] " ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "push cancelled"
  fi
  git push "$REMOTE" "$BRANCH"          # never --force
  git push "$REMOTE" --tags             # new tags only; existing remote tags are never overwritten
  echo "   pushed $BRANCH to $REMOTE"
fi
echo; echo "Done."
