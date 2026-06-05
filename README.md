# Linux Automation Orchestrator

A Python-based orchestration system for managing dynamic task execution across multiple Linux hosts. Supports predefined execution profiles, host tagging, task applicability rules, and detailed JSON reporting with emulation modes for testing.

## Features

- **Execution Profiles**: Predefined task workflows targeting specific host groups via tags
- **Host Tagging**: Organize hosts by environment (production/non-production), function (docker, dns), and other attributes
- **Task Applicability**: Smart task routing (e.g., docker checks only run on docker-enabled hosts, skipped elsewhere)
- **Multiple Execution Modes**:
  - Real execution with SSH/local command execution
  - Dry-run planning (resolution without execution)
  - Emulate-success mode (applicable tasks pass, non-applicable skip)
  - Emulate-all-passed mode (all selected tasks pass, useful for UI testing)
- **Interactive and CLI Modes**: Choose between profile-based, manual host/task selection, or interactive menu
- **JSON Reporting**: Comprehensive reports with per-host, per-task status, timestamps, and execution metadata
- **Report Archiving**: Automatic timestamped archival of previous reports
- **Cron Integration**: Shell script for scheduling automated runs

## Project Structure

```
.
├── orchestrator.py          # Main entry point for task orchestration
├── execution.py             # SSH/local command execution logic
├── models.py                # Data models (HostIdentity, HostRunResult)
├── selection.py             # Host filtering, profile loading, task validation
├── task_playbook.py         # Task implementations (maint, health checks, docker)
├── inventory.py             # Host inventory loader
├── reporting.py             # Report generation and archiving
├── hosts.json               # Host inventory with tags
├── profiles.json            # Predefined execution profiles
├── setup_update_cron.sh     # Cron scheduling utility
└── archives/                # Archived reports and older code
```

## Installation

### Prerequisites

- Python 3.7+
- SSH access to target Linux hosts (for real execution mode)
- Passwordless sudo configured on remote hosts (if needed for privileged tasks)

### Setup

1. Clone or download the repository.
2. Ensure Python dependencies are available (standard library only).
3. Configure `hosts.json` with your host inventory.
4. Customize `profiles.json` for your operational workflows.

## Configuration

### hosts.json

Define your host inventory with optional tags:

```json
{
  "hosts": [
    {
      "name": "ubuntu.horizon.local",
      "ip": "192.168.50.150",
      "description": "DMZ VM for public services and docker",
      "username": "automator",
      "tags": ["production", "docker", "dmz"]
    },
    {
      "name": "pi.hole",
      "ip": "192.168.0.233",
      "description": "Raspberry pi DNS filter",
      "username": "automator",
      "tags": ["production", "dns"]
    }
  ]
}
```

**Tag conventions:**
- Environment: `production`, `non-production`, `lab`, `dev`
- Function: `docker`, `dns`, `hypervisor`, `automation`
- Criticality: `critical`, `non-critical`

### profiles.json

Define reusable execution profiles:

```json
{
  "profiles": {
    "prod-maintenance": {
      "description": "Run regular maintenance on production hosts",
      "host_query": "tags:production",
      "tasks": ["regular_maint"],
      "timeout": 600
    },
    "docker-health": {
      "description": "Check docker container health",
      "host_query": "tags:docker",
      "tasks": ["docker_healthcheck"],
      "timeout": 600
    }
  }
}
```

**host_query syntax:**
- `"all"` — select all hosts
- `"tags:production"` — hosts with `production` tag
- `"tags:docker,tags:critical"` — hosts with `docker` OR `critical` tag (OR logic)

## Usage

### List Available Profiles

```bash
python3 orchestrator.py --list-profiles
```

Output shows all profiles with descriptions and target queries.

### Profile-Based Execution

```bash
# Run a predefined profile
python3 orchestrator.py --profile prod-maintenance

# Preview without execution
python3 orchestrator.py --profile prod-maintenance --dry-run

# Emulate success (applicable tasks pass, non-applicable skip)
python3 orchestrator.py --profile full-health --emulate-success

# Emulate all passed (all tasks pass for all hosts, testing only)
python3 orchestrator.py --profile full-health --emulate-all-passed
```

### Manual Host/Task Selection (Legacy Mode)

```bash
# Select hosts by name/IP, tasks by name
python3 orchestrator.py --hosts ubuntu,pi.hole --tasks regular_maint,docker_healthcheck

# Run all hosts, all tasks
python3 orchestrator.py --hosts all --tasks all

# Combine with emulation
python3 orchestrator.py --hosts ubuntu --tasks docker_healthcheck --emulate-success
```

### Interactive Mode

```bash
python3 orchestrator.py
```

Menu shows available profiles with option to select custom hosts/tasks manually.

### Additional Options

- `--timeout SECONDS` — override default timeout (default: 600)
- `--hosts-file PATH` — custom hosts inventory (default: hosts.json)
- `--profiles-file PATH` — custom profiles file (default: profiles.json)
- `--report-file PATH` — custom report output (default: task_report.json)

## Built-in Tasks

### regular_maint
- Runs `apt-get update && upgrade`, cleanup, and journal maintenance
- Requires passwordless sudo for non-root users
- Status: **passed** if all operations succeed

### system_healthcheck
- Collects CPU usage, memory, DNS response time, packet loss, network latency
- Generates detailed health report in output and JSON
- Status: **passed** if data collection succeeds (N/A values are acceptable)

