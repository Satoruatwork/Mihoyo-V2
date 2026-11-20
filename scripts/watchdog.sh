#!/usr/bin/env bash
#
# Watchdog: ensure the bot daemon is running; relaunch (detached) if not.
#
# Safe to run repeatedly. run_local.sh holds a flock, so even a racing double
# launch can never create two pollers. Prints a line only when it takes action.
#
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="/tmp/mihoyo_bot.log"

if pgrep -f "python -m bot\.main" >/dev/null 2>&1; then
  # Already running — nothing to do.
  exit 0
fi

echo "[watchdog] bot not running; relaunching at $(date -u +%H:%M:%SZ)" >> "$LOG"
cd "$REPO_ROOT" || exit 1
setsid nohup bash "$REPO_ROOT/scripts/run_local.sh" >> "$LOG" 2>&1 < /dev/null &
echo "restarted"
