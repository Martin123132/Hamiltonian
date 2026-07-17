from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from . import __version__
from .core import ensure_repo, write_text
from .goals import goal_workspace_summary
from .runtime import build_runtime_state


DIAGNOSTICS_SCHEMA = "hamiltonian.sanitized-diagnostics.v1"


def build_sanitized_diagnostics(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    runtime = build_runtime_state(repo)
    packet_stages = Counter(
        str(packet.get("stage") or "unknown") for packet in runtime.recent_packets
    )
    return {
        "schema": DIAGNOSTICS_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "workspace_name": repo.name,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "git": {
            "available": runtime.git_available,
            "dirty": bool(runtime.git_status.strip()),
        },
        "runtime": {
            "surface": "local",
            "remote_execution": False,
            "workspace_paths_included": False,
            "adapter_output_included": False,
        },
        "adapters": [
            {
                "id": adapter.id,
                "name": adapter.name,
                "available": adapter.available,
                "mode": adapter.mode,
                "local_execution": adapter.local_execution,
                "remote_execution": adapter.remote_execution,
            }
            for adapter in runtime.runner_adapters
        ],
        "integrations": [
            {"name": integration.name, "available": integration.available}
            for integration in runtime.integrations
        ],
        "packets": {
            "total": len(runtime.recent_packets),
            "by_stage": dict(sorted(packet_stages.items())),
        },
        "goals": goal_workspace_summary(repo),
        "sanitized": True,
        "local_only": True,
    }


def export_sanitized_diagnostics(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    payload = build_sanitized_diagnostics(repo)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"hamiltonian-diagnostics-{stamp}.json"
    path = repo / ".hamiltonian" / "diagnostics" / filename
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {
        "filename": filename,
        "path": str(path),
        "schema": DIAGNOSTICS_SCHEMA,
        "sanitized": True,
        "local_only": True,
        "remote_execution": False,
    }