### docker_healthcheck
- Lists Docker containers and their status
- Detects unhealthy/exited/dead containers
- Auto-restarts docker service if unhealthy containers found
- **Applicability**: Only runs on hosts tagged `docker`; skipped elsewhere
- Status: **passed** if containers are healthy or service recovered

## Execution Modes

### Real Mode (default)
- Connects to hosts via SSH (or local shell if host is local)
- Executes actual commands and collects output
- Generates real operational report
- `run_mode: "real"` in report summary

### Dry-Run Mode (`--dry-run`)
- Resolves host selection and task list
- Prints execution plan (hosts, tasks, timeout)
- Does not connect or execute
- Exits after plan display

### Emulate-Success Mode (`--emulate-success`)
- Skips host connectivity and SSH
- Marks applicable tasks as passed
- Marks non-applicable tasks as skipped (e.g., docker check on non-docker hosts)
- Generates full report with correct skip/pass semantics
- `run_mode: "emulate_success"` in report summary
- **Use case**: Testing report generation in restricted environments

### Emulate-All-Passed Mode (`--emulate-all-passed`)
- Skips host connectivity and SSH
- Marks all selected tasks as passed for all selected hosts
- Ignores task applicability rules
- Generates full report
- `run_mode: "emulate_all_passed"` in report summary
- **Use case**: UI testing, demo workflows, full-pass scenarios

## Reports

Reports are JSON files saved to `task_report.json` (default):

```json
{
  "summary": {
    "total_hosts": 4,
    "passed": 4,
    "failed": 0,
    "started_at": "2026-06-05T14:00:00.000000",
    "finished_at": "2026-06-05T14:00:05.000000",
    "run_mode": "real"
  },
  "hosts": [
    {
      "name": "ubuntu.horizon.local",
      "ip": "192.168.50.150",
      "status": "passed",
      "tasks": [
        {
          "task": "system_healthcheck",
          "status": "passed",
          "checks": {
            "cpu_usage": "15.3%",
            "memory_usage": "2.45 / 8.00 GB",
            "dns_response_time": "45.2 ms",
            "packet_loss": "0%",
            "latency": "12.5 ms"
          }
        }
      ]
    }
  ]
}
```

**Status values:**
- `"passed"` — task or host succeeded
- `"failed"` — task or host encountered an error
- `"skipped"` — task not applicable to host (e.g., docker check on non-docker host)

**Host-level status:**
- `"passed"` if all tasks are passed or skipped
- `"failed"` if any task is failed

Previous reports are automatically archived in `reports_archive/` with timestamps.

## Cron Scheduling

Use `setup_update_cron.sh` to schedule automated runs:

```bash
# Run immediately
bash setup_update_cron.sh

# Schedule every 3 days at 03:00
bash setup_update_cron.sh 3day

# Schedule every hour
bash setup_update_cron.sh hourly

# Schedule with custom cron expression
bash setup_update_cron.sh custom "0 2 * * *"

# Remove existing scheduled job
bash setup_update_cron.sh remove

# Show current scheduled job
bash setup_update_cron.sh show
```

Logs are saved to `task_report.log` and archived in `automation_logs/` with timestamps.

## Linux Deployment

### Prerequisites

1. Python 3.7+ installed on target host
2. SSH key-based authentication configured (passwordless)
3. Passwordless sudo access where needed:
   ```bash
   # Add to sudoers (visudo):
   automator ALL=(ALL) NOPASSWD: /usr/bin/apt-get, /usr/bin/systemctl, /usr/bin/journalctl
   ```
4. `hosts.json` and `profiles.json` configured for your infrastructure

### Deployment Steps

1. Copy project files to target host (e.g., `/opt/linux-automation/`)
2. Test profile resolution:
   ```bash
   python3 orchestrator.py --list-profiles
   ```
3. Test connection with dry-run:
   ```bash
   python3 orchestrator.py --profile prod-maintenance --dry-run
   ```
4. Run with emulation to verify workflow:
   ```bash
   python3 orchestrator.py --profile prod-maintenance --emulate-success
   ```
5. Schedule via cron:
   ```bash
   bash setup_update_cron.sh 3day
   ```

## Backward Compatibility

The system supports both new profile-based and legacy manual host/task selection:

```bash
# Profile mode (new)
python3 orchestrator.py --profile prod-maintenance

# Manual mode (legacy, still supported)
python3 orchestrator.py --hosts all --tasks regular_maint
```

Both paths continue to work without breaking existing scripts or automations.

## Troubleshooting

### Profile Not Found
```
ERROR: Unknown profile 'my-profile'. Available: prod-maintenance, docker-health, ...
```
Check `profiles.json` and ensure profile name is spelled correctly.

### Host Selection Fails
```
ERROR: No hosts matched query 'tags:missing'
```
Verify host tags in `hosts.json` match profile queries in `profiles.json`.

### SSH Connection Timeout
```
Host unreachable on SSH port 22
```
Check network connectivity, firewall rules, and SSH daemon on target hosts.

### Passwordless Sudo Issues
```
Passwordless sudo is required for regular maintenance tasks
```
Configure sudoers as shown in Linux Deployment section above.

## Contributing

To add new tasks:
1. Implement task function in `task_playbook.py`
2. Add task to `TASK_PLAYBOOK` dictionary
3. Define any new task applicability rules in `orchestrator.py` under `is_task_applicable()`
4. Update `TASK_ALIASES` in `selection.py` if needed
5. Document task in README

## Support

For issues or questions, contact paragrayamajhi@yahoo.com
