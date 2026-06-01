#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="$SCRIPT_DIR/task_report.json"
LOG_FILE="$SCRIPT_DIR/task_report.log"
CMD="cd \"$SCRIPT_DIR\" && python3 orchestrator.py --hosts all --tasks system_update --report-file \"$REPORT_FILE\""

usage() {
  cat <<'EOF'
Usage: setup_update_cron.sh [mode]

Install a cron job to run system_update across all hosts.

Modes:
  3day      Install schedule for every 3 days at 03:00 (default)
  hourly    Install schedule for every hour on the hour
  custom    Install a custom cron schedule; provide the full cron expression afterwards
  remove    Remove the existing system_update cron job
  show      Display the currently installed system_update cron entry

Examples:
  ./setup_update_cron.sh 3day
  ./setup_update_cron.sh hourly
  ./setup_update_cron.sh custom "0 */2 * * *"
  ./setup_update_cron.sh remove
  ./setup_update_cron.sh show

The job writes the latest JSON report to task_report.json and appends stdout/stderr to task_report.log.
EOF
}

if [ "$#" -eq 0 ]; then
  MODE="3day"
else
  MODE="$1"
fi

if [ "$MODE" = "--help" ] || [ "$MODE" = "-h" ]; then
  usage
  exit 0
fi

if [ "$MODE" = "remove" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  filtered=$(printf '%s\n' "$existing" | grep -vF "$CMD >> \"$LOG_FILE\" 2>&1")
  printf '%s\n' "$filtered" | crontab -
  echo "Removed system_update cron job."
  exit 0
fi

if [ "$MODE" = "show" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  printf '%s\n' "$existing" | grep -F "$CMD" || true
  exit 0
fi

if [ "$MODE" = "3day" ]; then
  CRON_SCHEDULE="0 3 */3 * *"
elif [ "$MODE" = "hourly" ]; then
  CRON_SCHEDULE="0 * * * *"
elif [ "$MODE" = "custom" ]; then
  if [ "$#" -lt 2 ]; then
    echo "ERROR: custom mode requires a cron expression argument." >&2
    usage
    exit 1
  fi
  shift
  CRON_SCHEDULE="$*"
else
  echo "ERROR: Unknown mode '$MODE'" >&2
  usage
  exit 1
fi

CRON_ENTRY="$CRON_SCHEDULE $CMD >> \"$LOG_FILE\" 2>&1"
existing=$(crontab -l 2>/dev/null || true)
existing_entries=$(printf '%s\n' "$existing" | grep -F "$CMD" || true)

if [ -n "$existing_entries" ]; then
  echo "Existing system_update cron job(s) found:"
  printf '%s\n' "$existing_entries"
  echo
  read -r -p "Replace existing system_update cron job(s) with new schedule '$CRON_SCHEDULE'? [y/N] " answer
  case "${answer,,}" in
    y|yes)
      filtered=$(printf '%s\n' "$existing" | grep -vF "$CMD" || true)
      printf '%s\n%s\n' "$filtered" "$CRON_ENTRY" | crontab -
      echo "Replaced existing system_update cron job with: $CRON_ENTRY"
      echo "Log file: $LOG_FILE"
      exit 0
      ;;
    *)
      echo "Aborted; existing system_update cron job retained."
      exit 0
      ;;
  esac
fi

printf '%s\n%s\n' "$existing" "$CRON_ENTRY" | crontab -
echo "Installed cron job: $CRON_ENTRY"
echo "Log file: $LOG_FILE"
