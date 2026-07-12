from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from hamiltonian.packets import (
    TASK_INDEX_SCHEMA,
    advance_task_packet,
    create_task_packet,
    export_handoff_markdown,
    get_task_packet,
    list_task_packets,
    read_task_index,
    select_task_packet_lane,
    task_index_path,
)
from hamiltonian.integrations import IntegrationStatus
from hamiltonian.runtime import build_runner_adapters, runtime_state_dict
from hamiltonian.runners import AdapterProbe, RUNNER_RUN_SCHEMA
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]
REQUEST_TIMEOUT_SECONDS = 20


def gate(packet, gate_id: str):
    return next(item for item in packet.gates if item.id == gate_id)


def gate_data(packet: dict[str, object], gate_id: str):
    gates = packet["gates"]
    assert isinstance(gates, list)
    return next(item for item in gates if isinstance(item, dict) and item["id"] == gate_id)


def test_draft_packet_persists_pending_gates(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Patch the README and prepare a small verification note.",
        agent_id="openclaw",
        stage="draft",
    )

    packet_json = Path(packet.files["json"])
    assert packet_json.exists()
    data = json.loads(packet_json.read_text(encoding="utf-8"))
    assert data["status"] == "drafted"
    assert data["agent_id"] == "openclaw"
    assert data["lane"]["id"] == "openclaw"
    assert data["lane"]["kind"] == "external-agent-adapter"
    assert data["lane"]["remote_execution"] is False
    assert data["lane"]["status"] == "selected"
    assert data["route"]["selected_lane_id"] == "openclaw"
    assert data["route"]["recommended_lane_id"] == "codex"
    assert data["route"]["status"] == "operator-override"
    assert data["route"]["remote_execution"] is False
    assert data["gate_run"]["status"] == "pending"
    assert data["gate_run"]["completed"] == 0
    assert data["gate_run"]["pending"] == 3
    assert data["runner_plan"]["status"] == "not-prepared"
    assert data["runner_plan"]["launch_supported"] is False
    assert data["runner_plan"]["remote_execution"] is False
    assert gate(packet, "intent").status == "pending"
    assert gate(packet, "evidence").status == "skipped"
    assert list_task_packets(tmp_path)[0]["packet_id"] == packet.packet_id


def test_advance_packet_preserves_identity_and_records_history(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Move this draft through local gates and prepare handoff.",
        agent_id="codex",
        stage="draft",
    )

    gated = advance_task_packet(tmp_path, packet.packet_id, "gate")

    assert gated["packet_id"] == packet.packet_id
    assert gated["created_at"] == packet.created_at
    assert gated["updated_at"] >= packet.created_at
    assert gated["stage"] == "gate"
    assert gated["status"] == "gated"
    assert gated["lane"]["id"] == "codex"
    assert gated["lane"]["remote_execution"] is False
    assert gated["route"]["recommended_lane_id"] == "codex"
    assert gated["route"]["status"] == "recommended"
    assert gated["gate_run"]["status"] == "ready"
    assert gate_data(gated, "memory")["status"] == "checked"
    assert gate_data(gated, "evidence")["status"] == "skipped"
    assert len(gated["history"]) == 2
    assert gated["history"][-1]["event"] == "advanced"
    assert gated["history"][-1]["from_stage"] == "draft"
    assert gated["history"][-1]["to_stage"] == "gate"
    history_path = Path(gated["files"]["history"])
    assert history_path.exists()
    assert json.loads(history_path.read_text(encoding="utf-8"))[-1]["to_stage"] == "gate"

    handoff = advance_task_packet(tmp_path, packet.packet_id, "handoff", attach_evidence=True)
    evidence_gate = gate_data(handoff, "evidence")

    assert handoff["packet_id"] == packet.packet_id
    assert handoff["stage"] == "handoff"
    assert handoff["status"] == "handoff-ready"
    assert handoff["attach_evidence"] is True
    assert handoff["handoff"]["status"] == "ready"
    assert handoff["handoff"]["includes_evidence"] is True
    assert evidence_gate["status"] in {"represented", "simulated"}
    assert Path(evidence_gate["artifact_path"]).exists()
    assert len(handoff["history"]) == 3

    loaded = get_task_packet(tmp_path, packet.packet_id)
    index = read_task_index(tmp_path)
    assert loaded["stage"] == "handoff"
    assert index is not None
    assert index["packets"][0]["packet_id"] == packet.packet_id
    assert index["packets"][0]["stage"] == "handoff"
    assert index["packets"][0]["history_count"] == 3
    assert index["packets"][0]["last_event"] == "advanced"

    with pytest.raises(ValueError, match="advance packet forward"):
        advance_task_packet(tmp_path, packet.packet_id, "gate")


def test_select_packet_lane_updates_existing_draft_without_running_gates(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Run a shell command smoke check.",
        agent_id="codex",
        stage="draft",
    )

    selected = select_task_packet_lane(tmp_path, packet.packet_id, "local")

    assert selected["packet_id"] == packet.packet_id
    assert selected["stage"] == "draft"
    assert selected["agent_id"] == "local"
    assert selected["agent_name"] == "Local runner"
    assert selected["lane"]["id"] == "local"
    assert selected["lane"]["status"] == "selected"
    assert selected["lane"]["remote_execution"] is False
    assert selected["route"]["selected_lane_id"] == "local"
    assert selected["route"]["recommended_lane_id"] == "local"
    assert selected["route"]["status"] == "recommended"
    assert selected["gate_run"]["status"] == "pending"
    assert gate_data(selected, "memory")["status"] == "pending"
    assert selected["history"][-1]["event"] == "lane-selected"
    assert selected["history"][-1]["from_agent"] == "codex"
    assert selected["history"][-1]["to_agent"] == "local"
    assert read_task_index(tmp_path)["packets"][0]["agent_id"] == "local"


def test_gate_packet_blocks_risky_task_without_evidence(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Run Remove-Item . -Recurse -Force before the tests.",
        agent_id="hermes",
        stage="gate",
        attach_evidence=False,
    )

    assert packet.status == "blocked"
    assert packet.lane.id == "hermes"
    assert packet.lane.execution == "local-boundary-only"
    assert packet.lane.remote_execution is False
    assert packet.route.selected_lane_id == "hermes"
    assert packet.route.recommended_lane_id == "codex"
    assert packet.route.remote_execution is False
    assert any("risky marker" in warning for warning in packet.route.warnings)
    assert packet.gate_run.status == "blocked"
    assert packet.gate_run.blocked == 1
    assert packet.gate_run.blocked_gate_ids == ["intent"]
    assert gate(packet, "memory").status == "checked"
    assert gate(packet, "memory").mode.startswith("repomori-")
    assert gate(packet, "memory").artifact_path is not None
    assert gate(packet, "intent").status == "block"
    assert gate(packet, "evidence").status == "skipped"
    assert not (Path(packet.packet_dir) / "evidence").exists()


