from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .adapters import run_repomori_memory_adapter
from .core import ensure_repo, is_git_repo, write_text
from .integrations import IntegrationStatus, detect_integrations
from .runners import (
    RunnerPlan,
    RunnerRequest,
    read_latest_runner_state,
    runner_adapter_for_lane,
    runner_plan_from_dict,
    runner_plan_state,
)


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

LANE_CONTRACTS: dict[str, dict[str, Any]] = {
    "codex": {
        "boundary": "local implementation lane",
        "best_for": ["repo edits", "tests", "multi-file implementation", "handoff repair"],
        "avoid_for": ["unreviewed remote actions", "credential handling"],
        "evidence_policy": "Attach AgentLedger only when requested.",
    },
    "openclaw": {
        "boundary": "external adapter lane",
        "best_for": ["third-party agent experiments", "compatibility probes", "operator comparison"],
        "avoid_for": ["direct execution", "private repo scraping", "credentialed work"],
        "evidence_policy": "Represent evidence locally until a real adapter is wired.",
    },
    "hermes": {
        "boundary": "external adapter lane",
        "best_for": ["structured handoff", "agent comparison", "adapter proving"],
        "avoid_for": ["direct execution", "private repo scraping", "credentialed work"],
        "evidence_policy": "Represent evidence locally until a real adapter is wired.",
    },
    "local": {
        "boundary": "local command lane",
        "best_for": ["small scripts", "shell checks", "test commands", "repo inspection"],
        "avoid_for": ["large autonomous edits", "remote actions", "unsafe destructive commands"],
        "evidence_policy": "Use Hamiltonian reports or AgentLedger when proof matters.",
    },
}

CODE_TASK_MARKERS = (
    "patch",
    "fix",
    "implement",
    "refactor",
    "test",
    "tests",
    "ui",
    "api",
    "server",
    "bug",
)
LOCAL_TASK_MARKERS = ("command", "script", "shell", "pytest", "doctor", "compile", "smoke")
HANDOFF_TASK_MARKERS = ("handoff", "summarize", "brief", "compare", "review", "plan")
EVIDENCE_TASK_MARKERS = ("record", "evidence", "proof", "audit", "trace")

TASK_INDEX_SCHEMA = "hamiltonian.task-index.v1"
STAGE_ORDER = ("draft", "gate", "execute", "handoff", "record")
STAGES = set(STAGE_ORDER)
ADVANCE_STAGES = STAGE_ORDER[1:]
STAGE_RANK = {stage: index for index, stage in enumerate(STAGE_ORDER)}
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
class RouteDecision:
    selected_lane_id: str
    selected_lane_name: str
    recommended_lane_id: str
    recommended_lane_name: str
    status: str
    confidence: int
    summary: str
    reasons: list[str]
    warnings: list[str]
    remote_execution: bool
    policy: str


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
    updated_at: str
    repo: str
    agent_id: str
    agent_name: str
    lane: LaneAssignment
    route: RouteDecision
    task: str
    stage: str
    status: str
    attach_evidence: bool
    gates: list[GateResult]
    gate_run: GateRunSummary
    execution_boundary: ExecutionBoundary
    runner_plan: RunnerPlan
    handoff: HandoffSummary
    history: list[dict[str, Any]]
    packet_dir: str
    files: dict[str, str]


def tasks_root(repo: Path) -> Path:
    return repo / ".hamiltonian" / "tasks"


def task_index_path(repo: Path) -> Path:
    return tasks_root(repo) / "index.json"


def packet_history_path(packet_dir: Path) -> Path:
    return packet_dir / "history.json"


def utc_packet_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid4().hex[:8]}"


def _integration_by_name(integrations: list[IntegrationStatus]) -> dict[str, IntegrationStatus]:
    return {item.name: item for item in integrations}


def _available(integration_by_name: dict[str, IntegrationStatus], name: str) -> bool:
    item = integration_by_name.get(name)
    return bool(item and item.available)


def _route_git_available(repo: Path) -> bool:
    if not (repo / ".git").exists():
        return False
    return is_git_repo(repo)


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


