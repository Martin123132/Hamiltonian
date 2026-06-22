from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .adapters import run_repomori_memory_adapter
from .core import ensure_repo, write_text
from .integrations import IntegrationStatus, detect_integrations


LANE_CATALOG: dict[str, dict[str, str]] = {
    "codex": {
        "name": "Codex",
        "kind": "local-agent",
        "summary": "Primary local implementation lane behind Hamiltonian gates.",
    },
    "openclaw": {
        "name": "OpenClaw adapter",
        "kind": "external-agent-adapter",
        "summary": "External agent lane selected through an adapter boundary; no remote execution occurs in this prototype.",
    },
    "hermes": {
        "name": "Hermes adapter",
        "kind": "external-agent-adapter",
        "summary": "External agent lane selected through an adapter boundary; no remote execution occurs in this prototype.",
    },
    "local": {
        "name": "Local runner",
        "kind": "local-runner",
        "summary": "Direct local command lane, still gated before any future execution path.",
    },
}
AGENTS: dict[str, str] = {agent_id: lane["name"] for agent_id, lane in LANE_CATALOG.items()}

STAGES = {"draft", "gate", "record"}
DANGEROUS_MARKERS = (
    "rm -rf",
    "remove-item",
    "format ",
    "del /s",
    "delete secrets",
    "upload secrets",
    ".env",
)


@dataclass(frozen=True)
class GateResult:
    id: str
    name: str
    status: str
    mode: str
    summary: str
    integration: str | None = None
    artifact_path: str | None = None


@dataclass(frozen=True)
class LaneAssignment:
    id: str
    name: str
    kind: str
    status: str
    execution: str
    remote_execution: bool
    summary: str


@dataclass(frozen=True)
class GateRunSummary:
    status: str
    total: int
    completed: int
    pending: int
    skipped: int
    simulated: int
    warnings: int
    blocked: int
    blocked_gate_ids: list[str]
    next_action: str


@dataclass(frozen=True)
class TaskPacket:
    packet_id: str
    created_at: str
    repo: str
    agent_id: str
    agent_name: str
    lane: LaneAssignment
    task: str
    stage: str
    status: str
    attach_evidence: bool
    gates: list[GateResult]
    gate_run: GateRunSummary
    packet_dir: str
    files: dict[str, str]


def tasks_root(repo: Path) -> Path:
    return repo / ".hamiltonian" / "tasks"


def utc_packet_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _integration_by_name(integrations: list[IntegrationStatus]) -> dict[str, IntegrationStatus]:
    return {item.name: item for item in integrations}


def _available(integration_by_name: dict[str, IntegrationStatus], name: str) -> bool:
    item = integration_by_name.get(name)
    return bool(item and item.available)


def _has_dangerous_marker(task: str) -> str | None:
    lowered = task.lower()
    for marker in DANGEROUS_MARKERS:
        if marker in lowered:
            return marker
    return None


def _lane_assignment(agent_id: str, stage: str) -> LaneAssignment:
    lane = LANE_CATALOG[agent_id]
    external = lane["kind"] == "external-agent-adapter"
    return LaneAssignment(
        id=agent_id,
        name=lane["name"],
        kind=lane["kind"],
        status="selected" if stage == "draft" else "assigned",
        execution=(
            "not-started"
            if stage == "draft"
            else "adapter-boundary-only"
            if external
            else "local-boundary-only"
        ),
        remote_execution=False,
        summary=lane["summary"],
    )


def _pending_gates() -> list[GateResult]:
    return [
        GateResult(
            id="memory",
            name="Project memory",
            status="pending",
            mode="draft",
            summary="Draft saved; memory pack will be selected during gating.",
            integration="RepoMori",
        ),
        GateResult(
            id="intent",
            name="Intent and command gate",
            status="pending",
            mode="draft",
            summary="Draft saved; plan and command checks have not run yet.",
            integration="Memento Mori Jester",
        ),
        GateResult(
            id="cost",
            name="Cost and context posture",
            status="pending",
            mode="draft",
            summary="Draft saved; token posture will be estimated during gating.",
            integration="Tokometer / TokenSquash",
        ),
        GateResult(
            id="evidence",
            name="Evidence capture",
            status="skipped",
            mode="operator-choice",
            summary="Evidence was not requested for this draft.",
            integration="AgentLedger",
        ),
    ]


