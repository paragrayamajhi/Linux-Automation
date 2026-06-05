from __future__ import annotations

"""Structured data objects used by the orchestrator.

Why this file exists:
- Keep host information in a predictable shape (`HostIdentity`).
- Keep per-host run results in a predictable shape (`HostRunResult`).
- Convert those objects to plain dictionaries right before writing JSON.

Quick glossary:
- dataclass: A Python class used mainly for storing data cleanly.
- immutable: Cannot be changed after creation.
- mapping: Dictionary-like input object.
- serialize: Convert object into a plain dictionary/JSON-friendly shape.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class HostIdentity:
    """Validated host identity extracted from hosts.json.

    `frozen=True` means instances are immutable after creation, which helps
    prevent accidental changes during processing.
    """

    # Canonical host label from inventory.
    name: str
    # Target IP or DNS address.
    ip: str
    # SSH user used by remote execution.
    username: str
    # Human-readable description shown in logs/reports.
    description: str = ""
    # Optional grouping tags (production, docker, etc.).
    tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, host: Mapping[str, Any]) -> tuple[HostIdentity | None, str | None]:
        """Parse and validate raw host mapping.

        Returns:
        - (HostIdentity, None) when valid
        - (None, error_message) when invalid

        This pattern avoids raising exceptions for normal validation failures and
        lets callers report friendly error messages per host.
        """
        name = host.get("name")
        ip = host.get("ip")
        username = host.get("username")
        description = host.get("description", "")
        tags_raw = host.get("tags", [])

        # Name/IP are required for any meaningful execution context.
        if not isinstance(name, str) or not name.strip() or not isinstance(ip, str) or not ip.strip():
            return None, "Missing name or ip in hosts.json"

        # Username is mandatory because SSH target is username@host.
        if not isinstance(username, str) or not username.strip():
            return None, "Missing or invalid username in hosts.json"

        # Tags are optional. If present, keep only non-empty strings.
        parsed_tags: list[str] = []
        if isinstance(tags_raw, list):
            parsed_tags = [
                tag.strip()
                for tag in tags_raw
                if isinstance(tag, str) and tag.strip()
            ]

        return (
            cls(
                name=name.strip(),
                ip=ip.strip(),
                username=username.strip(),
                description=str(description),
                tags=tuple(parsed_tags),
            ),
            None,
        )

    def to_host_context(self) -> dict[str, Any]:
        """Convert model back to a mutable mapping used by executors/tasks.

        Tasks expect dictionaries, so this is the bridge from dataclass object
        back to dict form.
        """
        return {
            "name": self.name,
            "ip": self.ip,
            "username": self.username,
            "description": self.description,
            "tags": list(self.tags),
        }


@dataclass
class HostRunResult:
    """Structured result for one host in a run.

    This is what eventually becomes one entry in the report's `hosts` array.
    """

    name: str
    ip: str
    description: str
    username: str
    # Overall host status (passed/failed).
    status: str
    # Per-task result payloads.
    tasks: list[dict[str, Any]] = field(default_factory=list)
    # Optional failure reason at host level.
    reason: str | None = None
    # Aggregated stdout/stderr across tasks.
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def failed_from_mapping(cls, host: Mapping[str, Any], reason: str) -> HostRunResult:
        """Create a safe fallback failed result from partially invalid host data."""
        name_raw = host.get("name")
        ip_raw = host.get("ip")
        username_raw = host.get("username")

        username = username_raw.strip() if isinstance(username_raw, str) and username_raw.strip() else "<unknown>"

        return cls(
            name=name_raw.strip() if isinstance(name_raw, str) and name_raw.strip() else "<unknown>",
            ip=ip_raw.strip() if isinstance(ip_raw, str) and ip_raw.strip() else "<unknown>",
            description=str(host.get("description", "")),
            username=username,
            status="failed",
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize dataclass into report-friendly dictionary.

        Optional keys are included only when values exist, so the final JSON is
        easier to read and avoids empty noise fields.
        """
        payload: dict[str, Any] = {
            "name": self.name,
            "ip": self.ip,
            "description": self.description,
            "username": self.username,
            "status": self.status,
        }

        if self.tasks:
            payload["tasks"] = self.tasks
        if self.reason:
            payload["reason"] = self.reason
        if self.stdout is not None:
            payload["stdout"] = self.stdout
        if self.stderr is not None:
            payload["stderr"] = self.stderr

        return payload