def build_lane_contracts(
    git_available: bool,
    integrations: list[IntegrationStatus],
) -> list[dict[str, Any]]:
    by_name = _integration_by_name(integrations)
    contracts: list[dict[str, Any]] = []
    for lane_id, lane in LANE_CATALOG.items():
        contract = LANE_CONTRACTS[lane_id]
        external = lane["kind"] == "external-agent-adapter"
        status = "adapter-boundary" if external else "ready"
        if lane_id == "codex" and not git_available:
            status = "limited"
        contracts.append(
            {
                "id": lane_id,
                "name": lane["name"],
                "kind": lane["kind"],
                "status": status,
                "boundary": contract["boundary"],
                "best_for": list(contract["best_for"]),
                "avoid_for": list(contract["avoid_for"]),
                "required_gates": ["memory", "intent", "cost"],
                "remote_execution": False,
                "evidence_policy": contract["evidence_policy"],
                "adapter_ready": not external,
                "memory_available": _available(by_name, "RepoMori"),
            }
        )
    return contracts


def _contains_any(task: str, markers: tuple[str, ...]) -> bool:
    lowered = task.lower()
    return any(marker in lowered for marker in markers)


def build_route_recommendations(
    task: str = "",
    selected_agent_id: str | None = None,
    git_available: bool = True,
    integrations: list[IntegrationStatus] | None = None,
) -> list[dict[str, Any]]:
    integrations = integrations or []
    selected = (selected_agent_id or "").lower().strip()
    code_task = _contains_any(task, CODE_TASK_MARKERS)
    local_task = _contains_any(task, LOCAL_TASK_MARKERS)
    handoff_task = _contains_any(task, HANDOFF_TASK_MARKERS)
    evidence_task = _contains_any(task, EVIDENCE_TASK_MARKERS)
    risky_marker = _has_dangerous_marker(task)

    base_scores = {"codex": 82, "local": 70, "hermes": 54, "openclaw": 52}
    recommendations: list[dict[str, Any]] = []
    for lane_id, lane in LANE_CATALOG.items():
        external = lane["kind"] == "external-agent-adapter"
        score = base_scores[lane_id]
        reasons = [LANE_CONTRACTS[lane_id]["boundary"]]
        warnings: list[str] = []

        if lane_id == "codex":
            if git_available:
                reasons.append("repo-aware local implementation lane")
            else:
                score -= 8
                warnings.append("Git metadata is unavailable for this workspace.")
            if code_task:
                score += 12
                reasons.append("task looks like implementation or verification work")
            if local_task and not code_task:
                score -= 6
                reasons.append("task looks like a small local command, so the local runner may be cleaner")
            if evidence_task:
                score += 4
        elif lane_id == "local":
            if local_task:
                score += 13
                reasons.append("task looks like a bounded local command or smoke check")
            if code_task:
                score -= 4
            if evidence_task:
                score += 3
        elif lane_id == "hermes":
            if handoff_task:
                score += 8
                reasons.append("task includes handoff, review, or structured comparison language")
        elif lane_id == "openclaw":
            if "openclaw" in task.lower() or "open claw" in task.lower():
                score += 8
                reasons.append("task explicitly references OpenClaw")

        if selected == lane_id:
            score += 3
            reasons.append("operator selected this lane")

        if external:
            score = min(score, 66)
            warnings.append("Adapter is represented locally; remote execution is off.")
        if risky_marker:
            score = min(score, 60)
            warnings.append(f"Intent gate must clear risky marker `{risky_marker}` before execution.")

        recommendations.append(
            {
                "lane_id": lane_id,
                "lane_name": lane["name"],
                "rank": 0,
                "score": max(1, min(99, score)),
                "status": "available",
                "summary": LANE_CATALOG[lane_id]["summary"],
                "reasons": reasons,
                "warnings": warnings,
                "remote_execution": False,
                "selected": selected == lane_id,
            }
        )

    recommendations.sort(key=lambda item: (-int(item["score"]), str(item["lane_id"])))
    for index, item in enumerate(recommendations, start=1):
        item["rank"] = index
        if index == 1:
            item["status"] = "recommended"
        elif item["warnings"]:
            item["status"] = "review"
    return recommendations


