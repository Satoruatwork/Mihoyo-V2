#!/usr/bin/env bash
#
# Local supervised runner for temporary testing.
#
# Runs the bot and auto-restarts it if it crashes, so a transient error doesn't
# silently take the bot down during a testing session. Not a production deployment
# tool — for real hosting use systemd / a container / a process manager.
#
# Usage:  ./scripts/run_local.sh
# Stop:   Ctrl+C, or `pkill -f "bot.main"`
#
set -u

# Resolve repo root regardless of where the script is invoked from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Activate the virtualenv if present.
if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

RESTART_DELAY="${RESTART_DELAY:-3}"
LOCK_FILE="${LOCK_FILE:-/tmp/mihoyo_bot.lock}"

# Single-instance guard: only one supervisor may run at a time. A second launch
# exits immediately instead of starting a duplicate poller (which Telegram rejects
# with a Conflict error).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[supervisor] another instance already holds $LOCK_FILE; exiting"
  exit 0
fi
echo $$ > /tmp/mihoyo_bot.pid

echo "[supervisor] repo=$REPO_ROOT restart_delay=${RESTART_DELAY}s"
while true; do
  echo "[supervisor] starting bot"
  python -m bot.main
  code=$?
  # Clean exit (0) or SIGINT (130) -> stop supervising.
  if [[ "$code" -eq 0 || "$code" -eq 130 ]]; then
    echo "[supervisor] bot exited cleanly (code=$code); not restarting"
    break
  fi
  echo "[supervisor] bot crashed (code=$code); restarting in ${RESTART_DELAY}s"
  sleep "$RESTART_DELAY"
done
