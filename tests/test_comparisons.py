from __future__ import annotations

from dataclasses import asdict
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from hamiltonian.comparisons import (
    COMPARISON_SCHEMA,
    create_result_comparison,
    list_result_comparisons,
)
from hamiltonian.packets import create_task_packet, get_task_packet
from hamiltonian.runners import LocalRunManager, start_packet_run
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)


def run_packet(
    repo: Path,
    manager: LocalRunManager,
    task: str,
    lane_id: str,
) -> dict:
    packet = create_task_packet(repo, task, lane_id, stage="execute")
    start_packet_run(manager, repo, asdict(packet), timeout_seconds=10)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        run = manager.get(Path(packet.packet_dir))
        if run["status"] not in {"starting", "running", "cancelling"}:
            assert run["status"] == "succeeded"
            return get_task_packet(repo, packet.packet_id)
        time.sleep(0.05)
    raise AssertionError("comparison packet did not finish")


def test_result_comparison_persists_receipt_metadata_without_answer_text(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))
    manager = LocalRunManager()
    task = "Compare two local agent responses for the same bounded task."
    codex = run_packet(tmp_path, manager, task, "codex")
    hermes = run_packet(tmp_path, manager, task, "hermes")

    comparison = create_result_comparison(tmp_path, codex["packet_id"], hermes["packet_id"])
    stored_path = Path(comparison["artifact_path"])
    stored_text = stored_path.read_text(encoding="utf-8")

    assert comparison["schema"] == COMPARISON_SCHEMA
    assert comparison["status"] == "complete"
    assert {comparison["primary"]["lane_id"], comparison["secondary"]["lane_id"]} == {
        "codex",
        "hermes",
    }
    assert comparison["result_text_included"] is False
    assert comparison["remote_execution"] is False
    assert comparison["primary"]["result_digest"]
    assert comparison["secondary"]["result_digest"]
    assert "Synthetic Codex run completed locally." not in stored_text
    assert "Synthetic Hermes Agent run completed locally." not in stored_text
    assert str(tmp_path.resolve()) not in stored_text
    assert list_result_comparisons(tmp_path)[0]["comparison_id"] == comparison["comparison_id"]


def test_result_comparison_rejects_mismatched_tasks(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))
    manager = LocalRunManager()
    codex = run_packet(tmp_path, manager, "First bounded task.", "codex")
    hermes = run_packet(tmp_path, manager, "Different bounded task.", "hermes")

    with pytest.raises(ValueError, match="same task"):
        create_result_comparison(tmp_path, codex["packet_id"], hermes["packet_id"])


def test_comparison_api_returns_runtime_answers_but_persists_only_receipts(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setenv("HAMILTONIAN_CODEX_COMMAND", json.dumps(list(fake_codex_command)))
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))
    manager = LocalRunManager()
    task = "Return two comparable local answers."
    codex = run_packet(tmp_path, manager, task, "codex")
    hermes = run_packet(tmp_path, manager, task, "hermes")

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
        request = Request(
            f"{base_url}/api/comparisons",
            data=json.dumps(
                {
                    "repo": str(tmp_path),
                    "primary_packet_id": codex["packet_id"],
                    "secondary_packet_id": hermes["packet_id"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            assert response.status == 201
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["results"]["primary"] == "Synthetic Codex run completed locally."
        assert payload["results"]["secondary"] == "Synthetic Hermes Agent run completed locally."
        assert payload["comparison"]["result_text_included"] is False

        query = urlencode({"repo": str(tmp_path)})
        with urlopen(f"{base_url}/api/comparisons?{query}", timeout=20) as response:
            listed = json.loads(response.read().decode("utf-8"))["comparisons"]
        assert listed[0]["comparison_id"] == payload["comparison"]["comparison_id"]
        stored = Path(listed[0]["artifact_path"]).read_text(encoding="utf-8")
        assert "Synthetic Codex" not in stored
        assert "Synthetic Hermes" not in stored
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