def recommend_route(
    task: str,
    selected_agent_id: str,
    git_available: bool,
    integrations: list[IntegrationStatus],
) -> RouteDecision:
    selected = selected_agent_id.lower().strip()
    recommendations = build_route_recommendations(
        task=task,
        selected_agent_id=selected,
        git_available=git_available,
        integrations=integrations,
    )
    top = recommendations[0]
    selected_item = next(
        (item for item in recommendations if item["lane_id"] == selected),
        top,
    )
    recommended_id = str(top["lane_id"])
    status = "recommended" if selected == recommended_id else "operator-override"
    warnings = list(selected_item["warnings"])
    if status == "operator-override":
        warnings.append(
            f"Hamiltonian recommends {top['lane_name']} first, but will keep the operator-selected lane."
        )

    return RouteDecision(
        selected_lane_id=selected,
        selected_lane_name=AGENTS[selected],
        recommended_lane_id=recommended_id,
        recommended_lane_name=str(top["lane_name"]),
        status=status,
        confidence=int(top["score"]),
        summary=(
            f"Recommended {top['lane_name']} for this packet; "
            f"selected lane is {AGENTS[selected]}."
        ),
        reasons=list(top["reasons"]),
        warnings=warnings,
        remote_execution=False,
        policy=(
            "Route advice is local metadata only and never launches an agent. "
            "Execution requires a separate operator action; remote execution stays off."
        ),
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
        next_action = "Operator approval is required before the bounded local runner can execute this packet."
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
    runner_run: dict[str, Any] | None = None,
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
            next_action="Use Prepare execute to create an explicit local approval boundary.",
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

    run_status = str((runner_run or {}).get("status") or "not-started")
    if stage == "handoff" and run_status == "succeeded":
        return ExecutionBoundary(
            status="completed",
            mode="local-codex",
            approval_required=False,
            local_execution=True,
            remote_execution=False,
            summary="The bounded local Codex run completed before handoff.",
            next_action="Review the local runner report and prepare the operator handoff.",
        )
    if stage == "handoff" and run_status in {"failed", "timed-out", "cancelled", "interrupted"}:
        return ExecutionBoundary(
            status="run-failed",
            mode="local-codex",
            approval_required=True,
            local_execution=True,
            remote_execution=False,
            summary=f"The bounded local Codex run ended as {run_status}.",
            next_action="Review or retry the local run before treating the work as complete.",
        )

    mode = "dry-run" if stage == "execute" else "handoff-dry-run"
    next_action = (
        "Review the handoff packet before assigning the next bounded work step."
        if stage == "handoff"
        else "Review the runner plan and explicitly launch the bounded local adapter when ready."
    )
    return ExecutionBoundary(
        status="awaiting-approval",
        mode=mode,
        approval_required=True,
        local_execution=False,
        remote_execution=False,
        summary=f"{lane.name} is prepared behind Hamiltonian gates; no local run has started yet.",
        next_action=next_action,
    )


def _runner_plan(
    repo: Path,
    packet_dir: Path,
    packet_id: str,
    task: str,
    stage: str,
    lane: LaneAssignment,
    gate_run: GateRunSummary,
    execution_boundary: ExecutionBoundary,
    attach_evidence: bool,
    previous_plan: dict[str, Any] | None = None,
) -> RunnerPlan:
    if gate_run.blocked or execution_boundary.status == "blocked":
        return runner_plan_state(
            lane_id=lane.id,
            status="blocked",
            mode="local-dry-run",
            summary="Runner plan was not prepared because readiness gates blocked the packet.",
            next_action="Clear blocked gates before preparing a launch plan.",
        )
    if execution_boundary.status == "needs-review":
        return runner_plan_state(
            lane_id=lane.id,
            status="needs-review",
            mode="local-dry-run",
            summary="Runner plan is paused until the operator reviews gate warnings.",
            next_action="Review warnings before preparing a launch plan.",
        )
    if stage == "handoff" and execution_boundary.status in {"completed", "run-failed"} and previous_plan:
        return runner_plan_from_dict(previous_plan)
    if stage not in {"execute", "handoff"} or execution_boundary.status != "awaiting-approval":
        return runner_plan_state(
            lane_id=lane.id,
            status="not-prepared",
            mode="inactive",
            summary="Runner contract is available but no launch plan has been prepared for this stage.",
            next_action="Run gates, then use Prepare execute to write the local dry-run plan.",
        )

    request = RunnerRequest(
        packet_id=packet_id,
        lane_id=lane.id,
        repo=repo,
        task=task,
        gate_status=gate_run.status,
        blocked_gate_ids=tuple(gate_run.blocked_gate_ids),
        attach_evidence=attach_evidence,
    )
    return runner_adapter_for_lane(lane.id).prepare(request, packet_dir)


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

    if execution_boundary.status == "run-failed":
        return HandoffSummary(
            status="needs-review",
            mode="operator-handoff",
            ready=False,
            lane=lane.name,
            gate_status=gate_run.status,
            execution_status=execution_boundary.status,
            evidence_status=evidence_status,
            includes_evidence=includes_evidence,
            summary="Handoff is paused because the bounded local run did not succeed.",
            next_action="Review or retry the local run before handing off this packet as complete.",
        )

    completed_run = execution_boundary.status == "completed"

    return HandoffSummary(
        status="ready",
        mode="operator-handoff",
        ready=True,
        lane=lane.name,
        gate_status=gate_run.status,
        execution_status=execution_boundary.status,
        evidence_status=evidence_status,
        includes_evidence=includes_evidence,
        summary=(
            "Handoff packet is ready with a completed bounded local runner result."
            if completed_run
            else "Handoff packet is ready for operator review; no local run was started."
        ),
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
        "summary": "Evidence was requested; this placeholder does not execute AgentLedger or capture runner output.",
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


def _packet_status(
    stage: str,
    gates: list[GateResult],
    attach_evidence: bool,
    handoff: HandoffSummary | None = None,
) -> str:
    if any(gate.status == "block" for gate in gates):
        return "blocked"
    if stage == "draft":
        return "drafted"
    if stage == "execute":
        return "execution-ready"
    if stage == "handoff":
        if handoff is not None and not handoff.ready:
            return handoff.status
        return "handoff-ready"
    if attach_evidence:
        return "recorded"
    return "gated"


def _history_event(
    event: str,
    at: str,
    stage: str,
    status: str,
    summary: str,
    attach_evidence: bool,
    from_stage: str | None = None,
    to_stage: str | None = None,
    from_agent: str | None = None,
    to_agent: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": event,
        "at": at,
        "stage": stage,
        "status": status,
        "summary": summary,
        "attach_evidence": attach_evidence,
        "local_only": True,
        "remote_execution": False,
    }
    if from_stage is not None:
        record["from_stage"] = from_stage
    if to_stage is not None:
        record["to_stage"] = to_stage
    if from_agent is not None:
        record["from_agent"] = from_agent
    if to_agent is not None:
        record["to_agent"] = to_agent
    return record


def build_packet_markdown(packet: TaskPacket) -> str:
    lines = [
        "# Hamiltonian Task Packet",
        "",
        f"- Packet: `{packet.packet_id}`",
        f"- Repo: `{packet.repo}`",
        f"- Created: `{packet.created_at}`",
        f"- Updated: `{packet.updated_at}`",
        f"- Agent: `{packet.agent_name}`",
        f"- Lane kind: `{packet.lane.kind}`",
        f"- Lane execution: `{packet.lane.execution}`",
        f"- Route: `{packet.route.status}`",
        f"- Stage: `{packet.stage}`",
        f"- Status: **{packet.status.upper()}**",
        f"- Evidence requested: `{packet.attach_evidence}`",
        f"- Execution boundary: `{packet.execution_boundary.status}`",
        f"- Runner plan: `{packet.runner_plan.status}`",
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
        "## Route Decision",
        "",
        f"- Recommended: `{packet.route.recommended_lane_name}`",
        f"- Selected: `{packet.route.selected_lane_name}`",
        f"- Confidence: `{packet.route.confidence}`",
        f"- Remote execution: `{packet.route.remote_execution}`",
        f"- Summary: {packet.route.summary}",
        f"- Policy: {packet.route.policy}",
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
            "## Runner Plan",
            "",
            f"- Schema: `{packet.runner_plan.schema}`",
            f"- Adapter: `{packet.runner_plan.adapter_id}`",
            f"- Status: `{packet.runner_plan.status}`",
            f"- Mode: `{packet.runner_plan.mode}`",
            f"- Lifecycle: `{', '.join(packet.runner_plan.lifecycle)}`",
            f"- Launch supported: `{packet.runner_plan.launch_supported}`",
            f"- Local execution: `{packet.runner_plan.local_execution}`",
            f"- Remote execution: `{packet.runner_plan.remote_execution}`",
            f"- Summary: {packet.runner_plan.summary}",
            f"- Next action: {packet.runner_plan.next_action}",
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
            "",
            "## History",
        ]
    )
    if packet.history:
        for event in packet.history:
            lines.append(
                f"- {event.get('at')}: {event.get('event')} "
                f"{event.get('from_stage', event.get('stage'))} -> "
                f"{event.get('to_stage', event.get('stage'))}. "
                f"{event.get('summary')}"
            )
    else:
        lines.append("- No history events recorded.")
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
    created_at = datetime.now(timezone.utc).isoformat()

    evidence_requested = bool(attach_evidence or normalized_stage == "record")
    integrations = detect_integrations(repo)
    route = recommend_route(clean_task, normalized_agent, _route_git_available(repo), integrations)
    gates = (
        _pending_gates()
        if normalized_stage == "draft"
        else _run_gates(repo, clean_task, evidence_requested, integrations, packet_dir)
    )
    lane = _lane_assignment(normalized_agent, normalized_stage)
    gate_run = _gate_run_summary(normalized_stage, gates, evidence_requested)
    execution_boundary = _execution_boundary(normalized_stage, lane, gate_run)
    runner_plan = _runner_plan(
        repo=repo,
        packet_dir=packet_dir,
        packet_id=packet_id,
        task=clean_task,
        stage=normalized_stage,
        lane=lane,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        attach_evidence=evidence_requested,
    )
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
    history_path = packet_history_path(packet_dir)
    status = _packet_status(normalized_stage, gates, evidence_requested, handoff)
    files = {
        "json": str(packet_json),
        "markdown": str(packet_md),
        "history": str(history_path),
    }
    if runner_plan.artifact_path:
        files["runner_plan"] = runner_plan.artifact_path
    history = [
        _history_event(
            event="created",
            at=created_at,
            stage=normalized_stage,
            status=status,
            summary="Created local task packet.",
            attach_evidence=evidence_requested,
        )
    ]
    packet = TaskPacket(
        packet_id=packet_id,
        created_at=created_at,
        updated_at=created_at,
        repo=str(repo),
        agent_id=normalized_agent,
        agent_name=AGENTS[normalized_agent],
        lane=lane,
        route=route,
        task=clean_task,
        stage=normalized_stage,
        status=status,
        attach_evidence=evidence_requested,
        gates=gates,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        runner_plan=runner_plan,
        handoff=handoff,
        history=history,
        packet_dir=str(packet_dir),
        files=files,
    )
    write_text(history_path, json.dumps(history, indent=2))
    write_text(packet_json, json.dumps(asdict(packet), indent=2))
    write_text(packet_md, build_packet_markdown(packet))
    write_task_index(repo)
    return packet


def advance_task_packet(
    repo_path: Path,
    packet_id: str,
    stage: str,
    attach_evidence: bool = False,
) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    target_stage = stage.lower().strip()
    if target_stage not in ADVANCE_STAGES:
        raise ValueError(f"stage must be one of: {', '.join(ADVANCE_STAGES)}")

    packet = get_task_packet(repo, packet_id)
    current_stage = str(packet.get("stage") or "draft").lower().strip()
    if current_stage not in STAGES:
        raise ValueError(f"packet has unknown stage: {current_stage}")
    if STAGE_RANK[target_stage] <= STAGE_RANK[current_stage]:
        raise ValueError(f"target stage must advance packet forward from {current_stage}")

    clean_task = str(packet.get("task") or "").strip()
    if not clean_task:
        raise ValueError("task must not be empty")

    agent_id = str(packet.get("agent_id") or "codex").lower().strip()
    if agent_id not in AGENTS:
        raise ValueError(f"unknown agent lane: {agent_id}")

    packet_json = _packet_json_path(repo, str(packet.get("packet_id") or packet_id))
    packet_dir = packet_json.parent
    packet_md = packet_dir / "task-packet.md"
    history_path = packet_history_path(packet_dir)
    updated_at = datetime.now(timezone.utc).isoformat()
    created_at = str(packet.get("created_at") or updated_at)

    evidence_requested = bool(
        attach_evidence or packet.get("attach_evidence") or target_stage == "record"
    )
    integrations = detect_integrations(repo)
    route = recommend_route(clean_task, agent_id, _route_git_available(repo), integrations)
    gates = _run_gates(repo, clean_task, evidence_requested, integrations, packet_dir)
    lane = _lane_assignment(agent_id, target_stage)
    gate_run = _gate_run_summary(target_stage, gates, evidence_requested)
    runner_run = packet.get("runner_run") if isinstance(packet.get("runner_run"), dict) else None
    if target_stage == "handoff" and str((runner_run or {}).get("status")) in {"starting", "running", "cancelling"}:
        raise ValueError("cannot prepare handoff while a local runner is active")
    execution_boundary = _execution_boundary(target_stage, lane, gate_run, runner_run=runner_run)
    runner_plan = _runner_plan(
        repo=repo,
        packet_dir=packet_dir,
        packet_id=str(packet.get("packet_id") or packet_id),
        task=clean_task,
        stage=target_stage,
        lane=lane,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        attach_evidence=evidence_requested,
        previous_plan=packet.get("runner_plan") if isinstance(packet.get("runner_plan"), dict) else None,
    )
    handoff = _handoff_summary(
        target_stage,
        lane,
        gates,
        gate_run,
        execution_boundary,
        evidence_requested,
    )
    status = _packet_status(target_stage, gates, evidence_requested, handoff)
    files = {
        "json": str(packet_json),
        "markdown": str(packet_md),
        "history": str(history_path),
    }
    if runner_plan.artifact_path:
        files["runner_plan"] = runner_plan.artifact_path
    history = [event for event in packet.get("history", []) if isinstance(event, dict)]
    if not history:
        history = [
            _history_event(
                event="created",
                at=created_at,
                stage=current_stage,
                status=str(packet.get("status") or "unknown"),
                summary="Recovered creation event from packet metadata.",
                attach_evidence=bool(packet.get("attach_evidence")),
            )
        ]
    history.append(
        _history_event(
            event="advanced",
            at=updated_at,
            stage=target_stage,
            status=status,
            summary=f"Advanced packet from {current_stage} to {target_stage} using local gates.",
            attach_evidence=evidence_requested,
            from_stage=current_stage,
            to_stage=target_stage,
        )
    )

    packet_obj = TaskPacket(
        packet_id=str(packet.get("packet_id") or packet_id),
        created_at=created_at,
        updated_at=updated_at,
        repo=str(repo),
        agent_id=agent_id,
        agent_name=AGENTS[agent_id],
        lane=lane,
        route=route,
        task=clean_task,
        stage=target_stage,
        status=status,
        attach_evidence=evidence_requested,
        gates=gates,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        runner_plan=runner_plan,
        handoff=handoff,
        history=history,
        packet_dir=str(packet_dir),
        files=files,
    )
    packet_data = asdict(packet_obj)
    write_text(history_path, json.dumps(history, indent=2))
    write_text(packet_json, json.dumps(packet_data, indent=2))
    write_text(packet_md, build_packet_markdown(packet_obj))
    write_task_index(repo)
    return packet_data


def select_task_packet_lane(
    repo_path: Path,
    packet_id: str,
    agent_id: str,
) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    normalized_agent = agent_id.lower().strip()
    if normalized_agent not in AGENTS:
        raise ValueError(f"unknown agent lane: {agent_id}")

    packet = get_task_packet(repo, packet_id)
    current_stage = str(packet.get("stage") or "draft").lower().strip()
    if current_stage not in STAGES:
        raise ValueError(f"packet has unknown stage: {current_stage}")

    clean_task = str(packet.get("task") or "").strip()
    if not clean_task:
        raise ValueError("task must not be empty")

    packet_json = _packet_json_path(repo, str(packet.get("packet_id") or packet_id))
    packet_dir = packet_json.parent
    packet_md = packet_dir / "task-packet.md"
    history_path = packet_history_path(packet_dir)
    updated_at = datetime.now(timezone.utc).isoformat()
    created_at = str(packet.get("created_at") or updated_at)
    previous_agent = str(packet.get("agent_id") or "codex").lower().strip()
    if previous_agent not in AGENTS:
        previous_agent = "codex"

    evidence_requested = bool(packet.get("attach_evidence") or current_stage == "record")
    integrations = detect_integrations(repo)
    route = recommend_route(
        clean_task,
        normalized_agent,
        _route_git_available(repo),
        integrations,
    )
    gates = (
        _pending_gates()
        if current_stage == "draft"
        else _run_gates(repo, clean_task, evidence_requested, integrations, packet_dir)
    )
    lane = _lane_assignment(normalized_agent, current_stage)
    gate_run = _gate_run_summary(current_stage, gates, evidence_requested)
    runner_run = packet.get("runner_run") if isinstance(packet.get("runner_run"), dict) else None
    execution_boundary = _execution_boundary(current_stage, lane, gate_run, runner_run=runner_run)
    runner_plan = _runner_plan(
        repo=repo,
        packet_dir=packet_dir,
        packet_id=str(packet.get("packet_id") or packet_id),
        task=clean_task,
        stage=current_stage,
        lane=lane,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        attach_evidence=evidence_requested,
        previous_plan=packet.get("runner_plan") if isinstance(packet.get("runner_plan"), dict) else None,
    )
    handoff = _handoff_summary(
        current_stage,
        lane,
        gates,
        gate_run,
        execution_boundary,
        evidence_requested,
    )
    status = _packet_status(current_stage, gates, evidence_requested, handoff)
    files = {
        "json": str(packet_json),
        "markdown": str(packet_md),
        "history": str(history_path),
    }
    if runner_plan.artifact_path:
        files["runner_plan"] = runner_plan.artifact_path
    history = [event for event in packet.get("history", []) if isinstance(event, dict)]
    if not history:
        history = [
            _history_event(
                event="created",
                at=created_at,
                stage=current_stage,
                status=str(packet.get("status") or "unknown"),
                summary="Recovered creation event from packet metadata.",
                attach_evidence=bool(packet.get("attach_evidence")),
            )
        ]
    history.append(
        _history_event(
            event="lane-selected",
            at=updated_at,
            stage=current_stage,
            status=status,
            summary=(
                f"Changed packet lane from {AGENTS[previous_agent]} to "
                f"{AGENTS[normalized_agent]} using local route metadata."
            ),
            attach_evidence=evidence_requested,
            from_agent=previous_agent,
            to_agent=normalized_agent,
        )
    )

    packet_obj = TaskPacket(
        packet_id=str(packet.get("packet_id") or packet_id),
        created_at=created_at,
        updated_at=updated_at,
        repo=str(repo),
        agent_id=normalized_agent,
        agent_name=AGENTS[normalized_agent],
        lane=lane,
        route=route,
        task=clean_task,
        stage=current_stage,
        status=status,
        attach_evidence=evidence_requested,
        gates=gates,
        gate_run=gate_run,
        execution_boundary=execution_boundary,
        runner_plan=runner_plan,
        handoff=handoff,
        history=history,
        packet_dir=str(packet_dir),
        files=files,
    )
    packet_data = asdict(packet_obj)
    write_text(history_path, json.dumps(history, indent=2))
    write_text(packet_json, json.dumps(packet_data, indent=2))
    write_text(packet_md, build_packet_markdown(packet_obj))
    write_task_index(repo)
    return packet_data


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
    packet = load_task_packet(packet_json)
    runner_run = read_latest_runner_state(packet_json.parent)
    if runner_run is not None:
        packet["runner_run"] = runner_run
    return packet


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
    route = packet.get("route", {})
    gate_run = packet.get("gate_run", {})
    execution = packet.get("execution_boundary", {})
    runner_plan = packet.get("runner_plan", {})
    runner_run = packet.get("runner_run", {})
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
        f"- Route: `{_sanitize_handoff_text(route.get('status', 'unknown'))}`",
        f"- Remote execution: `{bool(execution.get('remote_execution') or lane.get('remote_execution'))}`",
        f"- Evidence: `{_sanitize_handoff_text(evidence_gate.get('status', 'unknown'))}`",
        "",
        "## Task",
        "",
        _sanitize_handoff_text(packet.get("task")),
        "",
        "## Route Decision",
        "",
        f"- Recommended: `{_sanitize_handoff_text(route.get('recommended_lane_name', packet.get('agent_name')))}`",
        f"- Selected: `{_sanitize_handoff_text(route.get('selected_lane_name', packet.get('agent_name')))}`",
        f"- Confidence: `{int(route.get('confidence', 0) or 0)}`",
        f"- Remote execution: `{bool(route.get('remote_execution'))}`",
        f"- Summary: {_sanitize_handoff_text(route.get('summary', 'No route decision recorded.'))}",
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
        "## Runner Plan",
        "",
        f"- Adapter: `{_sanitize_handoff_text(runner_plan.get('adapter_id', 'legacy'))}`",
        f"- Status: `{_sanitize_handoff_text(runner_plan.get('status', 'unknown'))}`",
        f"- Mode: `{_sanitize_handoff_text(runner_plan.get('mode', 'unknown'))}`",
        f"- Launch supported: `{bool(runner_plan.get('launch_supported'))}`",
        f"- Local execution: `{bool(runner_plan.get('local_execution'))}`",
        f"- Remote execution: `{bool(runner_plan.get('remote_execution'))}`",
        f"- Summary: {_sanitize_handoff_text(runner_plan.get('summary', 'No runner plan recorded.'))}",
        "",
        "## Local Runner Result",
        "",
        f"- Status: `{_sanitize_handoff_text(runner_run.get('status', 'not-started'))}`",
        f"- Local execution: `{bool(runner_run.get('local_execution'))}`",
        f"- Remote execution: `{bool(runner_run.get('remote_execution'))}`",
        f"- Exit code: `{_sanitize_handoff_text(runner_run.get('exit_code'))}`",
        f"- Timed out: `{bool(runner_run.get('timed_out'))}`",
        f"- Summary: {_sanitize_handoff_text(runner_run.get('summary', 'No local run result recorded.'))}",
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
    write_task_index(repo)
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
    route = packet.get("route") or {
        "selected_lane_id": packet.get("agent_id"),
        "selected_lane_name": packet.get("agent_name"),
        "recommended_lane_id": packet.get("agent_id"),
        "recommended_lane_name": packet.get("agent_name"),
        "status": "legacy",
        "confidence": 0,
        "summary": "Legacy packet without route metadata.",
        "reasons": [],
        "warnings": [],
        "remote_execution": False,
        "policy": "Legacy packet; review details before use.",
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
    runner_plan = packet.get("runner_plan") or {
        "schema": "hamiltonian.runner-contract.legacy",
        "adapter_id": f"{lane.get('id') or 'unknown'}-legacy",
        "lane_id": lane.get("id") or packet.get("agent_id"),
        "status": "unknown",
        "mode": "legacy",
        "lifecycle": [],
        "approval_required": True,
        "launch_supported": False,
        "local_only": True,
        "local_execution": False,
        "remote_execution": False,
        "workspace_name": "",
        "task_digest": "",
        "task_length": 0,
        "artifact_path": None,
        "summary": "Legacy packet without runner-plan metadata.",
        "next_action": "Review packet details before any launch.",
    }
    runner_run = packet.get("runner_run") or {
        "schema": "hamiltonian.runner-run.v1",
        "status": "not-started",
        "local_execution": False,
        "remote_execution": False,
        "summary": "No local runner has started for this packet.",
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
    handoff_export = (packet.get("exports") or {}).get("handoff_markdown") or {}
    history = packet.get("history") if isinstance(packet.get("history"), list) else []
    last_event = history[-1] if history and isinstance(history[-1], dict) else {}
    return {
        "packet_id": packet.get("packet_id"),
        "created_at": packet.get("created_at"),
        "updated_at": packet.get("updated_at") or packet.get("created_at"),
        "agent_id": packet.get("agent_id"),
        "agent_name": packet.get("agent_name"),
        "lane": lane,
        "route": route,
        "stage": packet.get("stage"),
        "status": packet.get("status"),
        "attach_evidence": packet.get("attach_evidence", False),
        "gate_run": gate_run,
        "execution_boundary": execution_boundary,
        "runner_plan": runner_plan,
        "runner_run": runner_run,
        "handoff": handoff,
        "memory_status": memory_gate.get("status", "unknown"),
        "memory_mode": memory_gate.get("mode", "unknown"),
        "evidence_status": evidence_gate.get("status", "unknown"),
        "has_handoff_export": bool(handoff_export),
        "handoff_export_filename": handoff_export.get("filename"),
        "history_count": len(history),
        "last_event": last_event.get("event"),
        "task_excerpt": task if len(task) <= 140 else f"{task[:137]}...",
        "packet_dir": packet.get("packet_dir"),
    }


def _index_packet_summary(packet: dict[str, Any]) -> dict[str, Any]:
    summary = packet_summary(packet)
    summary.pop("packet_dir", None)
    return summary


def _scan_task_packets(repo: Path) -> list[dict[str, Any]]:
    root = tasks_root(repo)
    if not root.exists():
        return []
    packets: list[dict[str, Any]] = []
    for packet_json in root.glob("*/task-packet.json"):
        try:
            packets.append(_index_packet_summary(load_task_packet(packet_json)))
        except (OSError, json.JSONDecodeError):
            continue
    packets.sort(
        key=lambda packet: (
            str(packet.get("updated_at") or packet.get("created_at") or ""),
            str(packet.get("packet_id") or ""),
        ),
        reverse=True,
    )
    return packets


def build_task_index(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    packets = _scan_task_packets(repo)
    return {
        "schema": TASK_INDEX_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packet_count": len(packets),
        "packets": packets,
    }


def write_task_index(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    root = tasks_root(repo)
    root.mkdir(parents=True, exist_ok=True)
    index = build_task_index(repo)
    write_text(task_index_path(repo), json.dumps(index, indent=2))
    return index


def read_task_index(repo_path: Path) -> dict[str, Any] | None:
    repo = ensure_repo(repo_path)
    index_path = task_index_path(repo)
    if not index_path.exists():
        return None
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if index.get("schema") != TASK_INDEX_SCHEMA:
        return None
    packets = index.get("packets")
    if not isinstance(packets, list):
        return None
    return index


def list_task_packets(repo_path: Path, limit: int = 8) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = tasks_root(repo)
    if not root.exists():
        return []
    index = read_task_index(repo)
    if index is None:
        index = write_task_index(repo)
    packets = [dict(item) for item in list(index.get("packets", []))[:limit] if isinstance(item, dict)]
    for packet in packets:
        packet_id = str(packet.get("packet_id") or "")
        if not PACKET_ID_PATTERN.fullmatch(packet_id):
            continue
        runner_run = read_latest_runner_state(tasks_root(repo) / packet_id)
        if runner_run is not None:
            packet["runner_run"] = runner_run
    return packets
