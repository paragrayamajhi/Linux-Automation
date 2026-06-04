from __future__ import annotations

from typing import Any

from task_playbook import TASK_PLAYBOOK

TASK_ALIASES = {
    "system_update": "regular_maint",
    "update_upgrade": "regular_maint",
    "system_health": "system_healthcheck",
    "healthcheck": "system_healthcheck",
    "docker_health": "docker_healthcheck",
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


def format_host_selector(host: dict[str, Any]) -> str:
    name = str(host.get("name", "")).lower()
    if not name:
        return "<unknown>"

    short_name = name.split(".")[0]
    if short_name == "automation-hub":
        return "automation"
    return short_name


def format_available_hosts(hosts: list[dict[str, Any]]) -> str:
    return ", ".join(format_host_selector(host) for host in hosts)


def format_available_tasks() -> str:
    canonical = list(TASK_PLAYBOOK.keys())
    alias_entries = [f"{alias} ({target})" for alias, target in TASK_ALIASES.items()]
    return ", ".join(canonical + alias_entries)


def host_matches_selector(host: dict[str, Any], selector: str) -> bool:
    selector_lower = selector.lower()
    name = str(host.get("name", "")).lower()
    ip = str(host.get("ip", "")).lower()
    short_name = name.split(".")[0] if name else ""
    if selector_lower in {name, ip, short_name}:
        return True
    if short_name.startswith(selector_lower + "-"):
        return True
    return False


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

    unique_hosts: list[dict[str, Any]] = []
    seen = set()
    for host in selected:
        key = (host.get("name"), host.get("ip"))
        if key not in seen:
            seen.add(key)
            unique_hosts.append(host)

    return unique_hosts
