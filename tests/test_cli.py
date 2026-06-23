from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from hamiltonian.packets import create_task_packet
from hamiltonian.runtime import build_runtime_state


def test_doctor_runs(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    env = {**os.environ, "PYTHONPATH": str(SRC)}
    proc = subprocess.run(
        [sys.executable, "-m", "hamiltonian", "doctor", "--repo", str(tmp_path), "--json"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "integrations" in proc.stdout


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


def test_runtime_state_keeps_agentledger_optional(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)

    state = build_runtime_state(tmp_path)

    assert state.repo_name == tmp_path.name
    assert any(agent.id == "openclaw" for agent in state.agents)
    assert any(agent.id == "hermes" for agent in state.agents)
    evidence_gate = next(gate for gate in state.gates if gate.id == "evidence")
    assert evidence_gate.integration == "AgentLedger"
    assert "optional" in evidence_gate.status or evidence_gate.status == "available as module"
