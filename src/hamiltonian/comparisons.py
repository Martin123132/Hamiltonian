from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .core import ensure_repo, write_text
from .packets import get_task_packet


COMPARISON_SCHEMA = "hamiltonian.result-comparison.v1"
COMPARISON_EXPORT_SCHEMA = "hamiltonian.comparison-export.v1"
COMPARABLE_LANES = {"codex", "hermes"}
COMPARISON_ID_PATTERN = re.compile(r"^comparison-[A-Za-z0-9T-]{12,64}$")
MAX_COMPARISON_BYTES = 64_000
MAX_DECISION_REASON_CHARS = 500


def comparisons_root(repo: Path) -> Path:
    return repo.resolve() / ".hamiltonian" / "comparisons"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _comparison_dir(repo: Path, comparison_id: str) -> Path:
    clean_id = comparison_id.strip()
    if not COMPARISON_ID_PATTERN.fullmatch(clean_id):
        raise ValueError("invalid comparison id")
    root = comparisons_root(repo).resolve()
    target = (root / clean_id).resolve()
    if root not in target.parents:
        raise ValueError("comparison path escapes local comparison store")
    return target


def _comparison_file(repo: Path, comparison_id: str, filename: str) -> Path:
    root = _comparison_dir(repo, comparison_id)
    target = (root / filename).resolve()
    if target.parent != root:
        raise ValueError("comparison artifact escapes local comparison directory")
    return target


