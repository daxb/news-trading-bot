#!/usr/bin/env bash
# fly_diag.sh — read-only Fly.io diagnostics for FIONA.
#
# Bundles the recurring read-only health checks into one auditable surface
# so they can be allowlisted once instead of prompting per ad-hoc command.
# Contains NO mutating operations (no deploy, no secrets, no reset_bot.py).
#
# Usage:
#   scripts/fly_diag.sh            full snapshot (status + machines + mem + recent logs)
#   scripts/fly_diag.sh status     app status + machine list
#   scripts/fly_diag.sh logs       recent logs (no tail)
#   scripts/fly_diag.sh mem        memory + top RSS processes + OOM check
#   scripts/fly_diag.sh audit [H]  run_audit.py over last H hours (default 48)
#
# App name is read from fly.toml so it never goes stale.

set -euo pipefail

cd "$(dirname "$0")/.."
APP="$(grep -E "^app" fly.toml | head -1 | sed -E "s/^app *= *['\"]?([^'\"]+)['\"]?.*/\1/")"

if [[ -z "${APP:-}" ]]; then
  echo "ERROR: could not read app name from fly.toml" >&2
  exit 1
fi

bar() { echo; echo "=== $1 ==="; }

cmd_status() {
  bar "flyctl status ($APP)"
  flyctl status -a "$APP"
  bar "machine list"
  flyctl machine list -a "$APP"
}

cmd_logs() {
  bar "recent logs (no tail)"
  flyctl logs -a "$APP" --no-tail
}

cmd_mem() {
  bar "memory snapshot"
  flyctl ssh console -a "$APP" --command \
    "free -m && echo '--- top RSS ---' && ps aux --sort=-rss | head -8 && echo '--- recent OOM ---' && (dmesg 2>/dev/null | grep -i 'killed process\|out of memory' | tail -5 || echo 'none')"
}

cmd_audit() {
  local hours="${1:-48}"
  bar "audit report (last ${hours}h)"
  flyctl ssh console -a "$APP" --command "python /app/scripts/run_audit.py --hours ${hours}"
}

case "${1:-all}" in
  status) cmd_status ;;
  logs)   cmd_logs ;;
  mem)    cmd_mem ;;
  audit)  cmd_audit "${2:-48}" ;;
  all)    cmd_status; cmd_mem; cmd_logs ;;
  *) echo "Unknown subcommand: $1" >&2
     echo "Use: status | logs | mem | audit [hours] | all" >&2
     exit 1 ;;
esac