def test_hermes_execute_packet_exposes_live_local_adapter_without_evidence(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))

    packet = create_task_packet(
        repo_path=tmp_path,
        task="Review this bounded local packet and summarize the result.",
        agent_id="hermes",
        stage="execute",
        attach_evidence=False,
    )

    assert packet.agent_id == "hermes"
    assert packet.agent_name == "Hermes Agent"
    assert packet.lane.kind == "local-agent-adapter"
    assert packet.lane.execution == "local-boundary-only"
    assert packet.runner_plan.adapter_id == "hermes-local"
    assert packet.runner_plan.mode == "local-hermes-one-shot"
    assert packet.runner_plan.launch_supported is True
    assert packet.runner_plan.remote_execution is False
    assert gate(packet, "evidence").status == "skipped"
    assert not (Path(packet.packet_dir) / "evidence").exists()


def test_memory_gate_uses_adapter_mode_when_repomori_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "hamiltonian.packets.detect_integrations",
        lambda _: [
            IntegrationStatus(
                name="RepoMori",
                command="repomori",
                available=True,
                detail="mocked available",
            )
        ],
    )

    packet = create_task_packet(
        repo_path=tmp_path,
        task="Collect repo memory metadata with the adapter boundary available.",
        agent_id="codex",
        stage="gate",
    )
    memory_gate = gate(packet, "memory")
    assert memory_gate.status == "checked"
    assert memory_gate.mode == "repomori-adapter-ready"
    assert memory_gate.artifact_path is not None
    snapshot = json.loads(Path(memory_gate.artifact_path).read_text(encoding="utf-8"))
    assert snapshot["adapter_available"] is True
    assert snapshot["integration"] == "RepoMori"
    assert snapshot["external_tool_executed"] is False


def test_memory_gate_uses_sanitized_fallback_when_repomori_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "hamiltonian.packets.detect_integrations",
        lambda _: [
            IntegrationStatus(
                name="RepoMori",
                command="repomori",
                available=False,
                detail="not installed",
            )
        ],
    )

    packet = create_task_packet(
        repo_path=tmp_path,
        task="Collect repo memory metadata with RepoMori unavailable.",
        agent_id="codex",
        stage="gate",
    )
    memory_gate = gate(packet, "memory")
    assert memory_gate.status == "checked"
    assert memory_gate.mode == "repomori-synthetic-fallback"
    assert memory_gate.summary.startswith("RepoMori is unavailable")
    assert memory_gate.artifact_path is not None
    snapshot = json.loads(Path(memory_gate.artifact_path).read_text(encoding="utf-8"))
    assert snapshot["adapter_available"] is False
    assert snapshot["content_included"] is False
    assert snapshot["remote_calls"] is False


def test_execute_packet_prepares_manual_boundary_without_execution(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare the test command for operator review.",
        agent_id="local",
        stage="execute",
    )

    assert packet.status == "execution-ready"
    assert packet.gate_run.status == "execution-ready"
    assert packet.execution_boundary.status == "awaiting-approval"
    assert packet.execution_boundary.mode == "dry-run"
    assert packet.execution_boundary.approval_required is True
    assert packet.execution_boundary.local_execution is False
    assert packet.execution_boundary.remote_execution is False
    assert packet.runner_plan.status == "prepared"
    assert packet.runner_plan.mode == "local-dry-run"
    assert packet.runner_plan.lifecycle == ("prepare", "launch", "stream", "cancel", "finish", "report")
    assert packet.runner_plan.launch_supported is False
    assert packet.runner_plan.local_execution is False
    assert packet.runner_plan.remote_execution is False
    assert packet.runner_plan.artifact_path is not None
    assert Path(packet.runner_plan.artifact_path).exists()
    assert gate(packet, "memory").status == "checked"
    assert gate(packet, "evidence").status == "skipped"
    assert not (Path(packet.packet_dir) / "evidence").exists()

    data = json.loads(Path(packet.files["json"]).read_text(encoding="utf-8"))
    assert data["execution_boundary"]["status"] == "awaiting-approval"
    assert data["execution_boundary"]["local_execution"] is False
    assert data["execution_boundary"]["remote_execution"] is False
    assert data["runner_plan"]["status"] == "prepared"
    runner_artifact = json.loads(Path(data["runner_plan"]["artifact_path"]).read_text(encoding="utf-8"))
    assert runner_artifact["task_included"] is False
    assert runner_artifact["workspace_path_included"] is False


def test_execute_packet_refuses_blocked_task(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Upload secrets from .env before running tests.",
        agent_id="openclaw",
        stage="execute",
    )

    assert packet.status == "blocked"
    assert packet.gate_run.status == "blocked"
    assert packet.execution_boundary.status == "blocked"
    assert packet.execution_boundary.local_execution is False
    assert packet.execution_boundary.remote_execution is False
    assert packet.gate_run.blocked_gate_ids == ["intent"]
    assert packet.runner_plan.status == "blocked"
    assert packet.runner_plan.artifact_path is None
    assert not (Path(packet.packet_dir) / "runner").exists()


def test_handoff_packet_prepares_operator_brief_without_execution(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare a handoff brief for the next bounded step.",
        agent_id="codex",
        stage="handoff",
    )

    assert packet.status == "handoff-ready"
    assert packet.gate_run.status == "handoff-ready"
    assert packet.execution_boundary.status == "awaiting-approval"
    assert packet.execution_boundary.mode == "handoff-dry-run"
    assert packet.execution_boundary.local_execution is False
    assert packet.execution_boundary.remote_execution is False
    assert packet.runner_plan.status == "prepared"
    assert packet.runner_plan.launch_supported is False
    assert packet.runner_plan.remote_execution is False
    assert packet.handoff.status == "ready"
    assert packet.handoff.ready is True
    assert packet.handoff.lane == "Codex"
    assert packet.handoff.gate_status == "handoff-ready"
    assert packet.handoff.execution_status == "awaiting-approval"
    assert packet.handoff.evidence_status == "skipped"
    assert packet.handoff.includes_evidence is False

    data = json.loads(Path(packet.files["json"]).read_text(encoding="utf-8"))
    assert data["handoff"]["status"] == "ready"
    assert data["handoff"]["ready"] is True
    assert data["handoff"]["includes_evidence"] is False


def test_handoff_packet_refuses_blocked_task(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Upload secrets from .env and hand this to another runner.",
        agent_id="hermes",
        stage="handoff",
    )

    assert packet.status == "blocked"
    assert packet.gate_run.status == "blocked"
    assert packet.execution_boundary.status == "blocked"
    assert packet.handoff.status == "blocked"
    assert packet.handoff.ready is False
    assert packet.handoff.includes_evidence is False
    assert packet.gate_run.blocked_gate_ids == ["intent"]