def _gate_run_summary(stage: str, gates: list[GateResult], attach_evidence: bool) -> GateRunSummary:
    pending = sum(1 for gate in gates if gate.status == "pending")
    skipped = sum(1 for gate in gates if gate.status == "skipped")
    simulated = sum(1 for gate in gates if gate.status == "simulated")
    warnings = sum(1 for gate in gates if gate.status == "warn")
    blocked_gate_ids = [gate.id for gate in gates if gate.status == "block"]
    blocked = len(blocked_gate_ids)
    completed = sum(1 for gate in gates if gate.status not in {"pending", "skipped"})

    if stage == "draft":
        status = "pending"
        next_action = "Run Gate plan to check memory, intent, and cost before work starts."
    elif blocked:
        status = "blocked"
        next_action = "Rewrite the task or change lanes before any execution path is allowed."
    elif warnings:
        status = "needs-review"
        next_action = "Review warnings, then keep work bounded before execution."
    elif attach_evidence:
        status = "evidence-attached"
        next_action = "Ready for operator review with local evidence represented; execution remains manual."
    else:
        status = "ready"
        next_action = "Ready for operator review; evidence remains off unless explicitly requested."

    return GateRunSummary(
        status=status,
        total=len(gates),
        completed=completed,
        pending=pending,
        skipped=skipped,
        simulated=simulated,
        warnings=warnings,
        blocked=blocked,
        blocked_gate_ids=blocked_gate_ids,
        next_action=next_action,
    )


