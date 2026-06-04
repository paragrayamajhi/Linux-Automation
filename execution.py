from __future__ import annotations

import socket
import subprocess
from datetime import datetime
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


def collect_local_addresses() -> set[str]:
    addresses: set[str] = {"127.0.0.1", "::1"}

    try:
        hostname = socket.gethostname()
        for family, _, _, _, sockaddr in socket.getaddrinfo(hostname, None):
            host_addr = sockaddr[0]
            if not isinstance(host_addr, str):
                continue
            if family == socket.AF_INET:
                addresses.add(host_addr)
            elif family == socket.AF_INET6:
                addresses.add(host_addr.split("%")[0])
    except OSError:
        pass

    try:
        fqdn = socket.getfqdn()
        for family, _, _, _, sockaddr in socket.getaddrinfo(fqdn, None):
            host_addr = sockaddr[0]
            if not isinstance(host_addr, str):
                continue
            if family == socket.AF_INET:
                addresses.add(host_addr)
            elif family == socket.AF_INET6:
                addresses.add(host_addr.split("%")[0])
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
    username = str(host["username"]).strip()
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
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }

    executor: Callable[[str, int], tuple[int, str, str]]
    if local:
        executor = lambda command, timeout=timeout: run_shell_command(command, timeout)
    else:
        executor = lambda command, timeout=timeout: run_remote_command(host, command, timeout)

    started_at = datetime.now()
    try:
        result = task_fn(host, executor, timeout)
        finished_at = datetime.now()
        result["started_at"] = started_at.isoformat()
        result["finished_at"] = finished_at.isoformat()
        return result
    except subprocess.TimeoutExpired:
        finished_at = datetime.now()
        return {
            "task": task_name,
            "status": "failed",
            "reason": "Task timed out",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }
