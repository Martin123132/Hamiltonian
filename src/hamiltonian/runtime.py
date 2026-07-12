from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capabilities import capability_manifest_for_lane
from .core import ensure_repo, is_git_repo, run_capture
from .integrations import IntegrationStatus, detect_integrations
from .packets import build_lane_contracts, build_route_recommendations, list_task_packets
from .runners import probe_codex_command, probe_hermes_command, probe_openclaw_command


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    role: str
    status: str
    notes: str


@dataclass(frozen=True)
class RuntimeGate:
    id: str
    name: str
    purpose: str
    status: str
    integration: str | None = None


@dataclass(frozen=True)
class RunnerAdapterStatus:
    id: str
    name: str
    available: bool
    detail: str
    mode: str
    safety: str
    setup_guidance: str
    local_execution: bool
    remote_execution: bool
    capability_manifest: dict[str, Any]


@dataclass(frozen=True)
class RuntimeState:
    generated_at: str
    repo: str
    repo_name: str
    git_available: bool
    git_status: str
    agents: list[AgentProfile]
    runner_adapters: list[RunnerAdapterStatus]
    gates: list[RuntimeGate]
    integrations: list[IntegrationStatus]
    lane_contracts: list[dict[str, Any]]
    route_recommendations: list[dict[str, Any]]
    lifecycle: list[dict[str, str]]
    recent_packets: list[dict[str, Any]]
    next_actions: list[str]


def _integration_map(integrations: list[IntegrationStatus]) -> dict[str, IntegrationStatus]:
    return {item.name: item for item in integrations}


def _status_for(
    integration_by_name: dict[str, IntegrationStatus],
    integration_name: str,
    ready_label: str = "wired",
) -> str:
    item = integration_by_name.get(integration_name)
    if item and item.available:
        return ready_label
    return "available as module"


def build_agents(
    git_available: bool,
    integrations: list[IntegrationStatus] | None = None,
) -> list[AgentProfile]:
    repo_note = "workspace is git-aware" if git_available else "workspace is local-only"
    by_name = _integration_map(integrations or [])
    hermes_ready = bool(by_name.get("Hermes Agent") and by_name["Hermes Agent"].available)
    return [
        AgentProfile(
            id="codex",
            name="Codex",
            role="code operator",
            status="ready",
            notes=f"Primary local implementation lane; {repo_note}.",
        ),
        AgentProfile(
            id="openclaw",
            name="OpenClaw",
            role="tool-less embedded reasoning lane",
            status="runtime-probed",
            notes="Forced local one-shot transport; no tools, gateway, delivery, or remote execution.",
        ),
        AgentProfile(
            id="hermes",
            name="Hermes Agent",
            role="local one-shot agent lane",
            status="ready" if hermes_ready and git_available else "adapter unavailable",
            notes=(
                "Callable through safe mode and checkpoints behind Hamiltonian gates."
                if hermes_ready and git_available
                else "Install or expose Hermes Agent locally to enable this lane."
            ),
        ),
        AgentProfile(
            id="local",
            name="Local runner",
            role="shell and scripts",
            status="ready",
            notes="Runs commands directly when an agent is unnecessary.",
        ),
    ]


def build_runner_adapters(repo: Path, git_available: bool) -> list[RunnerAdapterStatus]:
    codex = probe_codex_command(repo)
    hermes = probe_hermes_command(repo)
    openclaw = probe_openclaw_command(repo)
    return [
        RunnerAdapterStatus(
            id="codex",
            name="Codex",
            available=bool(git_available and codex.available),
            detail=codex.detail if git_available else "A Git worktree is required.",
            mode="local-codex",
            safety="Workspace-write sandbox with a supervised timeout.",
            setup_guidance=(
                "Ready to use the existing Codex CLI session."
                if git_available and codex.available
                else "Set up the Codex app or CLI outside Hamiltonian, then reopen this workspace."
            ),
            local_execution=True,
            remote_execution=False,
            capability_manifest=capability_manifest_for_lane("codex"),
        ),
        RunnerAdapterStatus(
            id="hermes",
            name="Hermes Agent",
            available=bool(git_available and hermes.available),
            detail=hermes.detail if git_available else "A Git worktree is required.",
            mode="local-hermes-one-shot",
            safety="Hermes safe mode, checkpoints, bounded turns, and a supervised timeout.",
            setup_guidance=(
                "Ready to use the existing Hermes provider configuration."
                if git_available and hermes.available
                else "Install and configure Hermes outside Hamiltonian, then reopen this workspace."
            ),
            local_execution=True,
            remote_execution=False,
            capability_manifest=capability_manifest_for_lane("hermes"),
        ),
        RunnerAdapterStatus(
            id="openclaw",
            name="OpenClaw",
            available=bool(git_available and openclaw.available),
            detail=openclaw.detail if git_available else "A Git worktree is required.",
            mode="local-openclaw-embedded",
            safety="Forced embedded transport, all tools denied, no delivery flags, and verified JSON transport metadata.",
            setup_guidance=(
                "Ready for tool-less embedded one-shot reasoning."
                if git_available and openclaw.available
                else "Install OpenClaw and set HAMILTONIAN_OPENCLAW_MODEL outside Hamiltonian, then reopen this workspace."
            ),
            local_execution=True,
            remote_execution=False,
            capability_manifest=capability_manifest_for_lane("openclaw"),
        ),
    ]


