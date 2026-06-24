from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from hamiltonian.packets import TASK_INDEX_SCHEMA, create_task_packet, task_index_path
from hamiltonian.runtime import build_runtime_state


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    return subprocess.run(
        [sys.executable, "-m", "hamiltonian", *args],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_doctor_runs(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    proc = run_cli(["doctor", "--repo", str(tmp_path), "--json"])
    assert proc.returncode == 0, proc.stderr
    assert "integrations" in proc.stdout


def test_packets_cli_creates_local_packets(tmp_path: Path) -> None:
    draft_proc = run_cli(
        [
            "packets",
            "--repo",
            str(tmp_path),
            "create",
            "--task",
            "Draft a CLI-created packet for a local Hermes lane.",
            "--agent",
            "hermes",
            "--stage",
            "draft",
            "--json",
        ]
    )
    assert draft_proc.returncode == 0, draft_proc.stderr
    draft = json.loads(draft_proc.stdout)["packet"]
    assert draft["agent_id"] == "hermes"
    assert draft["stage"] == "draft"
    assert draft["status"] == "drafted"
    assert draft["attach_evidence"] is False
    assert draft["lane"]["remote_execution"] is False
    assert draft["gate_run"]["pending"] == 3
    draft_evidence_gate = next(gate for gate in draft["gates"] if gate["id"] == "evidence")
    assert draft_evidence_gate["status"] == "skipped"
    assert Path(draft["files"]["json"]).exists()
    assert Path(draft["files"]["markdown"]).exists()
    assert not (Path(draft["packet_dir"]) / "evidence").exists()

    advance_proc = run_cli(
        [
            "packets",
            "--repo",
            str(tmp_path),
            "advance",
            draft["packet_id"],
            "--stage",
            "gate",
            "--json",
        ]
    )
    assert advance_proc.returncode == 0, advance_proc.stderr
    advanced = json.loads(advance_proc.stdout)["packet"]
    assert advanced["packet_id"] == draft["packet_id"]
    assert advanced["stage"] == "gate"
    assert advanced["history"][-1]["from_stage"] == "draft"
    assert advanced["history"][-1]["to_stage"] == "gate"
    assert Path(advanced["files"]["history"]).exists()

    same_stage_proc = run_cli(
        [
            "packets",
            "--repo",
            str(tmp_path),
            "advance",
            draft["packet_id"],
            "--stage",
            "gate",
        ]
    )
    assert same_stage_proc.returncode == 2
    assert "target stage must advance packet forward" in same_stage_proc.stderr

    evidence_proc = run_cli(
        [
            "packets",
            "--repo",
            str(tmp_path),
            "create",
            "--task",
            "Gate a CLI-created packet with optional evidence represented.",
            "--agent",
            "codex",
            "--stage",
            "gate",
            "--attach-evidence",
            "--json",
        ]
    )
    assert evidence_proc.returncode == 0, evidence_proc.stderr
    evidence_packet = json.loads(evidence_proc.stdout)["packet"]
    evidence_gate = next(gate for gate in evidence_packet["gates"] if gate["id"] == "evidence")
    assert evidence_packet["attach_evidence"] is True
    assert evidence_gate["status"] in {"represented", "simulated"}
    assert Path(evidence_gate["artifact_path"]).exists()

    list_proc = run_cli(["packets", "--repo", str(tmp_path), "list", "--json"])
    assert list_proc.returncode == 0, list_proc.stderr
    listed_ids = {packet["packet_id"] for packet in json.loads(list_proc.stdout)["packets"]}
    assert {draft["packet_id"], evidence_packet["packet_id"]} <= listed_ids

    invalid_proc = run_cli(
        [
            "packets",
            "--repo",
            str(tmp_path),
            "create",
            "--task",
            "   ",
        ]
    )
    assert invalid_proc.returncode == 2
    assert "task must not be empty" in invalid_proc.stderr


def test_packets_cli_lists_details_and_exports(tmp_path: Path) -> None:
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Prepare CLI packet handoff with TOKEN=supersecret.",
        agent_id="codex",
        stage="handoff",
    )
    env = {**os.environ, "PYTHONPATH": str(SRC)}

    list_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hamiltonian",
            "packets",
            "--repo",
            str(tmp_path),
            "list",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert list_proc.returncode == 0, list_proc.stderr
    listed = json.loads(list_proc.stdout)
    assert listed["packets"][0]["packet_id"] == packet.packet_id

    detail_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hamiltonian",
            "packets",
            "--repo",
            str(tmp_path),
            "detail",
            packet.packet_id,
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert detail_proc.returncode == 0, detail_proc.stderr
    detail = json.loads(detail_proc.stdout)
    assert detail["packet"]["packet_id"] == packet.packet_id
    assert detail["packet"]["handoff"]["status"] == "ready"

    export_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hamiltonian",
            "packets",
            "--repo",
            str(tmp_path),
            "export",
            packet.packet_id,
            "--json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert export_proc.returncode == 0, export_proc.stderr
    exported = json.loads(export_proc.stdout)
    export_path = Path(exported["export"]["path"])
    export_text = export_path.read_text(encoding="utf-8")
    assert exported["export"]["filename"] == "handoff-export.md"
    assert exported["export"]["sanitized"] is True
    assert export_path.exists()
    assert "supersecret" not in export_text

    invalid_proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "hamiltonian",
            "packets",
            "--repo",
            str(tmp_path),
            "detail",
            "../secret",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert invalid_proc.returncode == 2
    assert "invalid packet id" in invalid_proc.stderr


def test_packets_cli_rebuilds_packet_index(tmp_path: Path) -> None:
    first = create_task_packet(
        repo_path=tmp_path,
        task="Create the first packet before rebuilding the index.",
        agent_id="codex",
        stage="draft",
    )
    second = create_task_packet(
        repo_path=tmp_path,
        task="Create the second packet before rebuilding the index.",
        agent_id="local",
        stage="gate",
    )
    index_path = task_index_path(tmp_path)
    index_path.write_text(
        json.dumps({"schema": "broken", "packet_count": 0, "packets": []}),
        encoding="utf-8",
    )

    rebuild_proc = run_cli(["packets", "--repo", str(tmp_path), "rebuild-index", "--json"])

    assert rebuild_proc.returncode == 0, rebuild_proc.stderr
    rebuilt = json.loads(rebuild_proc.stdout)["index"]
    assert rebuilt["schema"] == TASK_INDEX_SCHEMA
    assert rebuilt["packet_count"] == 2
    assert {packet["packet_id"] for packet in rebuilt["packets"]} == {
        first.packet_id,
        second.packet_id,
    }
    assert "packet_dir" not in rebuilt["packets"][0]

    saved = json.loads(index_path.read_text(encoding="utf-8"))
    assert saved["schema"] == TASK_INDEX_SCHEMA
    assert saved["packet_count"] == 2


def test_runtime_state_keeps_agentledger_optional(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)

    state = build_runtime_state(tmp_path)

    assert state.repo_name == tmp_path.name
    assert any(agent.id == "openclaw" for agent in state.agents)
    assert any(agent.id == "hermes" for agent in state.agents)
    evidence_gate = next(gate for gate in state.gates if gate.id == "evidence")
    assert evidence_gate.integration == "AgentLedger"
    assert "optional" in evidence_gate.status or evidence_gate.status == "available as module"
