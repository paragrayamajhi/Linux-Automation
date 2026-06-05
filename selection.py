from __future__ import annotations

"""Selection and profile helpers.

This module handles:
- profile file validation/parsing,
- task name alias normalization,
- tag-based host filtering,
- manual selector-based host filtering,
- display helpers for interactive prompts.

Layman view:
- A "profile" is a saved preset (which hosts + which tasks).
- A "selector" is what the user types to choose hosts/tasks.
- This module converts user-friendly input into exact internal values.

Quick glossary:
- alias: A short alternative name for a task.
- canonical name: The real internal task name.
- host_query: Rule used by profiles to pick hosts.
- tags: Labels attached to hosts (production, docker, lab, etc.).
"""

import json
from typing import Any

from task_playbook import TASK_PLAYBOOK

# User-friendly aliases mapped to canonical task names.
TASK_ALIASES = {
    "system_update": "regular_maint",
    "update_upgrade": "regular_maint",
    "system_health": "system_healthcheck",
    "healthcheck": "system_healthcheck",
    "docker_health": "docker_healthcheck",
}


def load_profiles(path: str) -> dict[str, dict[str, Any]]:
    """Load and validate profile definitions from profiles.json."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or "profiles" not in data or not isinstance(data["profiles"], dict):
        raise ValueError("profiles.json must contain an object with a 'profiles' mapping")

    profiles: dict[str, dict[str, Any]] = {}
    for name, profile in data["profiles"].items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Profile names must be non-empty strings")
        if not isinstance(profile, dict):
            raise ValueError(f"Profile '{name}' must be an object")

        host_query = profile.get("host_query")
        tasks = profile.get("tasks")
        description = profile.get("description", "")
        timeout = profile.get("timeout")

        if not isinstance(host_query, str) or not host_query.strip():
            raise ValueError(f"Profile '{name}' is missing a valid host_query")
        if not isinstance(tasks, list) or not all(isinstance(task, str) and task.strip() for task in tasks):
            raise ValueError(f"Profile '{name}' must provide a non-empty string tasks list")
        if timeout is not None and not isinstance(timeout, int):
            raise ValueError(f"Profile '{name}' timeout must be an integer when provided")

        profiles[name.strip()] = {
            "description": str(description),
            "host_query": host_query.strip(),
            "tasks": tasks,
            "timeout": timeout,
        }

    return profiles


def normalize_task_name(task: str) -> str:
    """Normalize user task input (trim/lower/alias resolution)."""
    normalized = task.strip().lower()
    return TASK_ALIASES.get(normalized, normalized)


def normalize_host_tags(host: dict[str, Any]) -> set[str]:
    """Return normalized lowercase tag set from a host mapping."""
    tags_raw = host.get("tags", [])
    if not isinstance(tags_raw, list):
        return set()
    return {
        str(tag).strip().lower()
        for tag in tags_raw
        if isinstance(tag, str) and tag.strip()
    }


def host_matches_tag_query(host: dict[str, Any], query: str) -> bool:
    """Return True if host matches OR-style comma-separated tag query.

    Query examples:
    - all
    - tags:production
    - tags:lab,tags:dev

    Important: comma means OR, not AND.
    """
    normalized_query = query.strip().lower()
    if normalized_query == "all":
        return True

    tags = normalize_host_tags(host)
    if not tags:
        return False

    selectors = [item.strip() for item in normalized_query.split(",") if item.strip()]
    for selector in selectors:
        # Accept both tags:foo and foo forms.
        tag_name = selector.removeprefix("tags:").strip()
        if tag_name in tags:
            return True

    return False


def build_host_selection_from_query(host_query: str, hosts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve profile host_query into concrete host list."""
    if host_query.strip().lower() == "all":
        return hosts

    selected = [host for host in hosts if host_matches_tag_query(host, host_query)]
    if not selected:
        raise ValueError(f"No hosts matched query '{host_query}'")
    return selected


def format_available_profiles(profiles: dict[str, dict[str, Any]]) -> str:
    """Format profiles into human-readable comma-separated list."""
    entries = []
    for name, profile in profiles.items():
        description = str(profile.get("description", "")).strip() or "No description"
        entries.append(f"{name} ({description})")
    return ", ".join(entries)


def build_task_list(tasks_arg: str) -> list[str]:
    """Parse tasks CLI argument into validated canonical task list.

    Example:
    - input: "system_health,docker_health"
    - output: ["system_healthcheck", "docker_healthcheck"]
    """
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
    """Return compact host selector for prompt display."""
    name = str(host.get("name", "")).lower()
    if not name:
        return "<unknown>"

    short_name = name.split(".")[0]
    if short_name == "automation-hub":
        return "automation"
    return short_name


def format_available_hosts(hosts: list[dict[str, Any]]) -> str:
    """Return human-readable host selector list."""
    return ", ".join(format_host_selector(host) for host in hosts)


def format_available_tasks() -> str:
    """Return canonical tasks plus alias hints for prompt display."""
    canonical = list(TASK_PLAYBOOK.keys())
    alias_entries = [f"{alias} ({target})" for alias, target in TASK_ALIASES.items()]
    return ", ".join(canonical + alias_entries)


def host_matches_selector(host: dict[str, Any], selector: str) -> bool:
    """Return True for exact name/ip/short-name match (with prefix support)."""
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
    """Parse manual hosts arg and return deduplicated host list."""
    if hosts_arg.strip().lower() == "all":
        return hosts

    selectors = [item.strip() for item in hosts_arg.split(",") if item.strip()]
    selected: list[dict[str, Any]] = []
    for selector in selectors:
        matches = [host for host in hosts if host_matches_selector(host, selector)]
        if not matches:
            raise ValueError(f"No host matched selector '{selector}'")
        selected.extend(matches)

    # De-duplicate while preserving order.
    unique_hosts: list[dict[str, Any]] = []
    seen = set()
    for host in selected:
        key = (host.get("name"), host.get("ip"))
        if key not in seen:
            seen.add(key)
            unique_hosts.append(host)

    return unique_hosts
