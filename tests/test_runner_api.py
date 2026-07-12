from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hamiltonian.packets import create_task_packet
from hamiltonian.runners import LocalRunManager
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]


def init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_packet_runner_api_launches_polls_and_persists_local_result(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Complete the API runner smoke path.",
        agent_id="codex",
        stage="execute",
    )
    assert packet.runner_plan.launch_supported is True

    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    Handler.run_manager = LocalRunManager()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        query = urlencode({"repo": str(tmp_path)})
        launch = Request(
            f"{base_url}/api/packets/{packet.packet_id}/run?{query}",
            data=json.dumps({"timeout_seconds": 10}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(launch, timeout=20) as response:
            assert response.status == 201
            started = json.loads(response.read().decode("utf-8"))["run"]
        assert started["status"] in {"running", "succeeded"}
        assert started["remote_execution"] is False

        deadline = time.monotonic() + 15
        completed = None
        while time.monotonic() < deadline:
            with urlopen(
                f"{base_url}/api/packets/{packet.packet_id}/run?{query}",
                timeout=20,
            ) as response:
                completed = json.loads(response.read().decode("utf-8"))["run"]
            if completed["status"] not in {"starting", "running", "cancelling"}:
                break
            time.sleep(0.05)
        assert completed is not None
        assert completed["status"] == "succeeded"
        assert completed["local_execution"] is True
        assert completed["remote_execution"] is False
        assert completed["last_message"] == "Synthetic Codex run completed locally."
        assert any(event["type"] == "runner.succeeded" for event in completed["events"])

        with urlopen(
            f"{base_url}/api/packets/{packet.packet_id}?{query}",
            timeout=20,
        ) as response:
            detail = json.loads(response.read().decode("utf-8"))["packet"]
        assert detail["runner_run"]["status"] == "succeeded"
        assert detail["runner_run"]["remote_execution"] is False

        invalid_timeout = Request(
            f"{base_url}/api/packets/{packet.packet_id}/run?{query}",
            data=json.dumps({"timeout_seconds": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(invalid_timeout, timeout=20)
            raise AssertionError("invalid timeout should fail")
        except HTTPError as exc:
            assert exc.code == 409

        local_packet = create_task_packet(
            repo_path=tmp_path,
            task="Run the local adapter lane.",
            agent_id="local",
            stage="execute",
        )
        wrong_lane = Request(
            f"{base_url}/api/packets/{local_packet.packet_id}/run?{query}",
            data=json.dumps({"timeout_seconds": 10}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(wrong_lane, timeout=20)
            raise AssertionError("non-Codex lane should fail")
        except HTTPError as exc:
            assert exc.code == 409
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_packet_runner_api_launches_hermes_adapter_and_persists_ui_state(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))
    packet = create_task_packet(
        repo_path=tmp_path,
        task="Complete the Hermes API adapter smoke path.",
        agent_id="hermes",
        stage="execute",
        attach_evidence=False,
    )
    assert packet.runner_plan.launch_supported is True

    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    Handler.run_manager = LocalRunManager()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        query = urlencode({"repo": str(tmp_path)})
        with urlopen(f"{base_url}/api/state?{query}", timeout=20) as response:
            runtime = json.loads(response.read().decode("utf-8"))
        hermes_status = next(
            adapter for adapter in runtime["runner_adapters"] if adapter["id"] == "hermes"
        )
        assert hermes_status["available"] is True
        assert hermes_status["remote_execution"] is False
        launch = Request(
            f"{base_url}/api/packets/{packet.packet_id}/run?{query}",
            data=json.dumps({"timeout_seconds": 10}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(launch, timeout=20) as response:
            assert response.status == 201

        deadline = time.monotonic() + 15
        completed = None
        while time.monotonic() < deadline:
            with urlopen(
                f"{base_url}/api/packets/{packet.packet_id}/run?{query}",
                timeout=20,
            ) as response:
                completed = json.loads(response.read().decode("utf-8"))["run"]
            if completed["status"] not in {"starting", "running", "cancelling"}:
                break
            time.sleep(0.05)

        assert completed is not None
        assert completed["status"] == "succeeded"
        assert completed["adapter_id"] == "hermes-local"
        assert completed["last_message"] == "Synthetic Hermes Agent run completed locally."
        assert completed["remote_execution"] is False

        with urlopen(
            f"{base_url}/api/packets/{packet.packet_id}?{query}",
            timeout=20,
        ) as response:
            detail = json.loads(response.read().decode("utf-8"))["packet"]
        assert detail["agent_name"] == "Hermes Agent"
        assert detail["runner_plan"]["mode"] == "local-hermes-one-shot"
        assert detail["runner_run"]["status"] == "succeeded"
        assert detail["attach_evidence"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