def build_gates(integrations: list[IntegrationStatus]) -> list[RuntimeGate]:
    by_name = _integration_map(integrations)
    return [
        RuntimeGate(
            id="memory",
            name="Project memory",
            purpose="Load compact repo context before an agent acts.",
            status=_status_for(by_name, "RepoMori"),
            integration="RepoMori",
        ),
        RuntimeGate(
            id="intent",
            name="Intent and command gate",
            purpose="Check plans and shell commands before execution.",
            status=_status_for(by_name, "Memento Mori Jester"),
            integration="Memento Mori Jester",
        ),
        RuntimeGate(
            id="cost",
            name="Cost and context posture",
            purpose="Expose token burn and shrink context before it gets silly.",
            status=(
                "wired"
                if by_name.get("Tokometer") and by_name["Tokometer"].available
                else "available as module"
            ),
            integration="Tokometer / TokenSquash",
        ),
        RuntimeGate(
            id="evidence",
            name="Evidence capture",
            purpose="Attach a recorder packet when the run needs proof.",
            status=_status_for(by_name, "AgentLedger", ready_label="optional and wired"),
            integration="AgentLedger",
        ),
        RuntimeGate(
            id="release",
            name="Release confidence",
            purpose="Compare behavior and catch regressions before handoff.",
            status=_status_for(by_name, "Sentinel Manifold"),
            integration="Sentinel Manifold",
        ),
    ]


def build_lifecycle() -> list[dict[str, str]]:
    return [
        {"step": "Draft", "owner": "operator", "state": "compose task"},
        {"step": "Prime", "owner": "memory", "state": "load repo context"},
        {"step": "Gate", "owner": "policy", "state": "approve plan and tools"},
        {"step": "Execute", "owner": "agent", "state": "run bounded work"},
        {"step": "Verify", "owner": "tests", "state": "prove the result"},
        {"step": "Record", "owner": "evidence", "state": "attach proof if needed"},
    ]


def build_next_actions(integrations: list[IntegrationStatus]) -> list[str]:
    by_name = _integration_map(integrations)
    actions = [
        "Build the task lifecycle: draft, assign, gate, execute, verify, hand off.",
        "Use OpenClaw only through its tool-less embedded boundary; gateway and delivery remain unavailable.",
    ]
    if not by_name.get("RepoMori") or not by_name["RepoMori"].available:
        actions.append("Wire RepoMori as the first memory pack so tasks start with repo context.")
    if not by_name.get("Memento Mori Jester") or not by_name["Memento Mori Jester"].available:
        actions.append("Wire Jester as the pre-run plan and command gate.")
    if not by_name.get("AgentLedger") or not by_name["AgentLedger"].available:
        actions.append("Keep AgentLedger optional: enable evidence packets only when the user asks.")
    return actions


def build_runtime_state(repo_path: Path) -> RuntimeState:
    repo = ensure_repo(repo_path)
    integrations = detect_integrations(repo)
    git_available = is_git_repo(repo)
    return RuntimeState(
        generated_at=datetime.now(timezone.utc).isoformat(),
        repo=str(repo),
        repo_name=repo.name,
        git_available=git_available,
        git_status=run_capture(("git", "status", "--short"), repo) if git_available else "",
        agents=build_agents(git_available, integrations),
        runner_adapters=build_runner_adapters(repo, git_available),
        gates=build_gates(integrations),
        integrations=integrations,
        lane_contracts=build_lane_contracts(git_available, integrations),
        route_recommendations=build_route_recommendations(
            task="",
            selected_agent_id="codex",
            git_available=git_available,
            integrations=integrations,
        ),
        lifecycle=build_lifecycle(),
        recent_packets=list_task_packets(repo),
        next_actions=build_next_actions(integrations),
    )


def runtime_state_dict(repo_path: Path) -> dict[str, Any]:
    return asdict(build_runtime_state(repo_path))
