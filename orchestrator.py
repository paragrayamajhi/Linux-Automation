#!/usr/bin/env python3
"""Orchestrate dynamic task execution on Linux hosts from inventory."""

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
DEFAULT_REPORT_PATH = Path(__file__).with_name("task_report.json")

TASK_ALIASES = {
    "system_update": "update_upgrade",
    "system_health": "system_healthcheck",
    "healthcheck": "system_healthcheck",
    "docker_health": "docker_healthcheck",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dynamic tasks against selected hosts")
    parser.add_argument(
        "--hosts",
        default=None,
        help="Comma-separated host names or IPs, or 'all' for every host in inventory. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task names to execute, e.g. docker_healthcheck,system_health. Use 'all' to run every task. If omitted, you will be prompted.",
    )
    parser.add_argument(
        "--hosts-file",
        default=str(DEFAULT_HOSTS_PATH),
        help="Path to the hosts.json inventory file",
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
        help="Timeout in seconds for each task command",
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

        if host_lower == hostname_lower:
            return True
        if host_lower.startswith(hostname_lower + "."):
            return True
        if hostname_lower.startswith(host_lower + "."):
            return True

    return False


def is_reachable(host: str, port: int = 22, timeout: int = SSH_CONNECT_TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_shell_command(command: str, timeout: int) -> tuple[int, str, str]:
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_remote_command(host: dict[str, Any], command: str, timeout: int) -> tuple[int, str, str]:
    username = host.get("username", "root")
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


def normalize_task_name(task: str) -> str:
    normalized = task.strip().lower()
    return TASK_ALIASES.get(normalized, normalized)


def build_task_list(tasks_arg: str) -> list[str]:
    normalized_arg = tasks_arg.strip().lower()
    if normalized_arg == "all":
        return list(TASK_PLAYBOOK.keys())

    task_names = [normalize_task_name(task) for task in tasks_arg.split(",") if task.strip()]
    if not task_names:
        raise ValueError("At least one task must be provided")

    unknown = [task for task in task_names if task not in TASK_PLAYBOOK]
    if unknown:
        raise ValueError(f"Unknown task(s): {', '.join(unknown)}")

    return task_names


def format_available_hosts(hosts: list[dict[str, Any]]) -> str:
    return ", ".join(str(host.get("name", "<unknown>")) for host in hosts)


def format_available_tasks() -> str:
    canonical = list(TASK_PLAYBOOK.keys())
    alias_entries = [f"{alias} ({target})" for alias, target in TASK_ALIASES.items()]
    return ", ".join(canonical + alias_entries)


def prompt_for_missing_values(hosts: list[dict[str, Any]], current_hosts: str | None, current_tasks: str | None) -> tuple[str, str]:
    print("Interactive orchestrator input")
    print("Available hosts:", format_available_hosts(hosts))
    print("Available tasks:", format_available_tasks())
    print()
    print("Enter hosts as 'all' or comma-separated values like 'ubuntu.horizon.local,pi.hole'")
    print("Enter tasks as comma-separated values like 'update_upgrade,docker_healthcheck,system_healthcheck'")
    print("Use aliases: system_update, system_health, docker_health, or 'all' for every task")
    print("Direct CLI examples:")
    print("  python3 orchestrator.py --hosts all --tasks all")
    print("  python3 orchestrator.py --hosts ubuntu.horizon.local,pi.hole --tasks docker_health,system_health")
    print()
    if current_hosts is None:
        current_hosts = input("Hosts [all]: ").strip() or "all"
    if current_tasks is None:
        current_tasks = input("Tasks [all]: ").strip() or "all"
    return current_hosts, current_tasks


def host_matches_selector(host: dict[str, Any], selector: str) -> bool:
    selector_lower = selector.lower()
    name = str(host.get("name", "")).lower()
    ip = str(host.get("ip", "")).lower()
    short_name = name.split(".")[0] if name else ""
    return selector_lower in {name, ip, short_name}


def build_host_selection(hosts_arg: str, hosts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if hosts_arg.strip().lower() == "all":
        return hosts

    selectors = [item.strip() for item in hosts_arg.split(",") if item.strip()]
    selected: list[dict[str, Any]] = []
    for selector in selectors:
        matches = [host for host in hosts if host_matches_selector(host, selector)]
        if not matches:
            raise ValueError(f"No host matched selector '{selector}'")
        selected.extend(matches)

    # Deduplicate preserving order
    unique_hosts: list[dict[str, Any]] = []
    seen = set()
    for host in selected:
        key = (host.get("name"), host.get("ip"))
        if key not in seen:
            seen.add(key)
            unique_hosts.append(host)

    return unique_hosts


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
    report_file = Path(report_path)
    if report_file.exists():
        archive_dir = report_file.parent / "reports_archive"
        archive_dir.mkdir(exist_ok=True)

        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        archived_path = archive_dir / f"{report_file.stem}_{timestamp}{report_file.suffix}"
        report_file.rename(archived_path)
        print(f"Archived previous report to: {archived_path}")


def main() -> int:
    args = parse_args()

    try:
        hosts = load_hosts(args.hosts_file)
    except Exception as exc:
        print(f"ERROR: Failed to load hosts file: {exc}", file=sys.stderr)
        return 1

    if args.hosts is None or args.tasks is None:
        if not sys.stdin.isatty():
            print("ERROR: --hosts and --tasks are required when not running interactively", file=sys.stderr)
            return 1
        args.hosts, args.tasks = prompt_for_missing_values(hosts, args.hosts, args.tasks)

    try:
        selected_hosts = build_host_selection(args.hosts, hosts)
        tasks = build_task_list(args.tasks)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    local_addresses = collect_local_addresses()
    local_hostname = socket.gethostname()
    report_items: list[dict[str, Any]] = []

    for host in selected_hosts:
        name = host.get("name")
        ip = host.get("ip")
        username = host.get("username", "root")
        description = host.get("description", "")

        if not name or not ip:
            report_items.append({
                "name": name or "<unknown>",
                "ip": ip or "<unknown>",
                "description": description,
                "username": username,
                "status": "failed",
                "reason": "Missing name or ip in hosts.json",
            })
            continue

        print(f"Processing {name} ({ip}) [{description}] as {username}")

        local = name.lower().startswith("automation-hub") or is_host_local(ip, local_addresses, local_hostname)

        if not local and not is_reachable(ip):
            report_items.append({
                "name": name,
                "ip": ip,
                "description": description,
                "username": username,
                "status": "failed",
                "reason": "Host unreachable on SSH port 22",
            })
            print(f"  - unreachable: {ip}:22")
            continue

        task_results: list[dict[str, Any]] = []
        for task_name in tasks:
            print(f"  Running {task_name}...")
            result = run_playbook_task(host, task_name, local, args.timeout)
            task_results.append(result)

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

        for task in task_results:
            task_name = task.get("task", "unknown")
            task_status = task.get("status", "unknown")
            status_icon = "✓" if task_status == "passed" else "✗"
            print(f"  - {status_icon} {task_name}: {task_status}")
            if task_name == "docker_healthcheck" and task_status == "passed":
                stdout = task.get("stdout", "").strip()
                if stdout:
                    print("    Docker containers:")
                    for line in stdout.splitlines():
                        print(f"      {line}")
            if task_name == "system_healthcheck" and task_status == "passed":
                checks = task.get("checks", {})
                print("    System Health Report:")
                print(f"      CPU Usage: {checks.get('cpu_usage', 'N/A')}")
                print(f"      Memory: {checks.get('memory_usage', 'N/A')}")
                print(f"      DNS Response Time: {checks.get('dns_response_time', 'N/A')}")
                print(f"      Packet Loss: {checks.get('packet_loss', 'N/A')}")
                print(f"      Network Latency: {checks.get('latency', 'N/A')}")
            if task_status == "failed":
                reason = task.get("reason", "Unknown error")
                print(f"    Error: {reason}")
                stderr = task.get("stderr", "").strip()
                if stderr and "Warning:" not in stderr:
                    print(f"    Details: {stderr[:200]}")

        print(f"  Overall: {host_status}")
        report_items.append(host_result)

    report = build_report(report_items)
    archive_report(args.report_file)
    with open(args.report_file, "w", encoding="utf-8") as report_handle:
        json.dump(report, report_handle, indent=2)

    print("\nOrchestrator run complete")
    print(f"Passed: {report['summary']['passed']} / {report['summary']['total_hosts']}")
    print(f"Failed: {report['summary']['failed']} / {report['summary']['total_hosts']}")
    print(f"Report saved to: {args.report_file}")

    print("\nHost-wise summary:")
    for host_record in report_items:
        host_name = host_record.get("name", "<unknown>")
        print(f"\n{host_name}:")
        host_tasks = host_record.get("tasks", [])
        total_tests = len(host_tasks)
        passed_tests = sum(1 for task in host_tasks if task.get("status") == "passed")
        failed_tests = total_tests - passed_tests
        if host_tasks:
            for task in host_tasks:
                task_name = task.get("task", "unknown")
                task_status = task.get("status", "unknown")
                print(f"  {task_name}: {task_status}")
        else:
            reason = host_record.get("reason")
            if reason:
                print(f"  Reason: {reason}")
        print(f"  Total tests: {total_tests}")
        print(f"  Passed: {passed_tests}")
        print(f"  Failed: {failed_tests}")

    return 0 if report["summary"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
