from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
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

STAGES = {"draft", "gate", "execute", "handoff", "record"}
PACKET_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
ABSOLUTE_PATH_PATTERN = re.compile(r"(?i)\b[A-Z]:[\\/][^\s`'\"<>]+")
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY|CREDENTIAL)[A-Z0-9_]*)\s*[:=]\s*[^,\s]+"
)
SECRET_VALUE_PATTERN = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}\b")
ENV_FILE_PATTERN = re.compile(r"(?i)\.env(?:\.[A-Za-z0-9_-]+)?")
REMOTE_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s`'\"<>]+")
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
class ExecutionBoundary:
    status: str
    mode: str
    approval_required: bool
    local_execution: bool
    remote_execution: bool
    summary: str
    next_action: str


@dataclass(frozen=True)
class HandoffSummary:
    status: str
    mode: str
    ready: bool
    lane: str
    gate_status: str
    execution_status: str
    evidence_status: str
    includes_evidence: bool
    summary: str
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
    execution_boundary: ExecutionBoundary
    handoff: HandoffSummary
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
    elif stage == "execute":
        status = "execution-ready"
        next_action = "Operator approval is required before any future runner can execute this packet."
    elif stage == "handoff":
        status = "handoff-ready"
        next_action = "Review the handoff summary before assigning the next operator or runner."
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


def _execution_boundary(
    stage: str,
    lane: LaneAssignment,
    gate_run: GateRunSummary,
) -> ExecutionBoundary:
    if stage == "draft":
        return ExecutionBoundary(
            status="not-prepared",
            mode="draft",
            approval_required=True,
            local_execution=False,
            remote_execution=False,
            summary="Draft saved; execution boundary has not been prepared.",
            next_action="Run Gate plan before preparing execution.",
        )

    if stage in {"gate", "record"}:
        return ExecutionBoundary(
            status="not-prepared",
            mode="gated-only",
            approval_required=True,
            local_execution=False,
            remote_execution=False,
            summary="Packet was gated without arming an execution boundary.",
            next_action="Use Prepare execute to create a dry-run approval boundary.",
        )

    if gate_run.blocked:
        return ExecutionBoundary(
            status="blocked",
            mode="manual-approval",
            approval_required=True,
            local_execution=False,
            remote_execution=False,
            summary="Execution boundary refused because one or more gates blocked the packet.",
            next_action="Clear blocked gates before preparing execution.",
        )

    if gate_run.warnings:
        return ExecutionBoundary(
            status="needs-review",
            mode="manual-approval",
            approval_required=True,
            local_execution=False,
            remote_execution=False,
            summary="Execution boundary is paused for operator review because gates emitted warnings.",
            next_action="Review warnings before any future runner can execute this packet.",
        )

    mode = "dry-run" if stage == "execute" else "handoff-dry-run"
    next_action = (
        "Review the handoff packet before a future bounded runner slice can execute."
        if stage == "handoff"
        else "Operator approval is required before a future bounded runner slice can execute."
    )
    return ExecutionBoundary(
        status="awaiting-approval",
        mode=mode,
        approval_required=True,
        local_execution=False,
        remote_execution=False,
        summary=f"{lane.name} is prepared behind Hamiltonian gates; no agent or command executed.",
        next_action=next_action,
    )


def _handoff_summary(
    stage: str,
    lane: LaneAssignment,
    gates: list[GateResult],
    gate_run: GateRunSummary,
    execution_boundary: ExecutionBoundary,
    attach_evidence: bool,
) -> HandoffSummary:
    evidence_gate = next((gate for gate in gates if gate.id == "evidence"), None)
    evidence_status = evidence_gate.status if evidence_gate else "unknown"
    includes_evidence = bool(attach_evidence and evidence_status not in {"skipped", "pending", "unknown"})

    if stage != "handoff":
        return HandoffSummary(
            status="not-prepared",
            mode="inactive",
            ready=False,
            lane=lane.name,
            gate_status=gate_run.status,
            execution_status=execution_boundary.status,
            evidence_status=evidence_status,
            includes_evidence=includes_evidence,
            summary="Handoff summary has not been prepared for this packet.",
            next_action="Use Handoff after gates and execution approval state are ready.",
        )

    if gate_run.blocked or execution_boundary.status == "blocked":
        return HandoffSummary(
            status="blocked",
            mode="operator-handoff",
            ready=False,
            lane=lane.name,
            gate_status=gate_run.status,
            execution_status=execution_boundary.status,
            evidence_status=evidence_status,
            includes_evidence=includes_evidence,
            summary="Handoff refused because one or more gates blocked the packet.",
            next_action="Clear blocked gates before handing this packet to another operator or runner.",
        )

    if execution_boundary.status == "needs-review":
        return HandoffSummary(
            status="needs-review",
            mode="operator-handoff",
            ready=False,
            lane=lane.name,
            gate_status=gate_run.status,
            execution_status=execution_boundary.status,
            evidence_status=evidence_status,
            includes_evidence=includes_evidence,
            summary="Handoff is paused because the execution boundary needs review.",
            next_action="Review warnings before handing this packet to another operator or runner.",
        )

    return HandoffSummary(
        status="ready",
        mode="operator-handoff",
        ready=True,
        lane=lane.name,
        gate_status=gate_run.status,
        execution_status=execution_boundary.status,
        evidence_status=evidence_status,
        includes_evidence=includes_evidence,
        summary="Handoff packet is ready for operator review with no agent or command executed.",
        next_action="Use this packet as the local handoff brief for the next bounded work step.",
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
    if stage == "execute":
        return "execution-ready"
    if stage == "handoff":
        return "handoff-ready"
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
        f"- Execution boundary: `{packet.execution_boundary.status}`",
        f"- Handoff: `{packet.handoff.status}`",
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
            "",
            "## Execution Boundary",
            "",
            f"- Status: `{packet.execution_boundary.status}`",
            f"- Mode: `{packet.execution_boundary.mode}`",
            f"- Approval required: `{packet.execution_boundary.approval_required}`",
            f"- Local execution: `{packet.execution_boundary.local_execution}`",
            f"- Remote execution: `{packet.execution_boundary.remote_execution}`",
            f"- Summary: {packet.execution_boundary.summary}",
            f"- Next action: {packet.execution_boundary.next_action}",
            "",
            "## Handoff",
            "",
            f"- Status: `{packet.handoff.status}`",
            f"- Ready: `{packet.handoff.ready}`",
            f"- Lane: `{packet.handoff.lane}`",
            f"- Gate status: `{packet.handoff.gate_status}`",
            f"- Execution status: `{packet.handoff.execution_status}`",
            f"- Evidence status: `{packet.handoff.evidence_status}`",
            f"- Includes evidence: `{packet.handoff.includes_evidence}`",
            f"- Summary: {packet.handoff.summary}",
            f"- Next action: {packet.handoff.next_action}",
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
    lane = _lane_assignment(normalized_agent, normalized_stage)
    gate_run = _gate_run_summary(normalized_stage, gates, evidence_requested)
    execution_boundary = _execution_boundary(normalized_stage, lane, gate_run)
    handoff = _handoff_summary(
        normalized_stage,
        lane,
        gates,
        gate_run,
        execution_boundary,
        evidence_requested,
    )
    packet_json = packet_dir / "task-packet.json"
    packet_md = packet_dir / "task-packet.md"
    packet = TaskPacket(
        packet_id=packet_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        repo=str(repo),
        agent_id=normalized_agent,
        agent_name=AGENTS[normalized_agent],
        lane=lane,
        task=clean_task,
        stage=normalized_stage,
        status=_packet_status(normalized_stage, gates, evidence_requested),
        attach_evidence=evidence_requested,
        gates=gates,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        handoff=handoff,
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


def get_task_packet(repo_path: Path, packet_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    clean_id = packet_id.strip()
    if not PACKET_ID_PATTERN.fullmatch(clean_id):
        raise ValueError("invalid packet id")

    root = tasks_root(repo).resolve()
    packet_json = (root / clean_id / "task-packet.json").resolve()
    if root not in packet_json.parents:
        raise ValueError("packet id resolved outside task storage")
    if not packet_json.exists():
        raise FileNotFoundError("packet not found")
    return load_task_packet(packet_json)


def _sanitize_handoff_text(value: Any) -> str:
    text = str(value or "")
    text = ABSOLUTE_PATH_PATTERN.sub("[redacted-path]", text)
    text = REMOTE_URL_PATTERN.sub("[redacted-url]", text)
    text = SECRET_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=[redacted-secret]", text)
    text = SECRET_VALUE_PATTERN.sub("[redacted-secret]", text)
    text = ENV_FILE_PATTERN.sub("[redacted-env-file]", text)
    return text


def _packet_json_path(repo: Path, packet_id: str) -> Path:
    root = tasks_root(repo).resolve()
    packet_json = (root / packet_id / "task-packet.json").resolve()
    if root not in packet_json.parents:
        raise ValueError("packet id resolved outside task storage")
    return packet_json


def build_sanitized_handoff_export(packet: dict[str, Any], exported_at: str) -> str:
    lane = packet.get("lane", {})
    gate_run = packet.get("gate_run", {})
    execution = packet.get("execution_boundary", {})
    handoff = packet.get("handoff", {})
    gates = packet.get("gates", [])
    evidence_gate = next((gate for gate in gates if gate.get("id") == "evidence"), {})
    blocked_ids = gate_run.get("blocked_gate_ids") or []

    lines = [
        "# Hamiltonian Handoff Export",
        "",
        f"- Packet: `{_sanitize_handoff_text(packet.get('packet_id'))}`",
        f"- Exported: `{_sanitize_handoff_text(exported_at)}`",
        f"- Stage: `{_sanitize_handoff_text(packet.get('stage'))}`",
        f"- Status: `{_sanitize_handoff_text(packet.get('status'))}`",
        f"- Agent: `{_sanitize_handoff_text(packet.get('agent_name'))}`",
        f"- Lane: `{_sanitize_handoff_text(lane.get('status'))}` / `{_sanitize_handoff_text(lane.get('execution'))}`",
        f"- Remote execution: `{bool(execution.get('remote_execution') or lane.get('remote_execution'))}`",
        f"- Evidence: `{_sanitize_handoff_text(evidence_gate.get('status', 'unknown'))}`",
        "",
        "## Task",
        "",
        _sanitize_handoff_text(packet.get("task")),
        "",
        "## Gate Run",
        "",
        f"- Status: `{_sanitize_handoff_text(gate_run.get('status'))}`",
        f"- Completed: `{gate_run.get('completed', 0)}/{gate_run.get('total', 0)}`",
        f"- Blocked gates: `{_sanitize_handoff_text(', '.join(blocked_ids) or 'none')}`",
        f"- Next action: {_sanitize_handoff_text(gate_run.get('next_action'))}",
        "",
        "## Execution Boundary",
        "",
        f"- Status: `{_sanitize_handoff_text(execution.get('status'))}`",
        f"- Mode: `{_sanitize_handoff_text(execution.get('mode'))}`",
        f"- Approval required: `{bool(execution.get('approval_required', True))}`",
        f"- Local execution: `{bool(execution.get('local_execution'))}`",
        f"- Remote execution: `{bool(execution.get('remote_execution'))}`",
        f"- Summary: {_sanitize_handoff_text(execution.get('summary'))}",
        f"- Next action: {_sanitize_handoff_text(execution.get('next_action'))}",
        "",
        "## Handoff",
        "",
        f"- Status: `{_sanitize_handoff_text(handoff.get('status'))}`",
        f"- Ready: `{bool(handoff.get('ready'))}`",
        f"- Lane: `{_sanitize_handoff_text(handoff.get('lane'))}`",
        f"- Gate status: `{_sanitize_handoff_text(handoff.get('gate_status'))}`",
        f"- Execution status: `{_sanitize_handoff_text(handoff.get('execution_status'))}`",
        f"- Evidence status: `{_sanitize_handoff_text(handoff.get('evidence_status'))}`",
        f"- Includes evidence: `{bool(handoff.get('includes_evidence'))}`",
        f"- Summary: {_sanitize_handoff_text(handoff.get('summary'))}",
        f"- Next action: {_sanitize_handoff_text(handoff.get('next_action'))}",
        "",
        "## Gates",
    ]
    for gate in gates:
        lines.append(
            "- "
            f"{_sanitize_handoff_text(gate.get('name'))}: "
            f"{_sanitize_handoff_text(gate.get('status'))} "
            f"({_sanitize_handoff_text(gate.get('mode'))}). "
            f"{_sanitize_handoff_text(gate.get('summary'))}"
        )
    lines.extend(
        [
            "",
            "## Sanitization",
            "",
            "This export omits repo paths, packet storage paths, artifact paths, file contents, credentials, and remote URLs.",
            "It is a local operator handoff brief, not a publication artifact.",
            "",
        ]
    )
    return "\n".join(lines)


def export_handoff_markdown(repo_path: Path, packet_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    clean_id = packet_id.strip()
    packet = get_task_packet(repo, clean_id)
    packet_json = _packet_json_path(repo, clean_id)
    packet_dir = packet_json.parent
    export_path = (packet_dir / "handoff-export.md").resolve()
    if packet_dir not in export_path.parents:
        raise ValueError("export path resolved outside packet directory")

    exported_at = datetime.now(timezone.utc).isoformat()
    export_text = build_sanitized_handoff_export(packet, exported_at)
    write_text(export_path, export_text)

    export_record = {
        "kind": "sanitized-handoff-markdown",
        "filename": export_path.name,
        "path": str(export_path),
        "exported_at": exported_at,
        "sanitized": True,
        "local_only": True,
    }
    packet.setdefault("files", {})["handoff_export"] = str(export_path)
    packet.setdefault("exports", {})["handoff_markdown"] = export_record
    write_text(packet_json, json.dumps(packet, indent=2))
    return {"packet": packet, "export": export_record}


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
    execution_boundary = packet.get("execution_boundary") or {
        "status": "unknown",
        "mode": "legacy",
        "approval_required": True,
        "local_execution": False,
        "remote_execution": False,
        "summary": "Legacy packet without execution-boundary metadata.",
        "next_action": "Review packet details.",
    }
    handoff = packet.get("handoff") or {
        "status": "unknown",
        "mode": "legacy",
        "ready": False,
        "lane": lane.get("name"),
        "gate_status": gate_run.get("status"),
        "execution_status": execution_boundary.get("status"),
        "evidence_status": evidence_gate.get("status", "unknown"),
        "includes_evidence": False,
        "summary": "Legacy packet without handoff metadata.",
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
        "execution_boundary": execution_boundary,
        "handoff": handoff,
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
