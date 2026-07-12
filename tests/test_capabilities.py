from __future__ import annotations

import json
from pathlib import Path
import subprocess

from hamiltonian.capabilities import (
    CAPABILITY_FIT_SCHEMA,
    CAPABILITY_MANIFEST_SCHEMA,
    TASK_PROFILE_SCHEMA,
    capability_manifest_for_lane,
    evaluate_capability_fit,
    infer_task_requirements,
)
from hamiltonian.packets import build_route_recommendations, create_task_packet
from hamiltonian.runtime import build_runner_adapters


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)


def test_capability_manifests_are_versioned_deterministic_and_local_only() -> None:
    first = capability_manifest_for_lane("codex")
    second = capability_manifest_for_lane("codex")
    hermes = capability_manifest_for_lane("hermes")

    assert first["schema"] == CAPABILITY_MANIFEST_SCHEMA
    assert first["manifest_version"] == 1
    assert first["manifest_digest"] == second["manifest_digest"]
    assert len(first["manifest_digest"]) == 64
    assert first["local_only"] is True
    assert first["remote_execution"] is False
    assert hermes["remote_execution"] is False
    assert "implementation" in first["strengths"]
    assert "handoff" in hermes["strengths"]
    assert "remote-execution" not in first["task_families"]
    assert "remote-execution" not in hermes["task_families"]


def test_task_requirements_and_lane_fit_are_explained_without_task_text() -> None:
    profile = infer_task_requirements("Implement the fix, run tests, and write a handoff report.")
    codex = evaluate_capability_fit("Implement the fix and run tests.", "codex")
    hermes = evaluate_capability_fit("Prepare a structured handoff report.", "hermes")

    assert profile["schema"] == TASK_PROFILE_SCHEMA
    assert profile["task_included"] is False
    assert set(profile["requirements"]) >= {"implementation", "verification", "handoff"}
    assert codex["schema"] == CAPABILITY_FIT_SCHEMA
    assert codex["status"] == "strong"
    assert hermes["status"] == "strong"
    assert codex["missing_capabilities"] == []
    assert "Implement the fix" not in json.dumps(codex)


def test_remote_execution_requirement_is_incompatible_for_every_lane() -> None:
    task = "Use SSH remote execution and start a delivery service on another machine."
    codex = evaluate_capability_fit(task, "codex")
    hermes = evaluate_capability_fit(task, "hermes")
    routes = build_route_recommendations(task=task, selected_agent_id="codex")

    assert codex["status"] == "incompatible"
    assert hermes["status"] == "incompatible"
    assert codex["missing_capabilities"] == ["remote-execution"]
    assert all(route["capability_status"] == "incompatible" for route in routes)
    assert all(route["status"] == "unsupported" for route in routes)
    assert all(route["remote_execution"] is False for route in routes)


def test_runtime_adapter_status_exposes_manifest_separately_from_availability(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))

    adapters = {item.id: item for item in build_runner_adapters(tmp_path, git_available=True)}
    assert adapters["codex"].available is True
    assert adapters["codex"].capability_manifest["schema"] == CAPABILITY_MANIFEST_SCHEMA
    assert adapters["hermes"].available is True
    assert adapters["hermes"].capability_manifest["evidence_policy"] == "packet-optional"


def test_packet_and_runner_plan_persist_capability_refusal(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    packet = create_task_packet(
        tmp_path,
        "Start a remote execution gateway over SSH.",
        "codex",
        stage="execute",
    )

    assert packet.route.status == "capability-blocked"
    assert packet.route.capability_status == "incompatible"
    assert packet.route.missing_capabilities == ["remote-execution"]
    assert packet.runner_plan.status == "capability-blocked"
    assert packet.runner_plan.launch_supported is False
    assert packet.runner_plan.capability_status == "incompatible"
    assert packet.runner_plan.remote_execution is False
    assert packet.runner_plan.capability_manifest_digest == packet.route.capability_manifest_digest
    markdown = Path(packet.files["markdown"]).read_text(encoding="utf-8")
    assert "Capability fit: `incompatible`" in markdown
    assert "Missing capabilities: `remote-execution`" in markdown
    assert packet.runner_plan.capability_manifest_digest in markdown
