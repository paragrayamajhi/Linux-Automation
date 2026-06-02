#!/usr/bin/env python3
"""Update remote Linux hosts from hosts.json.

This script checks whether each target host is reachable over SSH, then runs
`apt-get update && apt-get -y upgrade` on each host. Hosts that are not
reachable are skipped, and a JSON report is written at the end summarizing
successes and failures.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from task_playbook import TASK_PLAYBOOK

SSH_CONNECT_TIMEOUT = 10
SSH_BATCH_OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "StrictHostKeyChecking=accept-new",
    "-o",
    "UserKnownHostsFile=/dev/null",
]
DEFAULT_HOSTS_PATH = Path(__file__).with_name("hosts.json")
DEFAULT_REPORT_PATH = Path(__file__).with_name("update_report.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update remote Linux hosts from hosts.json")
    parser.add_argument(
        "--hosts-file",
        default=str(DEFAULT_HOSTS_PATH),
        help="Path to the hosts.json file",
    )
    parser.add_argument(
        "--report-file",
        default=str(DEFAULT_REPORT_PATH),
        help="Path to write the JSON report",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Timeout in seconds for each remote update command",
    )
    return parser.parse_args()


def load_hosts(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or "hosts" not in data or not isinstance(data["hosts"], list):
        raise ValueError("hosts.json must contain an object with a 'hosts' list")

    return data["hosts"]


def collect_local_addresses() -> set[str]:
    addresses: set[str] = {"127.0.0.1", "::1"}

    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            if family == socket.AF_INET:
                addresses.add(sockaddr[0])
            elif family == socket.AF_INET6:
                addresses.add(sockaddr[0].split("%")[0])
    except OSError:
        pass

    try:
        fqdn = socket.getfqdn()
        for family, _, _, _, sockaddr in socket.getaddrinfo(fqdn, None):
            if family == socket.AF_INET:
                addresses.add(sockaddr[0])
            elif family == socket.AF_INET6:
                addresses.add(sockaddr[0].split("%")[0])
    except OSError:
        pass

    return addresses


def is_host_local(host: str, local_addresses: set[str], hostname: str | None = None) -> bool:
    if host in local_addresses:
        return True

    try:
        host_addrs = {addr[4][0] for addr in socket.getaddrinfo(host, None)}
    except OSError:
        host_addrs = set()

    if host_addrs.intersection(local_addresses):
        return True

    if hostname:
        host_lower = host.lower()
        hostname_lower = hostname.lower()
        
        # Exact match or FQDN match
        if host_lower == hostname_lower:
            return True
        
        # Check if host starts with hostname (e.g., "automation-hub.horizon.local" matches "automation-hub")
        if host_lower.startswith(hostname_lower + "."):
            return True
        
        # Check if hostname starts with host (e.g., "automation-hub" matches "automation-hub.horizon.local")
        if hostname_lower.startswith(host_lower + "."):
            return True

    return False


def is_reachable(host: str, port: int = 22, timeout: int = SSH_CONNECT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_local(host: dict[str, Any], timeout: int) -> tuple[int, str, str]:
    username = host.get("username", "automator")
    if username == "root":
        command = "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get -y upgrade"
    else:
        command = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "sudo -n apt-get update && sudo -n apt-get -y upgrade"
        )

    result = subprocess.run(
        ["/bin/sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_remote(host: dict[str, Any], timeout: int) -> tuple[int, str, str]:
    username = host.get("username", "automator")
    target = f"{username}@{host['ip']}"

    if username == "root":
        command = "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get -y upgrade"
    else:
        command = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "sudo -n apt-get update && sudo -n apt-get -y upgrade"
        )

    ssh_command = ["ssh", *SSH_BATCH_OPTIONS, target, command]
    result = subprocess.run(
        ssh_command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_shell_command(command: str, timeout: int) -> tuple[int, str, str]:
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_remote_command(host: dict[str, Any], command: str, timeout: int) -> tuple[int, str, str]:
    username = host.get("username", "automator")
    target = f"{username}@{host['ip']}"
    ssh_command = ["ssh", *SSH_BATCH_OPTIONS, target, command]
    result = subprocess.run(
        ssh_command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_playbook_task(host: dict[str, Any], task_name: str, local: bool, timeout: int) -> dict[str, Any]:
    task_fn = TASK_PLAYBOOK.get(task_name)
    if task_fn is None:
        return {
            "task": task_name,
            "status": "failed",
            "reason": "Unknown task",
        }

    executor: Callable[[str, int], tuple[int, str, str]]
    if local:
        executor = lambda command, timeout=timeout: run_shell_command(command, timeout)
    else:
        executor = lambda command, timeout=timeout: run_remote_command(host, command, timeout)

    try:
        return task_fn(host, executor, timeout)
    except subprocess.TimeoutExpired:
        return {
            "task": task_name,
            "status": "failed",
            "reason": "Task timed out",
        }


def run_host_tasks(host: dict[str, Any], local: bool, timeout: int) -> list[dict[str, Any]]:
    tasks = host.get("tasks")
    if tasks is None:
        tasks = ["update_upgrade"]
    if not isinstance(tasks, list):
        return [{
            "task": "<invalid>",
            "status": "failed",
            "reason": "Host tasks field must be a list",
        }]

    task_results: list[dict[str, Any]] = []
    for task_name in tasks:
        if not isinstance(task_name, str):
            task_results.append({
                "task": str(task_name),
                "status": "failed",
                "reason": "Invalid task name",
            })
            continue
        task_results.append(run_playbook_task(host, task_name, local, timeout))
    return task_results


def build_report(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for item in results if item["status"] == "passed")
    failed = sum(1 for item in results if item["status"] != "passed")
    return {
        "summary": {
            "total_hosts": len(results),
            "passed": passed,
            "failed": failed,
        },
        "hosts": results,
    }


def archive_report(report_path: str) -> None:
    """Archive existing report file with a datetime timestamp into reports_archive directory."""
    report_file = Path(report_path)
    if report_file.exists():
        archive_dir = report_file.parent / "reports_archive"
        archive_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        stem = report_file.stem
        suffix = report_file.suffix
        archived_path = archive_dir / f"{stem}_{timestamp}{suffix}"
        report_file.rename(archived_path)
        print(f"Archived previous report to: {archived_path}")


def main() -> int:
    args = parse_args()
    try:
        hosts = load_hosts(args.hosts_file)
    except Exception as exc:
        print(f"ERROR: Failed to load hosts file: {exc}", file=sys.stderr)
        return 1

    local_addresses = collect_local_addresses()
    local_hostname = socket.gethostname()
    report_items: list[dict[str, Any]] = []

    for host in hosts:
        name = host.get("name")
        ip = host.get("ip")
        username = host.get("username", "automator")
        description = host.get("description", "")

        if not name or not ip:
            report_items.append(
                {
                    "name": name or "<unknown>",
                    "ip": ip or "<unknown>",
                    "description": description,
                    "username": username,
                    "status": "failed",
                    "reason": "Missing name or ip in hosts.json",
                }
            )
            continue

        print(f"Processing {name} ({ip}) [{description}] as {username}")

        local = name.lower().startswith("automation-hub") or is_host_local(ip, local_addresses, local_hostname)

        if not local and not is_reachable(ip):
            report_items.append(
                {
                    "name": name,
                    "ip": ip,
                    "description": description,
                    "username": username,
                    "status": "failed",
                    "reason": "Host unreachable on SSH port 22",
                }
            )
            print(f"  - unreachable: {ip}:22")
            continue

        task_results = run_host_tasks(host, local=local, timeout=args.timeout)
        host_status = "passed" if all(task["status"] == "passed" for task in task_results) else "failed"
        host_result = {
            "name": name,
            "ip": ip,
            "description": description,
            "username": username,
            "status": host_status,
            "tasks": task_results,
        }

        if host_status == "failed":
            host_result["reason"] = "One or more tasks failed"

        if task_results:
            host_result["stdout"] = "\n".join(task.get("stdout", "") for task in task_results)
            host_result["stderr"] = "\n".join(task.get("stderr", "") for task in task_results)

        # Print detailed task results
        for task in task_results:
            task_name = task.get("task", "unknown")
            task_status = task.get("status", "unknown")
            status_icon = "✓" if task_status == "passed" else "✗"
            print(f"  - {status_icon} {task_name}: {task_status}")
            
            # Special handling for docker_healthcheck: display container list
            if task_name == "docker_healthcheck" and task_status == "passed":
                stdout = task.get("stdout", "").strip()
                if stdout:
                    print(f"    Docker containers:")
                    for line in stdout.splitlines():
                        print(f"      {line}")
            
            # Special handling for system_healthcheck: display detailed report
            if task_name == "system_healthcheck" and task_status == "passed":
                checks = task.get("checks", {})
                if checks:
                    print(f"    System Health Report:")
                    print(f"      CPU Usage: {checks.get('cpu_usage', 'N/A')}")
                    print(f"      Memory: {checks.get('memory_usage', 'N/A')}")
                    print(f"      DNS Response Time: {checks.get('dns_response_time', 'N/A')}")
                    print(f"      Packet Loss: {checks.get('packet_loss', 'N/A')}")
                    print(f"      Network Latency: {checks.get('latency', 'N/A')}")
            
            # Display error details if task failed
            if task_status == "failed":
                reason = task.get("reason", "Unknown error")
                print(f"    Error: {reason}")
                stderr = task.get("stderr", "").strip()
                if stderr and "Warning:" not in stderr:  # Skip SSH key warnings
                    print(f"    Details: {stderr[:200]}")
        
        print(f"  Overall: {host_status}")
        report_items.append(host_result)

    report = build_report(report_items)
    archive_report(args.report_file)
    with open(args.report_file, "w", encoding="utf-8") as report_handle:
        json.dump(report, report_handle, indent=2)

    print("\nUpdate run complete")
    print(f"Passed: {report['summary']['passed']} / {report['summary']['total_hosts']}")
    print(f"Failed: {report['summary']['failed']} / {report['summary']['total_hosts']}")
    print(f"Report saved to: {args.report_file}")
    return 0 if report["summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
