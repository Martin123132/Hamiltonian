from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .core import ensure_repo, write_text
from .packets import get_task_packet


COMPARISON_SCHEMA = "hamiltonian.result-comparison.v1"
COMPARABLE_LANES = {"codex", "hermes"}


def comparisons_root(repo: Path) -> Path:
    return repo.resolve() / ".hamiltonian" / "comparisons"


def _receipt_for(packet: dict[str, Any]) -> dict[str, Any]:
    run = packet.get("runner_run") if isinstance(packet.get("runner_run"), dict) else {}
    receipt = run.get("result_receipt") if isinstance(run.get("result_receipt"), dict) else {}
    if run.get("status") != "succeeded" or receipt.get("status") != "succeeded":
        raise ValueError("both packets must have successful standardized result receipts")
    if not receipt.get("result_available"):
        raise ValueError("both result receipts must reference a final response")
    return receipt


def _comparison_side(packet: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": str(packet.get("packet_id") or ""),
        "lane_id": str(packet.get("agent_id") or receipt.get("lane_id") or ""),
        "lane_name": str(packet.get("agent_name") or receipt.get("lane_id") or "Unknown lane"),
        "adapter_id": str(receipt.get("adapter_id") or ""),
        "run_id": str(receipt.get("run_id") or ""),
        "status": str(receipt.get("status") or "unknown"),
        "duration_seconds": float(receipt.get("duration_seconds") or 0),
        "result_digest": str(receipt.get("result_digest") or ""),
        "result_length": int(receipt.get("result_length") or 0),
    }


def create_result_comparison(
    repo_path: Path,
    primary_packet_id: str,
    secondary_packet_id: str,
) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    if primary_packet_id == secondary_packet_id:
        raise ValueError("comparison requires two different packets")
    primary = get_task_packet(repo, primary_packet_id)
    secondary = get_task_packet(repo, secondary_packet_id)
    primary_lane = str(primary.get("agent_id") or "")
    secondary_lane = str(secondary.get("agent_id") or "")
    if {primary_lane, secondary_lane} != COMPARABLE_LANES:
        raise ValueError("comparison requires one Codex packet and one Hermes packet")

    primary_receipt = _receipt_for(primary)
    secondary_receipt = _receipt_for(secondary)
    task_digest = str(primary_receipt.get("task_digest") or "")
    if not task_digest or task_digest != str(secondary_receipt.get("task_digest") or ""):
        raise ValueError("comparison packets must use the same task")

    created_at = datetime.now(timezone.utc).isoformat()
    comparison_id = f"comparison-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    root = comparisons_root(repo)
    comparison_dir = root / comparison_id
    comparison_dir.mkdir(parents=True, exist_ok=False)
    comparison_path = comparison_dir / "comparison.json"
    comparison = {
        "schema": COMPARISON_SCHEMA,
        "comparison_id": comparison_id,
        "created_at": created_at,
        "workspace_name": repo.name,
        "status": "complete",
        "task_digest": task_digest,
        "primary": _comparison_side(primary, primary_receipt),
        "secondary": _comparison_side(secondary, secondary_receipt),
        "result_text_included": False,
        "local_only": True,
        "remote_execution": False,
        "artifact_path": str(comparison_path),
    }
    stored = dict(comparison)
    stored["artifact_path"] = comparison_path.name
    write_text(comparison_path, json.dumps(stored, indent=2))
    return comparison


def list_result_comparisons(repo_path: Path) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = comparisons_root(repo)
    if not root.exists():
        return []
    comparisons: list[dict[str, Any]] = []
    for path in root.glob("comparison-*/comparison.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("schema") != COMPARISON_SCHEMA:
            continue
        item = dict(payload)
        item["artifact_path"] = str(path)
        comparisons.append(item)
    comparisons.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return comparisons
