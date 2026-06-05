from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class HostIdentity:
    name: str
    ip: str
    username: str
    description: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, host: Mapping[str, Any]) -> tuple[HostIdentity | None, str | None]:
        name = host.get("name")
        ip = host.get("ip")
        username = host.get("username")
        description = host.get("description", "")
        tags_raw = host.get("tags", [])

        if not isinstance(name, str) or not name.strip() or not isinstance(ip, str) or not ip.strip():
            return None, "Missing name or ip in hosts.json"

        if not isinstance(username, str) or not username.strip():
            return None, "Missing or invalid username in hosts.json"

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
        return {
            "name": self.name,
            "ip": self.ip,
            "username": self.username,
            "description": self.description,
            "tags": list(self.tags),
        }


@dataclass
class HostRunResult:
    name: str
    ip: str
    description: str
    username: str
    status: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def failed_from_mapping(cls, host: Mapping[str, Any], reason: str) -> HostRunResult:
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
