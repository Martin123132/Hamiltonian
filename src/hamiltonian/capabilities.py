from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any


CAPABILITY_MANIFEST_SCHEMA = "hamiltonian.adapter-capabilities.v1"
TASK_PROFILE_SCHEMA = "hamiltonian.task-capability-profile.v1"
CAPABILITY_FIT_SCHEMA = "hamiltonian.capability-fit.v1"


@dataclass(frozen=True)
class AdapterCapabilityManifest:
    schema: str
    manifest_version: int
    adapter_id: str
    lane_id: str
    display_name: str
    execution_kind: str
    task_families: tuple[str, ...]
    strengths: tuple[str, ...]
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]
    safety_controls: tuple[str, ...]
    evidence_policy: str
    local_only: bool
    remote_execution: bool


MANIFESTS = {
    "codex": AdapterCapabilityManifest(
        schema=CAPABILITY_MANIFEST_SCHEMA,
        manifest_version=1,
        adapter_id="codex-local",
        lane_id="codex",
        display_name="Codex",
        execution_kind="supervised-local-cli",
        task_families=("implementation", "verification", "analysis", "handoff", "local-command"),
        strengths=("implementation", "verification", "local-command"),
        capabilities=(
            "git-worktree",
            "workspace-read",
            "workspace-write",
            "local-command",
            "test-execution",
            "structured-final-response",
            "cancellation",
            "result-receipt",
        ),
        limitations=(
            "Requires a Git worktree and an existing callable Codex CLI session.",
            "Does not provide remote command execution or unattended background work.",
            "Evidence capture is a separate packet choice, not an adapter capability.",
        ),
        safety_controls=("workspace-write sandbox", "explicit launch", "bounded timeout", "supervised cancellation"),
        evidence_policy="packet-optional",
        local_only=True,
        remote_execution=False,
    ),
    "hermes": AdapterCapabilityManifest(
        schema=CAPABILITY_MANIFEST_SCHEMA,
        manifest_version=1,
        adapter_id="hermes-local",
        lane_id="hermes",
        display_name="Hermes Agent",
        execution_kind="supervised-local-one-shot",
        task_families=("implementation", "verification", "analysis", "handoff"),
        strengths=("analysis", "handoff"),
        capabilities=(
            "git-worktree",
            "workspace-read",
            "workspace-write",
            "bounded-tool-use",
            "structured-final-response",
            "cancellation",
            "result-receipt",
        ),
        limitations=(
            "Requires a Git worktree, a callable Hermes CLI, and provider configuration created outside Hamiltonian.",
            "One-shot mode does not start a gateway, delivery service, SSH session, or Docker backend.",
            "Safe mode and checkpoints are application controls, not an operating-system sandbox.",
        ),
        safety_controls=("safe mode", "checkpoints", "24-turn cap", "explicit launch", "bounded timeout"),
        evidence_policy="packet-optional",
        local_only=True,
        remote_execution=False,
    ),
    "local": AdapterCapabilityManifest(
        schema=CAPABILITY_MANIFEST_SCHEMA,
        manifest_version=1,
        adapter_id="local-local-contract",
        lane_id="local",
        display_name="Local runner",
        execution_kind="dry-run-contract",
        task_families=("local-command", "verification"),
        strengths=("local-command",),
        capabilities=("sanitized-plan", "result-receipt"),
        limitations=("Current adapter stops at a dry-run plan and launches no process.",),
        safety_controls=("no launch", "local metadata only"),
        evidence_policy="packet-optional",
        local_only=True,
        remote_execution=False,
    ),
    "openclaw": AdapterCapabilityManifest(
        schema=CAPABILITY_MANIFEST_SCHEMA,
        manifest_version=1,
        adapter_id="openclaw-local",
        lane_id="openclaw",
        display_name="OpenClaw adapter",
        execution_kind="tool-less-embedded-one-shot",
        task_families=("analysis", "handoff"),
        strengths=("analysis", "handoff"),
        capabilities=("tool-less-reasoning", "structured-final-response", "cancellation", "result-receipt"),
        limitations=(
            "The first callable boundary receives task text only and cannot read, write, or execute inside the repository.",
            "Requires a compatible OpenClaw CLI and an operator-configured provider/model id.",
            "Gateway, channels, delivery, SSH, Docker, plugins, MCP tools, and remote execution are unavailable.",
        ),
        safety_controls=("forced --local transport", "all tools denied", "no delivery flags", "transport receipt verification"),
        evidence_policy="packet-optional",
        local_only=True,
        remote_execution=False,
    ),
}


