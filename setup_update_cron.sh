#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="$SCRIPT_DIR/task_report.json"
LOG_FILE="$SCRIPT_DIR/task_report.log"
LOG_ARCHIVE_DIR="$SCRIPT_DIR/automation_logs"
TASK_NAME="update_upgrade"
RUN_CMD="cd \"$SCRIPT_DIR\" && python3 orchestrator.py --hosts all --tasks $TASK_NAME --report-file \"$REPORT_FILE\""
CMD="bash \"$SCRIPT_DIR/setup_update_cron.sh\" --run-once"

usage() {
  cat <<'EOF'
Usage: setup_update_cron.sh [mode]
Run update_upgrade across all hosts immediately, or install a cron job when a mode is provided.
Modes:
  immediate Run update_upgrade immediately across all hosts (default)
  3day      Install schedule for every 3 days at 03:00
  hourly    Install schedule for every hour on the hour
  custom    Install a custom cron schedule; provide the full cron expression afterwards
  remove    Remove the existing update_upgrade cron job
  show      Display the currently installed update_upgrade cron entry
Examples:
  ./setup_update_cron.sh
  ./setup_update_cron.sh immediate
  ./setup_update_cron.sh 3day
  ./setup_update_cron.sh hourly
  ./setup_update_cron.sh custom "0 */2 * * *"
  ./setup_update_cron.sh remove
  ./setup_update_cron.sh show
The job writes the latest JSON report to task_report.json.
Latest cron output is saved to task_report.log, and timestamped archived logs are stored in automation_logs/.
EOF
}

run_immediate() {
  echo "Running $TASK_NAME immediately across all hosts..."
  run_once
}

run_once() {
  mkdir -p "$LOG_ARCHIVE_DIR"
  ARCHIVE_LOG_FILE="$LOG_ARCHIVE_DIR/task_report_$(date +"%Y-%m-%d_%H-%M-%S").log"
  {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron job started"
    cd "$SCRIPT_DIR" && python3 orchestrator.py --hosts all --tasks "$TASK_NAME" --report-file "$REPORT_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron job finished"
  } 2>&1 | tee "$ARCHIVE_LOG_FILE" > "$LOG_FILE"
}

validate_cron() {
  local expr="$1"
  local -a fields=()
  read -r -a fields <<< "$expr"

  if [ "${#fields[@]}" -ne 5 ]; then
    echo "ERROR: Invalid cron expression '$expr'. Must have exactly 5 fields (e.g. '0 */2 * * *')." >&2
    exit 1
  fi

  # Validate each field against allowed numeric cron formats
  local field
  local i=1
  for field in "${fields[@]}"; do
    if ! echo "$field" | grep -qE '^((\*|\*\/[0-9]+|[0-9]+(-[0-9]+)?)(\/[0-9]+)?)(,((\*|\*\/[0-9]+|[0-9]+(-[0-9]+)?)(\/[0-9]+)?))*$'; then
      echo "ERROR: Invalid value '$field' in field $i of cron expression." >&2
      exit 1
    fi
    i=$((i + 1))
  done
}

write_crontab() {
  local new_entry="$1"
  if [ -n "$existing" ]; then
    printf '%s\n%s\n' "$existing" "$new_entry" | awk 'NF' | crontab -
  else
    printf '%s\n' "$new_entry" | crontab -
  fi
}

if [ "$#" -eq 0 ]; then
  MODE="immediate"
else
  MODE="$1"
fi

if [ "$MODE" = "--help" ] || [ "$MODE" = "-h" ]; then
  usage
  exit 0
fi

if [ "$MODE" = "--run-once" ]; then
  run_once
  exit 0
fi

if [ "$MODE" = "remove" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  filtered=$(printf '%s\n' "$existing" | grep -vF "$CMD" || true)
  printf '%s\n' "$filtered" | awk 'NF' | crontab -
  echo "Removed $TASK_NAME cron job."
  exit 0
fi

if [ "$MODE" = "show" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  printf '%s\n' "$existing" | grep -F "$CMD" || echo "No $TASK_NAME cron job found."
  exit 0
fi

if [ "$MODE" = "immediate" ]; then
  run_immediate
  exit 0
elif [ "$MODE" = "3day" ]; then
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
  validate_cron "$CRON_SCHEDULE"
else
  echo "ERROR: Unknown mode '$MODE'" >&2
  usage
  exit 1
fi

CRON_ENTRY="$CRON_SCHEDULE $CMD"
existing=$(crontab -l 2>/dev/null || true)
existing_entries=$(printf '%s\n' "$existing" | grep -F "$CMD" || true)

if [ -n "$existing_entries" ]; then
  echo "Existing $TASK_NAME cron job(s) found:"
  printf '%s\n' "$existing_entries"
  echo
  read -r -p "Replace existing $TASK_NAME cron job(s) with new schedule '$CRON_SCHEDULE'? [y/N] " answer
  case "${answer,,}" in
    y|yes)
      filtered=$(printf '%s\n' "$existing" | grep -vF "$CMD" || true)
      existing="$filtered"
      write_crontab "$CRON_ENTRY"
      echo "Replaced existing $TASK_NAME cron job with: $CRON_ENTRY"
      echo "Log file: $LOG_FILE"
      exit 0
      ;;
    *)
      echo "Aborted; existing $TASK_NAME cron job retained."
      exit 0
      ;;
  esac
fi

write_crontab "$CRON_ENTRY"
echo "Installed cron job: $CRON_ENTRY"
echo "Log file: $LOG_FILE"
