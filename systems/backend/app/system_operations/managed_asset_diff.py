from __future__ import annotations

from typing import Any


def diff_payload(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[dict[str, Any]] = []
        for key in sorted(before.keys() | after.keys()):
            child = f"{path}/{key}"
            if key not in before:
                changes.append({"path": child, "change_type": "added", "before": None, "after": after[key]})
            elif key not in after:
                changes.append({"path": child, "change_type": "removed", "before": before[key], "after": None})
            else:
                changes.extend(diff_payload(before[key], after[key], child))
        return changes
    if before != after:
        return [{"path": path or "/", "change_type": "changed", "before": before, "after": after}]
    return []
