from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from hamiltonian.packets import create_task_packet, get_task_packet, list_task_packets
from hamiltonian.runtime import runtime_state_dict
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]


def gate(packet, gate_id: str):
    return next(item for item in packet.gates if item.id == gate_id)


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
    assert data["gate_run"]["status"] == "pending"
    assert data["gate_run"]["completed"] == 0
    assert data["gate_run"]["pending"] == 3
    assert gate(packet, "intent").status == "pending"
    assert gate(packet, "evidence").status == "skipped"
    assert list_task_packets(tmp_path)[0]["packet_id"] == packet.packet_id


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
    assert packet.lane.execution == "adapter-boundary-only"
    assert packet.lane.remote_execution is False
    assert packet.gate_run.status == "blocked"
    assert packet.gate_run.blocked == 1
    assert packet.gate_run.blocked_gate_ids == ["intent"]
    assert gate(packet, "memory").status == "checked"
    assert gate(packet, "memory").mode.startswith("repomori-")
    assert gate(packet, "memory").artifact_path is not None
    assert gate(packet, "intent").status == "block"
    assert gate(packet, "evidence").status == "skipped"
    assert not (Path(packet.packet_dir) / "evidence").exists()


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
    assert gate(packet, "memory").status == "checked"
    assert gate(packet, "evidence").status == "skipped"
    assert not (Path(packet.packet_dir) / "evidence").exists()

    data = json.loads(Path(packet.files["json"]).read_text(encoding="utf-8"))
    assert data["execution_boundary"]["status"] == "awaiting-approval"
    assert data["execution_boundary"]["local_execution"] is False
    assert data["execution_boundary"]["remote_execution"] is False


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

    assert state["recent_packets"][0]["packet_id"] == packet.packet_id
    assert state["recent_packets"][0]["agent_id"] == "local"
    assert state["recent_packets"][0]["lane"]["id"] == "local"
    assert state["recent_packets"][0]["lane"]["execution"] == "local-boundary-only"
    assert state["recent_packets"][0]["gate_run"]["status"] == "ready"
    assert state["recent_packets"][0]["gate_run"]["completed"] == 3
    assert state["recent_packets"][0]["execution_boundary"]["status"] == "not-prepared"
    assert state["recent_packets"][0]["handoff"]["status"] == "not-prepared"
    assert state["recent_packets"][0]["memory_status"] == "checked"
    assert state["recent_packets"][0]["memory_mode"].startswith("repomori-")
    assert state["recent_packets"][0]["evidence_status"] == "skipped"


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
        with urlopen(request, timeout=10) as response:
            created = json.loads(response.read().decode("utf-8"))

        assert created["packet"]["status"] == "recorded"
        assert created["packet"]["attach_evidence"] is True
        assert created["packet"]["lane"]["remote_execution"] is False
        assert created["packet"]["gate_run"]["status"] == "evidence-attached"
        assert created["packet"]["execution_boundary"]["status"] == "not-prepared"
        assert created["packet"]["handoff"]["status"] == "not-prepared"

        query = urlencode({"repo": str(tmp_path)})
        with urlopen(
            f"{base_url}/api/packets/{created['packet']['packet_id']}?{query}",
            timeout=10,
        ) as response:
            detail = json.loads(response.read().decode("utf-8"))

        assert detail["packet"]["packet_id"] == created["packet"]["packet_id"]
        assert detail["packet"]["task"] == "Gate this task and represent evidence."
        assert detail["packet"]["gates"][0]["id"] == "memory"

        try:
            urlopen(f"{base_url}/api/packets/%2e%2e%2fsecret?{query}", timeout=10)
            raise AssertionError("invalid packet id should fail")
        except HTTPError as exc:
            assert exc.code == 400

        with urlopen(f"{base_url}/api/state?{query}", timeout=10) as response:
            state = json.loads(response.read().decode("utf-8"))

        assert state["recent_packets"][0]["packet_id"] == created["packet"]["packet_id"]
        assert state["recent_packets"][0]["lane"]["id"] == "codex"
        assert state["recent_packets"][0]["gate_run"]["completed"] == 4
        assert state["recent_packets"][0]["memory_status"] == "checked"
        assert state["recent_packets"][0]["memory_mode"].startswith("repomori-")
        assert state["recent_packets"][0]["evidence_status"] in {"represented", "simulated"}

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
        with urlopen(execute_request, timeout=10) as response:
            execute_created = json.loads(response.read().decode("utf-8"))

        assert execute_created["packet"]["status"] == "execution-ready"
        assert execute_created["packet"]["execution_boundary"]["status"] == "awaiting-approval"
        assert execute_created["packet"]["execution_boundary"]["local_execution"] is False
        assert execute_created["packet"]["execution_boundary"]["remote_execution"] is False

        with urlopen(f"{base_url}/api/state?{query}", timeout=10) as response:
            execute_state = json.loads(response.read().decode("utf-8"))

        assert execute_state["recent_packets"][0]["packet_id"] == execute_created["packet"]["packet_id"]
        assert execute_state["recent_packets"][0]["stage"] == "execute"
        assert execute_state["recent_packets"][0]["execution_boundary"]["status"] == "awaiting-approval"

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
        with urlopen(handoff_request, timeout=10) as response:
            handoff_created = json.loads(response.read().decode("utf-8"))

        assert handoff_created["packet"]["status"] == "handoff-ready"
        assert handoff_created["packet"]["handoff"]["status"] == "ready"
        assert handoff_created["packet"]["handoff"]["ready"] is True
        assert handoff_created["packet"]["execution_boundary"]["local_execution"] is False
        assert handoff_created["packet"]["execution_boundary"]["remote_execution"] is False

        with urlopen(f"{base_url}/api/state?{query}", timeout=10) as response:
            handoff_state = json.loads(response.read().decode("utf-8"))

        assert handoff_state["recent_packets"][0]["packet_id"] == handoff_created["packet"]["packet_id"]
        assert handoff_state["recent_packets"][0]["stage"] == "handoff"
        assert handoff_state["recent_packets"][0]["handoff"]["status"] == "ready"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_ui_targets_packet_api() -> None:
    html = (ROOT / "src" / "hamiltonian" / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "src" / "hamiltonian" / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="packet-list"' in html
    assert 'id="packet-detail"' in html
    assert 'fetch("/api/packets"' in app
    assert "function renderPacketDetail" in app
    assert "loadPacketDetail(packet.packet_id)" in app
    assert "fetch(`/api/packets/${encodeURIComponent(packetId)}?${params.toString()}`)" in app
    assert "Memory: ${memoryStatus}" in app
    assert "Lane: ${lane.status}" in app
    assert "Gates: ${gateRun.completed}/${gateRun.total}" in app
    assert 'id="execute-button"' in html
    assert 'submitPacket("execute")' in app
    assert "Execute: ${executionBoundary.status}" in app
    assert 'id="handoff-button"' in html
    assert 'submitPacket("handoff")' in app
    assert "Handoff: ${handoff.status}" in app