TASK_MARKERS = {
    "implementation": (
        "implement",
        "build",
        "fix",
        "code",
        "refactor",
        "feature",
        "change the app",
        "update the repo",
    ),
    "verification": (
        "test",
        "verify",
        "validate",
        "audit",
        "review",
        "health check",
        "does this work",
    ),
    "analysis": ("research", "analyse", "analyze", "compare", "strategy", "investigate", "assess"),
    "handoff": ("handoff", "hand off", "goal", "report", "summary", "receipt", "decision"),
    "local-command": ("command", "shell", "terminal", "script", "compile", "smoke check"),
    "remote-execution": (
        "remote execution",
        "remote command",
        "ssh",
        "gateway",
        "delivery service",
        "docker backend",
        "run on another machine",
    ),
}


def _canonical_manifest(manifest: AdapterCapabilityManifest) -> str:
    return json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":"))


def capability_manifest_for_lane(lane_id: str) -> dict[str, Any]:
    normalized = lane_id.lower().strip()
    manifest = MANIFESTS.get(normalized)
    if manifest is None:
        raise ValueError(f"unknown capability manifest lane: {lane_id}")
    payload = asdict(manifest)
    payload["manifest_digest"] = sha256(_canonical_manifest(manifest).encode("utf-8")).hexdigest()
    return payload


def infer_task_requirements(task: str) -> dict[str, Any]:
    lowered = task.lower()
    requirements = [
        family
        for family, markers in TASK_MARKERS.items()
        if any(marker in lowered for marker in markers)
    ]
    if not requirements:
        requirements = ["general"]
    return {
        "schema": TASK_PROFILE_SCHEMA,
        "requirements": requirements,
        "remote_execution_requested": "remote-execution" in requirements,
        "task_included": False,
    }


def evaluate_capability_fit(task: str, lane_id: str) -> dict[str, Any]:
    manifest = capability_manifest_for_lane(lane_id)
    profile = infer_task_requirements(task)
    requirements = tuple(profile["requirements"])
    supported = set(manifest["task_families"])
    strengths = set(manifest["strengths"])
    material_requirements = {item for item in requirements if item != "general"}
    missing = sorted(material_requirements - supported)
    if missing:
        status = "incompatible"
        score_adjustment = -40
        summary = f"{manifest['display_name']} cannot satisfy: {', '.join(missing)}."
    elif material_requirements and material_requirements.issubset(strengths):
        status = "strong"
        score_adjustment = 8
        summary = f"{manifest['display_name']} is a strong fit for {', '.join(sorted(material_requirements))}."
    else:
        status = "compatible"
        score_adjustment = 1
        family_text = ", ".join(sorted(material_requirements)) if material_requirements else "general bounded work"
        summary = f"{manifest['display_name']} supports {family_text}."
    return {
        "schema": CAPABILITY_FIT_SCHEMA,
        "lane_id": manifest["lane_id"],
        "adapter_id": manifest["adapter_id"],
        "manifest_schema": manifest["schema"],
        "manifest_version": manifest["manifest_version"],
        "manifest_digest": manifest["manifest_digest"],
        "status": status,
        "requirements": list(requirements),
        "missing_capabilities": missing,
        "score_adjustment": score_adjustment,
        "summary": summary,
        "remote_execution": False,
    }