def _run_gates(
    repo: Path,
    task: str,
    attach_evidence: bool,
    integrations: list[IntegrationStatus],
    packet_dir: Path,
) -> list[GateResult]:
    by_name = _integration_by_name(integrations)
    gates: list[GateResult] = []

    memory = run_repomori_memory_adapter(repo, packet_dir, integrations)
    gates.append(
        GateResult(
            id="memory",
            name="Project memory",
            status=memory.status,
            mode=memory.mode,
            summary=memory.summary,
            integration=memory.integration,
            artifact_path=memory.artifact_path,
        )
    )

    marker = _has_dangerous_marker(task)
    if marker:
        gates.append(
            GateResult(
                id="intent",
                name="Intent and command gate",
                status="block",
                mode="local-synthetic",
                summary=f"Task contains risky marker `{marker}`; execution remains blocked in the prototype.",
                integration="Memento Mori Jester",
            )
        )
    elif _available(by_name, "Memento Mori Jester"):
        gates.append(
            GateResult(
                id="intent",
                name="Intent and command gate",
                status="pass",
                mode="available-synthetic",
                summary="Jester is available; prototype records that plan and command checks would run.",
                integration="Memento Mori Jester",
            )
        )
    else:
        gates.append(
            GateResult(
                id="intent",
                name="Intent and command gate",
                status="simulated",
                mode="local-synthetic",
                summary="Jester is not installed; Hamiltonian used a synthetic intent and command gate.",
                integration="Memento Mori Jester",
            )
        )

    estimated_tokens = max(1, len(task) // 4)
    cost_status = "warn" if estimated_tokens > 500 else "simulated"
    if _available(by_name, "Tokometer") or _available(by_name, "TokenSquash"):
        cost_status = "pass" if estimated_tokens <= 500 else "warn"
    gates.append(
        GateResult(
            id="cost",
            name="Cost and context posture",
            status=cost_status,
            mode="local-estimate",
            summary=f"Estimated task prompt size is {estimated_tokens} tokens; no model spend occurred.",
            integration="Tokometer / TokenSquash",
        )
    )

    if not attach_evidence:
        gates.append(
            GateResult(
                id="evidence",
                name="Evidence capture",
                status="skipped",
                mode="operator-choice",
                summary="Evidence was not requested, so AgentLedger was not called or represented.",
                integration="AgentLedger",
            )
        )
        return gates

    evidence_dir = packet_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / "agentledger-placeholder.json"
    installed = _available(by_name, "AgentLedger")
    evidence_payload = {
        "integration": "AgentLedger",
        "kind": "local-placeholder",
        "installed": installed,
        "executed": False,
        "summary": "Evidence was requested, but this prototype slice does not execute agents or shell commands.",
    }
    write_text(evidence_path, json.dumps(evidence_payload, indent=2))
    gates.append(
        GateResult(
            id="evidence",
            name="Evidence capture",
            status="represented" if installed else "simulated",
            mode="local-placeholder",
            summary=(
                "AgentLedger is installed; Hamiltonian wrote a local evidence placeholder without execution."
                if installed
                else "AgentLedger is missing; Hamiltonian wrote a synthetic evidence placeholder."
            ),
            integration="AgentLedger",
            artifact_path=str(evidence_path),
        )
    )
    return gates


def _packet_status(stage: str, gates: list[GateResult], attach_evidence: bool) -> str:
    if any(gate.status == "block" for gate in gates):
        return "blocked"
    if stage == "draft":
        return "drafted"
    if attach_evidence:
        return "recorded"
    return "gated"


def build_packet_markdown(packet: TaskPacket) -> str:
    lines = [
        "# Hamiltonian Task Packet",
        "",
        f"- Packet: `{packet.packet_id}`",
        f"- Repo: `{packet.repo}`",
        f"- Agent: `{packet.agent_name}`",
        f"- Lane kind: `{packet.lane.kind}`",
        f"- Lane execution: `{packet.lane.execution}`",
        f"- Stage: `{packet.stage}`",
        f"- Status: **{packet.status.upper()}**",
        f"- Evidence requested: `{packet.attach_evidence}`",
        "",
        "## Task",
        "",
        packet.task,
        "",
        "## Lane Assignment",
        "",
        f"- Lane: `{packet.lane.name}`",
        f"- Status: `{packet.lane.status}`",
        f"- Remote execution: `{packet.lane.remote_execution}`",
        f"- Summary: {packet.lane.summary}",
        "",
        "## Gates",
    ]
    for gate in packet.gates:
        artifact = f" Artifact: `{gate.artifact_path}`" if gate.artifact_path else ""
        lines.append(f"- {gate.name}: {gate.status} ({gate.mode}). {gate.summary}{artifact}")
    lines.extend(
        [
            "",
            "## Gate Run",
            "",
            f"- Status: `{packet.gate_run.status}`",
            f"- Completed: `{packet.gate_run.completed}/{packet.gate_run.total}`",
            f"- Blocked gates: `{', '.join(packet.gate_run.blocked_gate_ids) or 'none'}`",
            f"- Next action: {packet.gate_run.next_action}",
        ]
    )
    lines.extend(
        [
            "",
            "## Prototype Boundary",
            "",
            "This packet is local and synthetic. It does not execute remote agents, send credentials, or publish data.",
            "",
        ]
    )
    return "\n".join(lines)


def create_task_packet(
    repo_path: Path,
    task: str,
    agent_id: str,
    stage: str = "gate",
    attach_evidence: bool = False,
) -> TaskPacket:
    repo = ensure_repo(repo_path)
    normalized_stage = stage.lower().strip()
    if normalized_stage not in STAGES:
        raise ValueError(f"stage must be one of: {', '.join(sorted(STAGES))}")
    normalized_agent = agent_id.lower().strip()
    if normalized_agent not in AGENTS:
        raise ValueError(f"unknown agent lane: {agent_id}")
    clean_task = task.strip()
    if not clean_task:
        raise ValueError("task must not be empty")

    packet_id = utc_packet_id()
    packet_dir = tasks_root(repo) / packet_id
    packet_dir.mkdir(parents=True, exist_ok=True)

    evidence_requested = bool(attach_evidence or normalized_stage == "record")
    integrations = detect_integrations(repo)
    gates = (
        _pending_gates()
        if normalized_stage == "draft"
        else _run_gates(repo, clean_task, evidence_requested, integrations, packet_dir)
    )
    gate_run = _gate_run_summary(normalized_stage, gates, evidence_requested)
    packet_json = packet_dir / "task-packet.json"
    packet_md = packet_dir / "task-packet.md"
    packet = TaskPacket(
        packet_id=packet_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        repo=str(repo),
        agent_id=normalized_agent,
        agent_name=AGENTS[normalized_agent],
        lane=_lane_assignment(normalized_agent, normalized_stage),
        task=clean_task,
        stage=normalized_stage,
        status=_packet_status(normalized_stage, gates, evidence_requested),
        attach_evidence=evidence_requested,
        gates=gates,
        gate_run=gate_run,
        packet_dir=str(packet_dir),
        files={
            "json": str(packet_json),
            "markdown": str(packet_md),
        },
    )
    write_text(packet_json, json.dumps(asdict(packet), indent=2))
    write_text(packet_md, build_packet_markdown(packet))
    return packet


def load_task_packet(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    gates = packet.get("gates", [])
    evidence_gate = next((gate for gate in gates if gate.get("id") == "evidence"), {})
    memory_gate = next((gate for gate in gates if gate.get("id") == "memory"), {})
    lane = packet.get("lane") or {
        "id": packet.get("agent_id"),
        "name": packet.get("agent_name"),
        "kind": "unknown",
        "status": "unknown",
        "execution": "unknown",
        "remote_execution": False,
        "summary": "Legacy packet without lane metadata.",
    }
    gate_run = packet.get("gate_run") or {
        "status": packet.get("status", "unknown"),
        "total": len(gates),
        "completed": sum(1 for gate in gates if gate.get("status") not in {"pending", "skipped"}),
        "pending": sum(1 for gate in gates if gate.get("status") == "pending"),
        "skipped": sum(1 for gate in gates if gate.get("status") == "skipped"),
        "simulated": sum(1 for gate in gates if gate.get("status") == "simulated"),
        "warnings": sum(1 for gate in gates if gate.get("status") == "warn"),
        "blocked": sum(1 for gate in gates if gate.get("status") == "block"),
        "blocked_gate_ids": [gate.get("id") for gate in gates if gate.get("status") == "block"],
        "next_action": "Review packet details.",
    }
    task = packet.get("task", "")
    return {
        "packet_id": packet.get("packet_id"),
        "created_at": packet.get("created_at"),
        "agent_id": packet.get("agent_id"),
        "agent_name": packet.get("agent_name"),
        "lane": lane,
        "stage": packet.get("stage"),
        "status": packet.get("status"),
        "attach_evidence": packet.get("attach_evidence", False),
        "gate_run": gate_run,
        "memory_status": memory_gate.get("status", "unknown"),
        "memory_mode": memory_gate.get("mode", "unknown"),
        "evidence_status": evidence_gate.get("status", "unknown"),
        "task_excerpt": task if len(task) <= 140 else f"{task[:137]}...",
        "packet_dir": packet.get("packet_dir"),
    }


def list_task_packets(repo_path: Path, limit: int = 8) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = tasks_root(repo)
    if not root.exists():
        return []
    packets: list[dict[str, Any]] = []
    for packet_json in sorted(root.glob("*/task-packet.json"), reverse=True):
        try:
            packets.append(packet_summary(load_task_packet(packet_json)))
        except (OSError, json.JSONDecodeError):
            continue
        if len(packets) >= limit:
            break
    return packets
