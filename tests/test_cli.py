from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

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


def test_runtime_state_keeps_agentledger_optional(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)

    state = build_runtime_state(tmp_path)

    assert state.repo_name == tmp_path.name
    assert any(agent.id == "openclaw" for agent in state.agents)
    assert any(agent.id == "hermes" for agent in state.agents)
    evidence_gate = next(gate for gate in state.gates if gate.id == "evidence")
    assert evidence_gate.integration == "AgentLedger"
    assert "optional" in evidence_gate.status or evidence_gate.status == "available as module"