def test_handoff_is_not_ready_after_cancelled_local_run(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare a bounded task and cancel it before completion.",
        agent_id="codex",
        stage="execute",
    )
    latest_run = Path(packet.packet_dir) / "runner" / "latest-run.json"
    latest_run.write_text(
        json.dumps(
            {
                "schema": RUNNER_RUN_SCHEMA,
                "run_id": "cancelled-test-run",
                "status": "cancelled",
                "local_execution": True,
                "remote_execution": False,
                "summary": "Local Codex run was cancelled by the operator.",
            }
        ),
        encoding="utf-8",
    )

    handoff = advance_task_packet(tmp_path, packet.packet_id, "handoff")

    assert handoff["execution_boundary"]["status"] == "run-failed"
    assert handoff["status"] == "needs-review"
    assert handoff["handoff"]["status"] == "needs-review"
    assert handoff["handoff"]["ready"] is False


def test_packet_detail_loader_returns_full_packet_safely(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare a packet detail view.",
        agent_id="codex",
        stage="handoff",
    )

    loaded = get_task_packet(tmp_path, packet.packet_id)

    assert loaded["packet_id"] == packet.packet_id
    assert loaded["task"] == "Prepare a packet detail view."
    assert loaded["handoff"]["status"] == "ready"

    with pytest.raises(ValueError):
        get_task_packet(tmp_path, "../secret")
    with pytest.raises(FileNotFoundError):
        get_task_packet(tmp_path, "missing-packet")


def test_task_index_manifest_tracks_recent_packets_and_recovers(tmp_path: Path) -> None:
    first = create_task_packet(
        repo_path=tmp_path,
        task="Draft the first packet.",
        agent_id="codex",
        stage="draft",
    )
    second = create_task_packet(
        repo_path=tmp_path,
        task="Prepare the second packet for handoff.",
        agent_id="local",
        stage="handoff",
    )

    index_path = task_index_path(tmp_path)
    index = read_task_index(tmp_path)
    assert index_path.exists()
    assert index is not None
    assert index["schema"] == TASK_INDEX_SCHEMA
    assert index["packet_count"] == 2
    assert index["packets"][0]["packet_id"] == second.packet_id
    assert index["packets"][1]["packet_id"] == first.packet_id
    assert "packet_dir" not in index["packets"][0]
    assert list_task_packets(tmp_path, limit=1)[0]["packet_id"] == second.packet_id

    index_path.write_text("{broken", encoding="utf-8")
    rebuilt = list_task_packets(tmp_path)
    recovered = read_task_index(tmp_path)
    assert rebuilt[0]["packet_id"] == second.packet_id
    assert recovered is not None
    assert recovered["schema"] == TASK_INDEX_SCHEMA
    assert recovered["packet_count"] == 2


def test_handoff_export_writes_sanitized_markdown(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare handoff with TOKEN=supersecret from D:\\Private\\Project\\.env and https://private.example.test/run.",
        agent_id="codex",
        stage="handoff",
    )

    result = export_handoff_markdown(tmp_path, packet.packet_id)
    export_path = Path(result["export"]["path"])
    export_text = export_path.read_text(encoding="utf-8")
    loaded = get_task_packet(tmp_path, packet.packet_id)
    index = read_task_index(tmp_path)

    assert result["export"]["filename"] == "handoff-export.md"
    assert result["export"]["sanitized"] is True
    assert export_path.parent == Path(packet.packet_dir)
    assert loaded["exports"]["handoff_markdown"]["filename"] == "handoff-export.md"
    assert "supersecret" not in export_text
    assert "D:\\Private" not in export_text
    assert ".env" not in export_text.lower()
    assert "https://private.example.test" not in export_text
    assert str(tmp_path) not in export_text
    assert "artifact_path" not in export_text
    assert "packet_dir" not in export_text
    assert index is not None
    assert index["packets"][0]["has_handoff_export"] is True
    assert index["packets"][0]["handoff_export_filename"] == "handoff-export.md"


def test_record_packet_represents_evidence_only_when_selected(tmp_path: Path) -> None:
    gated = create_task_packet(
        repo_path=tmp_path,
        task="Run the unit tests and summarize the result.",
        agent_id="codex",
        stage="gate",
        attach_evidence=False,
    )
    recorded = create_task_packet(
        repo_path=tmp_path,
        task="Run the unit tests and summarize the result.",
        agent_id="codex",
        stage="record",
        attach_evidence=True,
    )

    assert gate(gated, "evidence").status == "skipped"
    recorded_evidence = gate(recorded, "evidence")
    assert recorded.attach_evidence is True
    assert recorded.gate_run.status == "evidence-attached"
    assert recorded.gate_run.blocked == 0
    assert recorded.execution_boundary.status == "not-prepared"
    assert recorded.handoff.status == "not-prepared"
    assert recorded_evidence.status in {"represented", "simulated"}
    assert recorded_evidence.artifact_path is not None
    artifact = json.loads(Path(recorded_evidence.artifact_path).read_text(encoding="utf-8"))
    assert artifact["executed"] is False
    assert artifact["kind"] == "local-placeholder"


def test_runtime_state_includes_recent_packets(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Ask the local runner to compile the project.",
        agent_id="local",
        stage="gate",
    )

    state = runtime_state_dict(tmp_path)

    assert state["lane_contracts"][0]["remote_execution"] is False
    assert state["route_recommendations"][0]["lane_id"] == "codex"
    assert state["route_recommendations"][0]["status"] == "recommended"
    assert state["route_recommendations"][0]["remote_execution"] is False
    assert {adapter["id"] for adapter in state["runner_adapters"]} == {"codex", "hermes"}
    assert all(adapter["remote_execution"] is False for adapter in state["runner_adapters"])
    assert state["recent_packets"][0]["packet_id"] == packet.packet_id
    assert state["recent_packets"][0]["agent_id"] == "local"
    assert state["recent_packets"][0]["lane"]["id"] == "local"
    assert state["recent_packets"][0]["lane"]["execution"] == "local-boundary-only"
    assert state["recent_packets"][0]["gate_run"]["status"] == "ready"
    assert state["recent_packets"][0]["gate_run"]["completed"] == 3
    assert state["recent_packets"][0]["execution_boundary"]["status"] == "not-prepared"
    assert state["recent_packets"][0]["runner_plan"]["status"] == "not-prepared"
    assert state["recent_packets"][0]["handoff"]["status"] == "not-prepared"
    assert state["recent_packets"][0]["memory_status"] == "checked"
    assert state["recent_packets"][0]["memory_mode"].startswith("repomori-")
    assert state["recent_packets"][0]["evidence_status"] == "skipped"
    assert state["recent_packets"][0]["route"]["recommended_lane_id"] == "local"


