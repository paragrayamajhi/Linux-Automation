from __future__ import annotations

import json
from typing import Any


def load_hosts(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict) or "hosts" not in data or not isinstance(data["hosts"], list):
        raise ValueError("hosts.json must contain an object with a 'hosts' list")

    return data["hosts"]
