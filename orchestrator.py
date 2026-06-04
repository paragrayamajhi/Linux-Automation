#!/usr/bin/env python3
"""Orchestrate dynamic task execution on Linux hosts from inventory."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from execution import collect_local_addresses, is_host_local, is_reachable, run_playbook_task
from inventory import load_hosts
from models import HostIdentity, HostRunResult
from reporting import archive_report, build_report
from selection import build_host_selection, build_task_list, format_available_hosts, format_available_tasks

DEFAULT_HOSTS_PATH = Path(__file__).with_name("hosts.json")
DEFAULT_REPORT_PATH = Path(__file__).with_name("task_report.json")


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


def prompt_for_missing_values(hosts: list[dict[str, Any]], current_hosts: str | None, current_tasks: str | None) -> tuple[str, str]:
    print("Interactive orchestrator input")
    print("Available hosts:", format_available_hosts(hosts))
    print("Available tasks:", format_available_tasks())
    print()
    print("Enter hosts as 'all' or comma-separated values like 'ubuntu,pi.hole' or short names like 'proxmox,ubuntu,eve,automation'")
    print("Enter tasks as comma-separated values like 'regular_maint,docker_healthcheck,system_healthcheck'")
    print("Use aliases: system_update, update_upgrade, system_health, docker_health, or 'all' for every task")
    print("Direct CLI examples:")
    print("  python3 orchestrator.py --hosts all --tasks all")
    print("  python3 orchestrator.py --hosts ubuntu.horizon.local,pi.hole --tasks regular_maint,docker_healthcheck")
    print()
    if current_hosts is None:
        current_hosts = input("Hosts [all]: ").strip() or "all"
    if current_tasks is None:
        current_tasks = input("Tasks [all]: ").strip() or "all"
    return current_hosts, current_tasks


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
    report_items: list[HostRunResult] = []
    execution_started_at = datetime.now()

    for host in selected_hosts:
        host_identity, host_error = HostIdentity.from_mapping(host)
        if host_identity is None:
            reason = host_error or "Invalid host entry in hosts.json"
            host_result = HostRunResult.failed_from_mapping(host, reason)
            if reason == "Missing or invalid username in hosts.json":
                print(f"Processing {host_result.name} ({host_result.ip}) [{host_result.description}] as <unknown>")
                print("  - invalid host configuration: username must be provided in hosts.json")
            report_items.append(host_result)
            continue

        print(
            f"Processing {host_identity.name} ({host_identity.ip}) "
            f"[{host_identity.description}] as {host_identity.username}"
        )

        local = host_identity.name.lower().startswith("automation-hub") or is_host_local(
            host_identity.ip, local_addresses, local_hostname
        )

        if not local and not is_reachable(host_identity.ip):
            report_items.append(
                HostRunResult(
                    name=host_identity.name,
                    ip=host_identity.ip,
                    description=host_identity.description,
                    username=host_identity.username,
                    status="failed",
                    reason="Host unreachable on SSH port 22",
                )
            )
            print(f"  - unreachable: {host_identity.ip}:22")
            continue

        host_context = host_identity.to_host_context()
        task_results: list[dict[str, Any]] = []
        for task_name in tasks:
            print(f"  Running {task_name}...")
            result = run_playbook_task(host_context, task_name, local, args.timeout)
            task_results.append(result)

        host_status = "passed" if all(task["status"] == "passed" for task in task_results) else "failed"
        host_result = HostRunResult(
            name=host_identity.name,
            ip=host_identity.ip,
            description=host_identity.description,
            username=host_identity.username,
            status=host_status,
            tasks=task_results,
        )

        if host_status == "failed":
            host_result.reason = "One or more tasks failed"

        if task_results:
            host_result.stdout = "\n".join(task.get("stdout", "") for task in task_results)
            host_result.stderr = "\n".join(task.get("stderr", "") for task in task_results)

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

    report_payload = [item.to_dict() for item in report_items]
    execution_finished_at = datetime.now()
    report = build_report(report_payload, execution_started_at, execution_finished_at)
    archive_report(args.report_file)
    with open(args.report_file, "w", encoding="utf-8") as report_handle:
        json.dump(report, report_handle, indent=2)

    print("\nOrchestrator run complete")
    print(f"Passed: {report['summary']['passed']} / {report['summary']['total_hosts']}")
    print(f"Failed: {report['summary']['failed']} / {report['summary']['total_hosts']}")
    print(f"Report saved to: {args.report_file}")

    print("\nHost-wise summary:")
    for host_record in report_payload:
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
