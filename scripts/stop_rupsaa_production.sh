#!/usr/bin/env bash
# Stop a Rupsaa production instance started by scripts/start_rupsaa_production.sh (clean SIGTERM).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDFILE="$ROOT/run/rupsaa-production.pid"
[ -f "$PIDFILE" ] || { echo "no production pid file — nothing to stop"; exit 0; }
PID="$(cat "$PIDFILE")"
if ! kill -0 "$PID" 2>/dev/null; then echo "pid $PID not running; removing stale pid file"; rm -f "$PIDFILE"; exit 0; fi
# The launcher's python child (start_rupsaa.py) handles SIGTERM and stops uvicorn + web proxy.
CHILD="$(pgrep -P "$PID" -f start_rupsaa.py || true)"
kill -TERM "${CHILD:-$PID}"
for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
kill -0 "$PID" 2>/dev/null && { echo "still running after 30 s — sending SIGKILL"; kill -KILL "$PID"; }
rm -f "$PIDFILE"
echo "Rupsaa production stopped."