def test_runtime_adapter_status_reports_ready_and_unavailable_without_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "hamiltonian.runtime.probe_codex_command",
        lambda _repo: AdapterProbe(True, ("private-codex-path",), "codex-cli test"),
    )
    monkeypatch.setattr(
        "hamiltonian.runtime.probe_hermes_command",
        lambda _repo: AdapterProbe(False, ("private-hermes-path",), "Hermes probe failed"),
    )

    statuses = build_runner_adapters(tmp_path, git_available=True)
    encoded = json.dumps([status.__dict__ for status in statuses])

    assert statuses[0].id == "codex"
    assert statuses[0].available is True
    assert statuses[1].id == "hermes"
    assert statuses[1].available is False
    assert statuses[1].detail == "Hermes probe failed"
    assert "outside Hamiltonian" in statuses[1].setup_guidance
    assert all(status.remote_execution is False for status in statuses)
    assert "private-codex-path" not in encoded
    assert "private-hermes-path" not in encoded


def test_runtime_state_reflects_memory_fallback_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hamiltonian.packets.detect_integrations",
        lambda _: [
            IntegrationStatus(
                name="RepoMori",
                command="repomori",
                available=False,
                detail="not installed",
            )
        ],
    )

    create_task_packet(
        repo_path=tmp_path,
        task="Prepare packet for runtime memory fallback.",
        agent_id="codex",
        stage="gate",
    )
    state = runtime_state_dict(tmp_path)

    assert state["recent_packets"][0]["memory_status"] == "checked"
    assert state["recent_packets"][0]["memory_mode"] == "repomori-synthetic-fallback"