def _read_comparison(repo: Path, comparison_id: str) -> tuple[dict[str, Any], Path]:
    path = _comparison_file(repo, comparison_id, "comparison.json")
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_COMPARISON_BYTES:
        raise ValueError("comparison record is too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != COMPARISON_SCHEMA:
        raise ValueError("unsupported comparison record")
    if payload.get("comparison_id") != comparison_id:
        raise ValueError("comparison id does not match its directory")
    return payload, path


def _public_comparison(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    result = dict(payload)
    result["artifact_path"] = str(path)
    return result


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

    comparison_id = f"comparison-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    comparison_dir = _comparison_dir(repo, comparison_id)
    comparison_dir.mkdir(parents=True, exist_ok=False)
    comparison_path = _comparison_file(repo, comparison_id, "comparison.json")
    comparison = {
        "schema": COMPARISON_SCHEMA,
        "comparison_id": comparison_id,
        "created_at": _utc_now(),
        "workspace_name": repo.name,
        "status": "complete",
        "task_digest": task_digest,
        "primary": _comparison_side(primary, primary_receipt),
        "secondary": _comparison_side(secondary, secondary_receipt),
        "decision": None,
        "result_text_included": False,
        "local_only": True,
        "remote_execution": False,
        "artifact_path": comparison_path.name,
    }
    write_text(comparison_path, json.dumps(comparison, indent=2))
    return _public_comparison(comparison, comparison_path)


def get_result_comparison(repo_path: Path, comparison_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    payload, path = _read_comparison(repo, comparison_id)
    return _public_comparison(payload, path)


def list_result_comparisons(repo_path: Path) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = comparisons_root(repo)
    if not root.exists():
        return []
    comparisons: list[dict[str, Any]] = []
    for path in root.glob("comparison-*/comparison.json"):
        try:
            payload, safe_path = _read_comparison(repo, path.parent.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        comparisons.append(_public_comparison(payload, safe_path))
    comparisons.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return comparisons


def _rehydrate_side(repo: Path, side: dict[str, Any]) -> dict[str, Any]:
    packet_id = str(side.get("packet_id") or "")
    try:
        packet = get_task_packet(repo, packet_id)
    except (FileNotFoundError, ValueError):
        return {"available": False, "result": "", "reason": "Original packet is unavailable."}
    run = packet.get("runner_run") if isinstance(packet.get("runner_run"), dict) else {}
    receipt = run.get("result_receipt") if isinstance(run.get("result_receipt"), dict) else {}
    packet_dir = Path(str(packet.get("packet_dir") or "")).resolve()
    runner_dir = (packet_dir / "runner").resolve()
    result_path_value = str(run.get("final_message_path") or "")
    if not result_path_value:
        return {"available": False, "result": "", "reason": "Original result is unavailable or no longer matches its receipt."}
    result_path = Path(result_path_value).resolve()
    if runner_dir not in result_path.parents or not result_path.is_file() or result_path.stat().st_size > 1_000_000:
        return {"available": False, "result": "", "reason": "Original result is unavailable or outside its packet boundary."}
    result = result_path.read_text(encoding="utf-8")
    result_digest = sha256(result.encode("utf-8")).hexdigest()
    if not result or result_digest != receipt.get("result_digest") or result_digest != side.get("result_digest"):
        return {"available": False, "result": "", "reason": "Original result is unavailable or no longer matches its receipt."}
    return {"available": True, "result": result, "reason": ""}


def hydrate_result_comparison(repo_path: Path, comparison_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    comparison = get_result_comparison(repo, comparison_id)
    return {
        "comparison": comparison,
        "results": {
            "primary": _rehydrate_side(repo, comparison.get("primary") or {}),
            "secondary": _rehydrate_side(repo, comparison.get("secondary") or {}),
        },
    }


def _sanitize_reason(reason: str) -> str:
    value = reason.replace("\r", " ").replace("\n", " ").strip()
    if len(value) > MAX_DECISION_REASON_CHARS:
        raise ValueError("decision reason is too long")
    value = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        value,
    )
    value = re.sub(r"https?://\S+", "<remote-url>", value)
    value = re.sub(r"(?i)(?:[a-z]:\\|/)[^\s\"']+", "<local-path>", value)
    return value


def save_comparison_decision(
    repo_path: Path,
    comparison_id: str,
    selected_lane_id: str,
    reason: str = "",
) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    payload, path = _read_comparison(repo, comparison_id)
    selection = selected_lane_id.lower().strip()
    if selection not in {*COMPARABLE_LANES, "neither"}:
        raise ValueError("decision must select codex, hermes, or neither")
    selected_side = next(
        (
            side
            for side in (payload.get("primary") or {}, payload.get("secondary") or {})
            if side.get("lane_id") == selection
        ),
        None,
    )
    if selection != "neither" and not selected_side:
        raise ValueError("selected lane is not present in this comparison")
    payload["decision"] = {
        "status": "neither" if selection == "neither" else "selected",
        "selected_lane_id": None if selection == "neither" else selection,
        "selected_packet_id": None if selection == "neither" else selected_side.get("packet_id"),
        "reason": _sanitize_reason(reason),
        "decided_at": _utc_now(),
        "operator_selected": True,
    }
    payload["artifact_path"] = path.name
    write_text(path, json.dumps(payload, indent=2))
    return _public_comparison(payload, path)


def export_comparison_receipt(repo_path: Path, comparison_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    payload, _ = _read_comparison(repo, comparison_id)
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else None
    selected = decision.get("selected_lane_id") if decision else None
    reason = decision.get("reason") if decision else "No operator decision recorded."
    lines = [
        "# Hamiltonian Comparison Receipt",
        "",
        f"- Schema: `{COMPARISON_EXPORT_SCHEMA}`",
        f"- Comparison: `{comparison_id}`",
        f"- Created: `{payload.get('created_at')}`",
        f"- Task fingerprint: `{payload.get('task_digest')}`",
        "- Local execution: `true`",
        "- Remote execution: `false`",
        "- Result text included: `false`",
        "",
        "## Result Receipts",
        "",
    ]
    for side_name in ("primary", "secondary"):
        side = payload.get(side_name) or {}
        lines.extend(
            [
                f"### {str(side.get('lane_name') or side.get('lane_id') or side_name).title()}",
                "",
                f"- Lane: `{side.get('lane_id')}`",
                f"- Packet: `{side.get('packet_id')}`",
                f"- Result fingerprint: `{side.get('result_digest')}`",
                f"- Result length: `{side.get('result_length')}`",
                f"- Duration: `{side.get('duration_seconds')}` seconds",
                "",
            ]
        )
    lines.extend(
        [
            "## Operator Decision",
            "",
            f"- Selection: `{selected or 'neither/not recorded'}`",
            f"- Decided: `{decision.get('decided_at') if decision else 'not recorded'}`",
            f"- Reason: {reason or 'No reason supplied.'}",
            "",
            "This receipt intentionally excludes agent answer text and local workspace paths.",
            "",
        ]
    )
    path = _comparison_file(repo, comparison_id, "comparison-export.md")
    write_text(path, "\n".join(lines))
    return {
        "schema": COMPARISON_EXPORT_SCHEMA,
        "comparison_id": comparison_id,
        "filename": path.name,
        "artifact_path": str(path),
        "result_text_included": False,
        "local_only": True,
        "remote_execution": False,
    }
