#!/usr/bin/env bash

# Exit on first error (-e), treat unset variables as errors (-u),
# and make pipeline failures bubble up (-o pipefail).
set -euo pipefail

# Quick glossary for this script:
# - cron: Linux scheduler that runs commands at set times.
# - crontab: The list of scheduled cron entries for a user.
# - mode: User-selected behavior (immediate/hourly/custom/remove/show).
# - --run-once: Internal mode used by cron to execute one job.

# Resolve script directory so all file paths remain stable regardless of cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Main output artifacts for cron-driven runs.
REPORT_FILE="$SCRIPT_DIR/task_report.json"
LOG_FILE="$SCRIPT_DIR/task_report.log"
LOG_ARCHIVE_DIR="$SCRIPT_DIR/automation_logs"

# Task name requested from orchestrator when this script runs jobs.
TASK_NAME="update_upgrade"

# Human-readable command string kept for compatibility/reference.
RUN_CMD="cd \"$SCRIPT_DIR\" && python3 orchestrator.py --hosts all --tasks $TASK_NAME --report-file \"$REPORT_FILE\""

# Cron entry executes this script in internal one-shot mode.
CMD="bash \"$SCRIPT_DIR/setup_update_cron.sh\" --run-once"

usage() {
  # Print usage documentation and exit behavior for each mode.
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
  # Interactive/manual entrypoint for running the task now.
  echo "Running $TASK_NAME immediately across all hosts..."
  run_once
}

run_once() {
  # Execute one orchestrator run and keep both latest + timestamped logs.
  mkdir -p "$LOG_ARCHIVE_DIR"
  ARCHIVE_LOG_FILE="$LOG_ARCHIVE_DIR/task_report_$(date +"%Y-%m-%d_%H-%M-%S").log"
  {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron job started"
    cd "$SCRIPT_DIR" && python3 orchestrator.py --hosts all --tasks "$TASK_NAME" --report-file "$REPORT_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Cron job finished"
  } 2>&1 | tee "$ARCHIVE_LOG_FILE" > "$LOG_FILE"
}

validate_cron() {
  # Validate custom cron expressions using a conservative numeric pattern.
  local expr="$1"
  local -a fields=()
  read -r -a fields <<< "$expr"

  if [ "${#fields[@]}" -ne 5 ]; then
    echo "ERROR: Invalid cron expression '$expr'. Must have exactly 5 fields (e.g. '0 */2 * * *')." >&2
    exit 1
  fi

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
  # Persist cron table preserving existing non-empty entries.
  local new_entry="$1"
  if [ -n "$existing" ]; then
    printf '%s\n%s\n' "$existing" "$new_entry" | awk 'NF' | crontab -
  else
    printf '%s\n' "$new_entry" | crontab -
  fi
}

# Default mode is immediate when no argument is provided.
if [ "$#" -eq 0 ]; then
  MODE="immediate"
else
  MODE="$1"
fi

# Standard help switch handling.
if [ "$MODE" = "--help" ] || [ "$MODE" = "-h" ]; then
  usage
  exit 0
fi

# Internal entrypoint used by cron to run one execution.
if [ "$MODE" = "--run-once" ]; then
  run_once
  exit 0
fi

# Remove matching cron entries for this automation command.
if [ "$MODE" = "remove" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  filtered=$(printf '%s\n' "$existing" | grep -vF "$CMD" || true)
  printf '%s\n' "$filtered" | awk 'NF' | crontab -
  echo "Removed $TASK_NAME cron job."
  exit 0
fi

# Display matching cron entries only.
if [ "$MODE" = "show" ]; then
  existing=$(crontab -l 2>/dev/null || true)
  printf '%s\n' "$existing" | grep -F "$CMD" || echo "No $TASK_NAME cron job found."
  exit 0
fi

# Resolve scheduler mode into a cron expression.
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

# Compose final cron line: schedule + command.
CRON_ENTRY="$CRON_SCHEDULE $CMD"
existing=$(crontab -l 2>/dev/null || true)
existing_entries=$(printf '%s\n' "$existing" | grep -F "$CMD" || true)

# If an entry exists, ask before replacing it.
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

# No conflicts: install new schedule.
write_crontab "$CRON_ENTRY"
echo "Installed cron job: $CRON_ENTRY"
echo "Log file: $LOG_FILE"
