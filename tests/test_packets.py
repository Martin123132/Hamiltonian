from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hamiltonian.packets import create_task_packet, list_task_packets
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

        query = urlencode({"repo": str(tmp_path)})
        with urlopen(f"{base_url}/api/state?{query}", timeout=10) as response:
            state = json.loads(response.read().decode("utf-8"))

        assert state["recent_packets"][0]["packet_id"] == created["packet"]["packet_id"]
        assert state["recent_packets"][0]["lane"]["id"] == "codex"
        assert state["recent_packets"][0]["gate_run"]["completed"] == 4
        assert state["recent_packets"][0]["memory_status"] == "checked"
        assert state["recent_packets"][0]["memory_mode"].startswith("repomori-")
        assert state["recent_packets"][0]["evidence_status"] in {"represented", "simulated"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_static_ui_targets_packet_api() -> None:
    html = (ROOT / "src" / "hamiltonian" / "web" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "src" / "hamiltonian" / "web" / "app.js").read_text(encoding="utf-8")

    assert 'id="packet-list"' in html
    assert 'fetch("/api/packets"' in app
    assert "Memory: ${memoryStatus}" in app
    assert "Lane: ${lane.status}" in app
    assert "Gates: ${gateRun.completed}/${gateRun.total}" in app
