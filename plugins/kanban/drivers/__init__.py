"""Driver registry. `get_driver(data, project_root)` returns the right impl
based on `data['backend']['driver']`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Driver


def get_driver(data: dict[str, Any], project_root: str | Path) -> Driver:
    backend = data.get("backend") or {"driver": "local"}
    name = backend.get("driver", "local")
    if name == "local":
        from .local import LocalDriver
        return LocalDriver(Path(project_root))
    if name == "jira":
        # Phase 2 lands this. Importing lazily so Phase 1 has no jira deps.
        from .jira import JiraDriver  # type: ignore[import-not-found]
        return JiraDriver(data, Path(project_root))
    raise ValueError(f"unknown driver: {name!r}")


__all__ = ["get_driver", "Driver"]
