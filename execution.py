from __future__ import annotations

"""Execution helpers for local/remote command execution.

This module centralizes:
- local address discovery,
- host-locality and reachability checks,
- shell/SSH execution wrappers,
- task playbook dispatch with timing metadata.

In simple terms:
- "Can I reach this host?"
- "Should I run this command locally or over SSH?"
- "Run it and give me structured outputs."

Quick glossary:
- host: A machine we want to run tasks on.
- local: This same machine where orchestrator is running.
- remote: Another machine reached through SSH.
- executor: A small function that actually runs a shell command.
- timeout: Maximum time allowed for one command before failure.
"""

import socket
import subprocess
from datetime import datetime
from typing import Any, Callable

from task_playbook import TASK_PLAYBOOK

# Default TCP timeout (seconds) used by lightweight reachability checks.
SSH_CONNECT_TIMEOUT = 10

# SSH options used for non-interactive automation-friendly execution.
SSH_BATCH_OPTIONS = [
    "-o",
    "BatchMode=yes",  # Prevent password prompts.
    "-o",
    "ConnectTimeout=10",  # Fail quickly on unreachable hosts.
    "-o",
    "StrictHostKeyChecking=accept-new",  # Auto-trust first-time hosts.
    "-o",
    "UserKnownHostsFile=/dev/null",  # Avoid mutating known_hosts in automation runs.
]


def collect_local_addresses() -> set[str]:
    """Return a set of IP addresses that represent this machine.

    The set includes loopback addresses plus all IPv4/IPv6 addresses resolved
    from hostname and FQDN. IPv6 zone IDs are stripped for stable comparisons.
    """
    addresses: set[str] = {"127.0.0.1", "::1"}

    # Resolve short hostname to collect local interface addresses.
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
        # Best-effort lookup: ignore resolution errors and continue.
        pass

    # Resolve FQDN as a second source in case DNS naming differs.
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
        # Keep whatever addresses were already discovered.
        pass

    return addresses


def is_host_local(host: str, local_addresses: set[str], hostname: str | None = None) -> bool:
    """Return True when a host points to the current machine.

    Matching strategy:
    1) exact IP match against known local addresses,
    2) resolved remote host IP intersects with local addresses,
    3) optional hostname/FQDN lexical match.
    """
    # Fast-path exact IP check.
    if host in local_addresses:
        return True

    # DNS-based check: compare resolved host addresses to local addresses.
    try:
        host_addrs = {addr[4][0] for addr in socket.getaddrinfo(host, None)}
    except OSError:
        host_addrs = set()

    if host_addrs.intersection(local_addresses):
        return True

    # Optional hostname-based check for short/FQDN variants.
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
    """Return True when TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_shell_command(command: str, timeout: int) -> tuple[int, str, str]:
    """Execute a command locally via /bin/sh and return rc/stdout/stderr."""
    result = subprocess.run(
        ["/bin/sh", "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def run_remote_command(host: dict[str, Any], command: str, timeout: int) -> tuple[int, str, str]:
    """Execute a command remotely over SSH and return rc/stdout/stderr."""
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
    """Run a named playbook task and attach timing metadata.

    The task is looked up from TASK_PLAYBOOK and receives an executor callable
    that already knows whether this host should run locally or over SSH.

    Think of this as an adapter layer: tasks only define *what* command logic to
    run, while this function decides *where/how* to run it and adds timestamps.
    """
    task_fn = TASK_PLAYBOOK.get(task_name)
    if task_fn is None:
        # Return normalized failure payload for unknown task names.
        return {
            "task": task_name,
            "status": "failed",
            "reason": "Unknown task",
            "started_at": datetime.now().isoformat(),
            "finished_at": datetime.now().isoformat(),
        }

    # Build a compatible executor signature for task functions.
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
        # Normalize timeout failures so callers can report consistently.
        finished_at = datetime.now()
        return {
            "task": task_name,
            "status": "failed",
            "reason": "Task timed out",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        }