def test_packet_api_creates_packet_and_updates_state(tmp_path: Path) -> None:
    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Gate this task and represent evidence.",
                "agent_id": "codex",
                "stage": "record",
                "attach_evidence": True,
            }
        ).encode("utf-8")
        request = Request(
            f"{base_url}/api/packets",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            created = json.loads(response.read().decode("utf-8"))

        assert created["packet"]["status"] == "recorded"
        assert created["packet"]["attach_evidence"] is True
        assert created["packet"]["lane"]["remote_execution"] is False
        assert created["packet"]["route"]["recommended_lane_id"] == "codex"
        assert created["packet"]["route"]["remote_execution"] is False
        assert created["packet"]["gate_run"]["status"] == "evidence-attached"
        assert created["packet"]["execution_boundary"]["status"] == "not-prepared"
        assert created["packet"]["runner_plan"]["status"] == "not-prepared"
        assert created["packet"]["runner_plan"]["remote_execution"] is False
        assert created["packet"]["handoff"]["status"] == "not-prepared"

        query = urlencode({"repo": str(tmp_path)})
        with urlopen(
            f"{base_url}/api/packets/{created['packet']['packet_id']}?{query}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            detail = json.loads(response.read().decode("utf-8"))

        assert detail["packet"]["packet_id"] == created["packet"]["packet_id"]
        assert detail["packet"]["task"] == "Gate this task and represent evidence."
        assert detail["packet"]["gates"][0]["id"] == "memory"

        try:
            urlopen(f"{base_url}/api/packets/%2e%2e%2fsecret?{query}", timeout=REQUEST_TIMEOUT_SECONDS)
            raise AssertionError("invalid packet id should fail")
        except HTTPError as exc:
            assert exc.code == 400

        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            state = json.loads(response.read().decode("utf-8"))

        assert state["recent_packets"][0]["packet_id"] == created["packet"]["packet_id"]
        assert state["recent_packets"][0]["lane"]["id"] == "codex"
        assert state["recent_packets"][0]["route"]["recommended_lane_id"] == "codex"
        assert state["recent_packets"][0]["gate_run"]["completed"] == 4
        assert state["recent_packets"][0]["memory_status"] == "checked"
        assert state["recent_packets"][0]["memory_mode"].startswith("repomori-")
        assert state["recent_packets"][0]["evidence_status"] in {"represented", "simulated"}

        route_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Run a shell command smoke check.",
                "agent_id": "codex",
            }
        ).encode("utf-8")
        route_request = Request(
            f"{base_url}/api/routes",
            data=route_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(route_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            route_response = json.loads(response.read().decode("utf-8"))
        assert route_response["selected_agent_id"] == "codex"
        assert route_response["route_recommendations"][0]["lane_id"] == "local"
        assert route_response["route_recommendations"][0]["remote_execution"] is False

        invalid_route_request = Request(
            f"{base_url}/api/routes",
            data=json.dumps({"repo": str(tmp_path), "agent_id": "unknown"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(invalid_route_request, timeout=REQUEST_TIMEOUT_SECONDS)
            raise AssertionError("invalid route lane should fail")
        except HTTPError as exc:
            assert exc.code == 400

        route_draft_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Run a shell command smoke check.",
                "agent_id": "codex",
                "stage": "draft",
                "attach_evidence": False,
            }
        ).encode("utf-8")
        route_draft_request = Request(
            f"{base_url}/api/packets",
            data=route_draft_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(route_draft_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            route_draft_created = json.loads(response.read().decode("utf-8"))

        lane_payload = json.dumps({"agent_id": "local"}).encode("utf-8")
        lane_request = Request(
            f"{base_url}/api/packets/{route_draft_created['packet']['packet_id']}/lane?{query}",
            data=lane_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(lane_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            lane_selected = json.loads(response.read().decode("utf-8"))

        assert lane_selected["packet"]["packet_id"] == route_draft_created["packet"]["packet_id"]
        assert lane_selected["packet"]["agent_id"] == "local"
        assert lane_selected["packet"]["lane"]["id"] == "local"
        assert lane_selected["packet"]["route"]["recommended_lane_id"] == "local"
        assert lane_selected["packet"]["history"][-1]["event"] == "lane-selected"

        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            lane_state = json.loads(response.read().decode("utf-8"))
        assert lane_state["recent_packets"][0]["packet_id"] == lane_selected["packet"]["packet_id"]
        assert lane_state["recent_packets"][0]["agent_id"] == "local"
        assert lane_state["recent_packets"][0]["history_count"] == 2

        invalid_lane_request = Request(
            f"{base_url}/api/packets/{route_draft_created['packet']['packet_id']}/lane?{query}",
            data=json.dumps({"agent_id": "unknown"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(invalid_lane_request, timeout=REQUEST_TIMEOUT_SECONDS)
            raise AssertionError("invalid lane selection should fail")
        except HTTPError as exc:
            assert exc.code == 400

        draft_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Draft this packet before advancing it through the API.",
                "agent_id": "hermes",
                "stage": "draft",
                "attach_evidence": False,
            }
        ).encode("utf-8")
        draft_request = Request(
            f"{base_url}/api/packets",
            data=draft_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(draft_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            draft_created = json.loads(response.read().decode("utf-8"))

        advance_payload = json.dumps({"stage": "gate", "attach_evidence": False}).encode("utf-8")
        advance_request = Request(
            f"{base_url}/api/packets/{draft_created['packet']['packet_id']}/advance?{query}",
            data=advance_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(advance_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            advanced = json.loads(response.read().decode("utf-8"))

        assert advanced["packet"]["packet_id"] == draft_created["packet"]["packet_id"]
        assert advanced["packet"]["stage"] == "gate"
        assert advanced["packet"]["history"][-1]["from_stage"] == "draft"
        assert advanced["packet"]["history"][-1]["to_stage"] == "gate"
        assert advanced["packet"]["lane"]["remote_execution"] is False

        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            advanced_state = json.loads(response.read().decode("utf-8"))

        assert advanced_state["recent_packets"][0]["packet_id"] == advanced["packet"]["packet_id"]
        assert advanced_state["recent_packets"][0]["stage"] == "gate"
        assert advanced_state["recent_packets"][0]["history_count"] == 2

        execute_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Prepare execution for operator approval.",
                "agent_id": "local",
                "stage": "execute",
                "attach_evidence": False,
            }
        ).encode("utf-8")
        execute_request = Request(
            f"{base_url}/api/packets",
            data=execute_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(execute_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            execute_created = json.loads(response.read().decode("utf-8"))

        assert execute_created["packet"]["status"] == "execution-ready"
        assert execute_created["packet"]["execution_boundary"]["status"] == "awaiting-approval"
        assert execute_created["packet"]["execution_boundary"]["local_execution"] is False
        assert execute_created["packet"]["execution_boundary"]["remote_execution"] is False
        assert execute_created["packet"]["runner_plan"]["status"] == "prepared"
        assert execute_created["packet"]["runner_plan"]["mode"] == "local-dry-run"
        assert execute_created["packet"]["runner_plan"]["launch_supported"] is False
        assert execute_created["packet"]["runner_plan"]["remote_execution"] is False

        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            execute_state = json.loads(response.read().decode("utf-8"))

        assert execute_state["recent_packets"][0]["packet_id"] == execute_created["packet"]["packet_id"]
        assert execute_state["recent_packets"][0]["stage"] == "execute"
        assert execute_state["recent_packets"][0]["execution_boundary"]["status"] == "awaiting-approval"
        assert execute_state["recent_packets"][0]["runner_plan"]["status"] == "prepared"

        handoff_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Prepare a handoff packet for operator review.",
                "agent_id": "codex",
                "stage": "handoff",
                "attach_evidence": False,
            }
        ).encode("utf-8")
        handoff_request = Request(
            f"{base_url}/api/packets",
            data=handoff_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(handoff_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            handoff_created = json.loads(response.read().decode("utf-8"))

        assert handoff_created["packet"]["status"] == "handoff-ready"
        assert handoff_created["packet"]["handoff"]["status"] == "ready"
        assert handoff_created["packet"]["handoff"]["ready"] is True
        assert handoff_created["packet"]["execution_boundary"]["local_execution"] is False
        assert handoff_created["packet"]["execution_boundary"]["remote_execution"] is False
        assert handoff_created["packet"]["runner_plan"]["status"] == "prepared"
        assert handoff_created["packet"]["runner_plan"]["remote_execution"] is False

        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            handoff_state = json.loads(response.read().decode("utf-8"))

        assert handoff_state["recent_packets"][0]["packet_id"] == handoff_created["packet"]["packet_id"]
        assert handoff_state["recent_packets"][0]["stage"] == "handoff"
        assert handoff_state["recent_packets"][0]["handoff"]["status"] == "ready"

        export_request = Request(
            f"{base_url}/api/packets/{handoff_created['packet']['packet_id']}/export?{query}",
            data=b"",
            method="POST",
        )
        with urlopen(export_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            export_created = json.loads(response.read().decode("utf-8"))

        export_path = Path(export_created["export"]["path"])
        export_text = export_path.read_text(encoding="utf-8")
        assert export_created["export"]["filename"] == "handoff-export.md"
        assert export_created["packet"]["exports"]["handoff_markdown"]["sanitized"] is True
        assert export_path.exists()
        assert str(tmp_path) not in export_text

        recorder_payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Capture a quick decision trace in recorder mode.",
                "mode": "recorder",
                "agent_id": "hermes",
            }
        ).encode("utf-8")
        recorder_request = Request(
            f"{base_url}/api/packets",
            data=recorder_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(recorder_request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            recorder_created = json.loads(response.read().decode("utf-8"))

        assert recorder_created["packet"]["stage"] == "record"
        assert recorder_created["packet"]["attach_evidence"] is True
        assert recorder_created["packet"]["agent_id"] == "codex"
        assert recorder_created["packet"]["lane"]["name"] == "Codex"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_packet_api_reflects_memory_fallback_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "hamiltonian.packets.detect_integrations",
        lambda _: [
            IntegrationStatus(
                name="RepoMori",
                command="repomori",
                available=False,
                detail="not installed",
            )
        ],
    )

    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        query = urlencode({"repo": str(tmp_path)})
        payload = json.dumps(
            {
                "repo": str(tmp_path),
                "task": "Create a packet with RepoMori unavailable.",
                "agent_id": "codex",
                "stage": "gate",
                "attach_evidence": False,
            }
        ).encode("utf-8")
        request = Request(
            f"{base_url}/api/packets",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            created = json.loads(response.read().decode("utf-8"))
        packet = created["packet"]
        memory_gate = next(gate for gate in packet["gates"] if gate["id"] == "memory")
        assert memory_gate["status"] == "checked"
        assert memory_gate["mode"] == "repomori-synthetic-fallback"
        assert memory_gate["artifact_path"] is not None
        with urlopen(f"{base_url}/api/state?{query}", timeout=REQUEST_TIMEOUT_SECONDS) as response:
            state = json.loads(response.read().decode("utf-8"))
        recent = state["recent_packets"][0]
        assert recent["packet_id"] == packet["packet_id"]
        assert recent["memory_status"] == "checked"
        assert recent["memory_mode"] == "repomori-synthetic-fallback"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_ui_targets_packet_api() -> None:
    html = (ROOT / "src" / "hamiltonian" / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "src" / "hamiltonian" / "web" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "src" / "hamiltonian" / "web" / "styles.css").read_text(encoding="utf-8")

    assert 'id="packet-list"' in html
    assert 'id="packet-detail"' in html
    assert "hamiltonian-codex-goals-v1" in html
    assert 'id="mission-home"' in html
    assert 'id="local-first-badge"' in html
    assert "Local-first | remote execution: off" in html
    assert 'id="simple-run-form"' in html
    assert 'id="simple-task-input"' in html
    assert 'data-testid="simple-task"' in html
    assert 'id="simple-run-button"' in html
    assert 'id="simple-lane-picker"' in html
    assert 'data-testid="simple-lane-picker"' in html
    assert 'name="simple-agent-lane" value="auto"' in html
    assert 'name="simple-agent-lane" value="codex"' in html
    assert 'name="simple-agent-lane" value="hermes"' in html
    assert 'id="simple-lane-guidance"' in html
    assert 'data-testid="simple-lane-guidance"' in html
    assert 'id="simple-runtime-agent"' in html
    assert 'id="simple-workspace-name"' in html
    assert 'data-testid="simple-run"' in html
    assert 'id="simple-run-status"' in html
    assert 'data-testid="simple-status"' in html
    assert 'id="simple-run-options"' in html
    assert 'id="simple-evidence-toggle"' in html
    assert 'id="simple-timeout-input"' in html
    assert 'id="simple-open-manual"' in html
    assert 'id="simple-open-packet"' in html
    assert 'id="simple-goal-button"' in html
    assert 'id="simple-compare-button"' in html
    assert 'data-testid="compare-agents"' in html
    assert 'id="comparison-dialog"' in html
    assert 'id="comparison-primary-result"' in html
    assert 'id="comparison-secondary-result"' in html
    assert 'id="comparison-run-button"' in html
    assert 'data-testid="run-comparison"' in html
    assert 'data-testid="get-codex-goal"' in html
    assert 'id="goal-dialog"' in html
    assert 'id="goal-type-maintenance"' in html
    assert 'id="goal-type-expansion"' in html
    assert 'id="goal-expansion-input"' in html
    assert 'id="goal-preview"' in html
    assert 'id="goal-copy-button"' in html
    assert 'id="goal-save-button"' in html
    assert 'id="goal-open-codex-button"' in html
    assert 'id="goal-review-button"' in html
    assert 'id="simple-step-check"' in html
    assert 'id="simple-step-run"' in html
    assert 'id="simple-step-done"' in html
    assert "<span>[]</span>" not in html
    assert 'id="home-recent-packets"' in html
    assert 'id="home-goal-history"' in html
    assert 'id="goal-history-list"' in html
    assert 'id="goal-history-summary"' in html
    assert 'data-page-target="create"' in html
    assert 'data-pages="create"' in html
    assert 'id="create-back-home"' in html
    assert 'id="create-task-count"' in html
    assert 'id="create-route-title"' in html
    assert 'id="create-evidence-title"' in html
    assert 'id="create-boundary-mode"' in html
    assert 'id="create-review-routes"' in html
    assert 'id="mode-orchestrate"' in html
    assert 'id="mode-recorder"' in html
    assert 'id="recorder-button"' in html
    assert 'id="lane-control"' in html
    assert 'id="orchestrate-tools"' in html
    assert 'id="recorder-tools"' in html
    assert 'id="recorder-intro"' in html
    assert 'id="cockpit-title"' in html
    assert 'aria-label="Sections"' in html
    assert 'role="tablist"' in html
    assert 'data-page-target="start"' in html
    assert 'data-icon="home"' in html
    assert 'data-icon="H"' not in html
    assert 'data-page-target="learn"' in html
    assert 'data-page-target="recorder"' in html
    assert 'data-page-target="handoff"' in html
    assert 'data-page-target="advanced"' in html
    assert 'id="mission-map"' in html
    assert 'data-pages="map learn"' in html
    assert 'id="mission-hud"' in html
    assert 'id="mission-hud-count"' in html
    assert 'id="mission-hud-title"' in html
    assert 'id="mission-hud-body"' in html
    assert 'id="mission-hud-steps"' in html
    assert 'id="mission-hud-action"' in html
    assert 'id="mission-hud-map"' in html
    assert 'id="mission-hud-guide"' in html
    assert 'id="map-path"' in html
    assert 'id="map-current"' in html
    assert 'id="map-action"' in html
    assert 'id="tutorial"' in html
    assert 'data-pages="learn"' in html
    assert 'id="tutorial-current"' in html
    assert 'id="tutorial-coach"' in html
    assert 'id="tutorial-action"' in html
    assert 'id="guide-toggle"' in html
    assert 'id="guide-layer"' in html
    assert 'id="guide-step-count"' in html
    assert 'id="guide-progress-fill"' in html
    assert 'id="guide-action"' in html
    assert 'class="tutorial-step"' in html
    assert 'data-stage="execute"' in html
    assert 'id="advanced"' in html
    assert 'data-pages="advanced"' in html
    assert 'class="panel wide advanced-settings-screen"' in html
    assert 'id="advanced-tabs"' in html
    assert 'data-advanced-tab="integrations"' in html
    assert 'data-advanced-tab="route-scoring"' in html
    assert 'id="advanced-data-sources"' in html
    assert 'id="advanced-source-count"' in html
    assert 'id="advanced-integration-count"' in html
    assert 'id="advanced-agent-count"' in html
    assert 'id="advanced-route-recommendation"' in html
    assert 'id="advanced-route-bars"' in html
    assert 'id="advanced-evidence-settings"' in html
    assert 'id="advanced-privacy-settings"' in html
    assert 'id="advanced-debug-settings"' in html
    assert 'id="advanced-debug-state"' in html
    assert 'id="next-build"' in html
    assert 'id="mission-path"' in html
    assert 'id="mission-next"' in html
    assert 'id="route-compass"' in html
    assert 'id="route-list"' in html
    assert "Agent lane selection" in html
    assert 'class="panel wide agent-lane-screen"' in html
    assert 'id="route-screen-title"' in html
    assert 'id="route-recommended-badge"' in html
    assert 'id="route-impact"' in html
    assert 'id="route-selection-count"' in html
    assert 'id="route-override-title"' in html
    assert 'id="route-override-body"' in html
    assert 'id="route-selection-summary"' in html
    assert 'id="route-cancel-button"' in html
    assert 'id="route-confirm-button"' in html
    assert 'data-page-target="gates"' in html
    assert 'class="panel wide gate-readiness-view"' in html
    assert 'id="gate-view-title"' in html
    assert 'id="gate-summary-metrics"' in html
    assert 'id="gate-selected-detail"' in html
    assert 'id="gate-required-actions"' in html
    assert 'id="gate-primary-action"' in html
    assert 'id="gate-back-packet"' in html
    assert 'class="panel wide flight-recorder-screen"' in html
    assert 'id="recorder-panel"' in html
    assert 'data-pages="recorder"' in html
    assert 'id="recorder-back-packet"' in html
    assert 'id="recorder-screen-title"' in html
    assert 'id="recorder-status-badge"' in html
    assert 'id="recorder-status-title"' in html
    assert 'id="recorder-task-input"' in html
    assert 'id="recorder-task-count"' in html
    assert 'id="recorder-packet-object"' in html
    assert 'id="recorder-evidence-list"' in html
    assert 'id="recorder-proof-bundle"' in html
    assert 'id="recorder-create-button"' in html
    assert 'id="recorder-open-packet-button"' in html
    assert 'class="panel wide handoff-export-screen"' in html
    assert 'id="handoff-panel"' in html
    assert 'data-pages="handoff"' in html
    assert 'id="handoff-back-packet"' in html
    assert 'id="handoff-screen-title"' in html
    assert 'id="handoff-ready-badge"' in html
    assert 'id="handoff-ready-title"' in html
    assert 'id="handoff-readiness-list"' in html
    assert 'id="handoff-packet-object"' in html
    assert 'id="handoff-export-summary"' in html
    assert 'id="handoff-primary-button"' in html
    assert 'id="handoff-export-button"' in html
    assert 'id="handoff-open-packet-button"' in html
    assert 'id="handoff-evidence-state"' in html
    assert 'id="handoff-share-link-button"' in html
    assert 'id="handoff-save-vault-button"' in html
    assert 'id="handoff-footer-note"' in html
    assert 'Local-first | remote execution: off' in html
    assert 'fetch("/api/packets"' in app
    assert 'fetch("/api/routes"' in app
    assert "function renderRoutes" in app
    assert 'row.dataset.testid = "route-lane"' in app
    assert 'useButton.dataset.testid = "select-route-lane"' in app
    assert "pendingRouteLaneId" in app
    assert "function routeSelectionLaneId" in app
    assert "function routeImpactMetric" in app
    assert "function renderRouteCompass" in app
    assert "function initRouteSelectionControls" in app
    assert "function renderMissionHome" in app
    assert 'const PAGE_ORDER = ["start", "create", "map", "learn", "routes", "gates", "recorder"' in app
    assert '"handoff", "packets"' in app
    assert 'cockpit: "create"' in app
    assert 'gates: "gates"' in app
    assert '"recorder-panel": "recorder"' in app
    assert '"handoff-panel": "handoff"' in app
    assert "function homePacketForDisplay" in app
    assert "function renderHomeReadiness" in app
    assert "function renderHomeEvidence" in app
    assert "function renderHomeRecentPackets" in app
    assert 'card.dataset.testid = "home-recent-packet"' in app
    assert "card.dataset.packetId = packet.packet_id" in app
    assert "function initMissionHomeControls" in app
    assert "function renderCreatePacketScreen" in app
    assert "function initCreatePacketControls" in app
    assert "function recorderPacketForDisplay" in app
    assert "function renderFlightRecorder" in app
    assert "function createRecorderPacketFromScreen" in app
    assert "function initFlightRecorderControls" in app
    assert "recorder-task-input" in app
    assert "function handoffPacketForDisplay" in app
    assert "function handoffExportForPacket" in app
    assert "has_handoff_export" in app
    assert "handoff_export_filename" in app
    assert "function renderHandoffExport" in app
    assert "function renderHandoffSummary" in app
    assert "function prepareHandoffPacket" in app
    assert "function exportHandoffPacket" in app
    assert "function initHandoffExportControls" in app
    assert 'activePage === "handoff" && state.data' in app
    assert "handoff-primary-button" in app
    assert "handoff-export-button" in app
    assert "Share links and vault sync are disabled" in app
    assert "function renderAdvancedSettings" in app
    assert "function renderAdvancedDataSources" in app
    assert "function renderAdvancedRouteScoring" in app
    assert "function renderAdvancedStaticSettings" in app
    assert "advanced-about-settings" in html
    assert 'data-advanced-tab="about"' in html
    assert "Crash diagnostics" in app
    assert "function initAdvancedSettingsControls" in app
    assert "function advancedTabTarget" in app
    assert "advanced-route-score" in app
    assert "advanced-tab-active" in app
    assert "AgentLedger stays out unless you attach evidence or use recorder mode." in app
    assert "function runSimpleMission" in app
    assert "function cancelSimpleMission" in app
    assert "function pollSimpleRunner" in app
    assert "function renderSimpleRunExperience" in app
    assert "function renderSimpleLanePicker" in app
    assert "function resolveSimpleLane" in app
    assert "function refreshSimpleRoutes" in app
    assert "agent_id: laneId" in app
    assert "simple-run-button" in app
    assert "function openGoalBuilder" in app
    assert "function openComparisonDialog" in app
    assert "function runComparison" in app
    assert "function pollComparisonRun" in app
    assert "function persistComparison" in app
    assert 'fetch("/api/comparisons"' in app
    assert "function refreshGoalPreview" in app
    assert "function ensureGoalSaved" in app
    assert "function openGoalInCodex" in app
    assert "function reviewCompletedGoal" in app
    assert "function renderGoalHistory" in app
    assert "function refreshGoalHistory" in app
    assert "function reviewGoalById" in app
    assert "function createCorrectiveGoal" in app
    assert "function recordGoalReview" in app
    assert "AgentLedger evidence is represented locally only." in app
    assert "route-strength" in app
    assert "route-boundary" in app
    assert "route-kicker" in app
    assert "function statusTone" in app
    assert "chip-confirmed" in app
    assert "chip-ready" in app
    assert "chip-advisory" in app
    assert "chip-optional" in app
    assert "chip-blocked" in app
    assert "function scheduleLiveRouteUpdate" in app
    assert "function refreshLiveRoutes" in app
    assert "function initPageNavigation" in app
    assert "function revealSection" in app
    assert "data-page-target" in app
    assert "function useRouteLane" in app
    assert "function selectPacketLane" in app
    assert "/lane?${params.toString()}" in app
    assert "packetHasLaneDecision" in app
    assert "Run gates" in app
    assert "function renderMissionMap" in app
    assert "function missionHudBody" in app
    assert "function missionHudStepLabel" in app
    assert "function renderMissionHud" in app
    assert "mission-hud-step-${status}" in app
    assert "openGuide(tutorialStage(packet))" in app
    assert 'revealSection("mission-map")' in app
    assert "function moveMapCursor" in app
    assert "function activateMapCursor" in app
    assert "function mapActionFor" in app
    assert "function runMapAction" in app
    assert "map-node-${status}" in app
    assert "map-node-orbit" in app
    assert "map-node-hint" in app
    assert "map-node-cursor" in app
    assert "--map-progress" in app
    assert "function renderTutorial" in app
    assert "function renderGuide" in app
    assert "function openGuide" in app
    assert "function closeGuide" in app
    assert "function setGuideStage" in app
    assert "function moveGuideStep" in app
    assert "function handleGlobalKeydown" in app
    assert "function guideTargetForStage" in app
    assert "const TUTORIAL_STEPS" in app
    assert "function runTutorialStep" in app
    assert "function tutorialButtonLabel" in app
    assert "tutorial-step-active" in app
    assert "tutorial-step-action" in app
    assert "guide-focus" in app
    assert "function renderPacketDetail" in app
    assert "packetDetailTab" in app
    assert "function renderPacketMissionControl" in app
    assert "function gateToneName" in app
    assert "function gateDisplayPacket" in app
    assert "function renderGateSelectedDetail" in app
    assert 'row.dataset.testid = "gate-row"' in app
    assert "function renderGateRequiredActions" in app
    assert "function initGateViewControls" in app
    assert ".flight-recorder-screen" in styles
    assert ".recorder-screen-layout" in styles
    assert ".recorder-waveform" in styles
    assert ".recorder-evidence-row" in styles
    assert ".recorder-footer" in styles
    assert ".handoff-export-screen" in styles
    assert ".handoff-screen-layout" in styles
    assert ".handoff-ready-emblem" in styles
    assert ".handoff-readiness-row" in styles
    assert ".handoff-summary-row" in styles
    assert ".handoff-footer" in styles
    assert ".advanced-settings-screen" in styles
    assert ".advanced-tabs" in styles
    assert ".advanced-settings-layout" in styles
    assert ".advanced-route-bar" in styles
    assert ".advanced-setting-row" in styles
    assert "function packetStatusRows" in app
    assert 'label: "Runner plan"' in app
    assert 'row.dataset.testid = `packet-status-${String(item.label' in app
    assert "function detailPanel" in app
    assert "function applyPacketDetailTab" in app
    assert "function initPacketDetailControls" in app
    assert "AgentLedger is represented as a local placeholder for this packet." in app
    assert "loadPacketDetail(packet.packet_id)" in app
    assert "fetch(`/api/packets/${encodeURIComponent(packetId)}?${params.toString()}`)" in app
    assert 'id="packet-export-button"' in html
    assert "packet-mission-control" in html
    assert 'id="packet-control-back"' in html
    assert 'id="packet-control-local"' in html
    assert 'id="detail-packet-object"' in html
    assert 'id="detail-packet-title"' in html
    assert 'id="detail-evidence-stamp"' in html
    assert 'id="packet-detail-tabs"' in html
    assert 'data-packet-tab="overview"' in html
    assert 'data-packet-tab="gates"' in html
    assert 'id="packet-status-list"' in html
    assert 'id="packet-command"' in html
    assert 'id="packet-primary-action"' in html
    assert 'id="packet-runner-control"' in html
    assert 'data-testid="runner-control"' in html
    assert 'id="runner-timeout-input"' in html
    assert 'id="runner-launch-button"' in html
    assert 'data-testid="runner-launch"' in html
    assert 'id="runner-cancel-button"' in html
    assert 'data-testid="runner-cancel"' in html
    assert 'id="runner-event-list"' in html
    assert 'id="runner-final-message"' in html
    assert 'id="readiness-strip"' in html
    assert 'id="readiness-detail"' in html
    assert 'id="packet-gate-button"' in html
    assert 'id="packet-execute-button"' in html
    assert 'id="packet-handoff-button"' in html
    assert 'id="packet-record-button"' in html
    assert "function readinessItemsForPacket" in app
    assert "function readinessSelectedItem" in app
    assert "function renderReadinessDetail" in app
    assert "function renderReadinessStrip" in app
    assert "readinessFocus" in app
    assert "readiness-item" in app
    assert "readiness-copy" in app
    assert "readiness-item-selected" in app
    assert 'aria-controls", "readiness-detail"' in app
    assert 'aria-pressed"' in app
    assert "Execution is a manual approval boundary" in app
    assert "Gates decide whether the packet can move" in app
    assert "AgentLedger stays out unless evidence is selected." in app
    assert "RepoMori boundary" in app
    assert "manual only" in app
    assert "function exportSelectedPacket" in app
    assert "fetch(`/api/packets/${encodeURIComponent(packetId)}/export?${params.toString()}`" in app
    assert "function updatePacketAdvanceButtons" in app
    assert "function packetCommandState" in app
    assert "function updatePacketCommand" in app
    assert "function renderRunnerControl" in app
    assert "function refreshSelectedRunnerRun" in app
    assert "function launchSelectedRunner" in app
    assert "function cancelSelectedRunner" in app
    assert "function initRunnerControls" in app
    assert "/run/cancel?${params.toString()}" in app
    assert "/run?${params.toString()}" in app
    assert "function packetActionLockReason" in app
    assert "locked-action" in app
    assert "next-action" in app
    assert "primary-action" in html
    assert "function advanceSelectedPacket" in app
    assert "advanceSelectedPacket(\"gate\")" in app
    assert "advanceSelectedPacket(\"execute\")" in app
    assert "advanceSelectedPacket(\"handoff\")" in app
    assert "advanceSelectedPacket(\"record\")" in app
    assert "function renderMissionPath" in app
    assert "buildAdvancePlan" in app
    assert "Memory: ${memoryStatus}" in app
    assert "Lane: ${lane.status}" in app
    assert "Route: ${route.status" in app
    assert "Gates: ${gateRun.completed}/${gateRun.total}" in app
    assert 'id="execute-button"' in html
    assert 'submitPacket("execute")' in app
    assert "Execute: ${executionBoundary.status}" in app
    assert "Runner: ${runnerPlan.status}" in app
    assert 'id="handoff-button"' in html
    assert 'submitPacket("handoff")' in app
    assert "Handoff: ${handoff.status}" in app
    assert "--surface-1" in styles
    assert "--accent: #ff6a00" in styles
    assert "@media (max-width: 620px)" in styles
    assert "position: sticky" in styles
    assert "calc(100% - 150px)" in styles
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles
    assert ".topbar .eyebrow" in styles
    assert ".mission-home" in styles
    assert ".create-packet-screen" in styles
    assert ".create-layout" in styles
    assert ".stage-action-grid" in styles
    assert ".create-side-card" in styles
    assert ".agent-lane-screen" in styles
    assert ".lane-screen-layout" in styles
    assert ".lane-option-card" in styles
    assert ".lane-option-selected" in styles
    assert ".lane-selection-footer" in styles
    assert ".packet-mission-control" in styles
    assert ".packet-control-layout" in styles
    assert ".gate-readiness-view" in styles
    assert ".gate-view-layout" in styles
    assert ".gate-check-row" in styles
    assert ".gate-tone-blocked" in styles
    assert ".gate-summary-metrics" in styles
    assert ".advanced-card" in styles
    assert ".advanced-route-top" in styles
    assert ".advanced-module-list" in styles
    assert ".packet-status-row" in styles
    assert ".packet-runner-control" in styles
    assert ".runner-control-grid" in styles
    assert ".runner-progress-track" in styles
    assert ".runner-event-row" in styles
    assert ".runner-final-message" in styles
    assert ".comparison-dialog" in styles
    assert ".comparison-results" in styles
    assert ".comparison-result-text" in styles
    assert ".detail-panel-section" in styles
    assert ".packet-detail-tabs button" in styles
    assert ".mission-packet-object" in styles
    assert ".home-readiness-list" in styles
    assert ".home-evidence-option" in styles
    assert ".home-recent-packets" in styles
    assert ".simple-goal-history" in styles
    assert ".goal-history-row" in styles
    assert ".goal-history-badge" in styles
