from __future__ import annotations

"""Load the host inventory file.

In plain words:
- Read JSON from disk.
- Check that it has a `hosts` list.
- Return only that list to the rest of the app.

Note: extra top-level keys (like `_meta`) are allowed and ignored.

Quick glossary:
- inventory: List of machines to manage.
- parse JSON: Read text and convert it into Python data.
- validation: Check data shape before using it.
"""

import json
from typing import Any


def load_hosts(path: str) -> list[dict[str, Any]]:
    """Load host list from hosts.json-like file.

    Expected structure:
    {
      "hosts": [ ... ]
    }
    """
    # Open and parse the JSON file from the provided path.
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    # Guardrail: the orchestrator requires an object with a `hosts` list.
    if not isinstance(data, dict) or "hosts" not in data or not isinstance(data["hosts"], list):
        raise ValueError("hosts.json must contain an object with a 'hosts' list")

    # Return only the host list; caller does not need other top-level fields.
    return data["hosts"]
