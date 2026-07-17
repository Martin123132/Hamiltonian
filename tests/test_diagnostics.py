from __future__ import annotations

from dataclasses import dataclass
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from urllib.request import Request, urlopen

from hamiltonian.diagnostics import (
    DIAGNOSTICS_SCHEMA,
    build_sanitized_diagnostics,
    export_sanitized_diagnostics,
)
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]


@dataclass(frozen=True)
class FakeAdapter:
    id: str
    name: str
    available: bool
    mode: str
    local_execution: bool
    remote_execution: bool
    detail: str


@dataclass(frozen=True)
class FakeIntegration:
    name: str
    available: bool
    detail: str


def fake_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        git_available=True,
        git_status=" M private-file.txt",
        runner_adapters=[
            FakeAdapter(
                id="codex",
                name="Codex",
                available=True,
                mode="local-codex",
                local_execution=True,
                remote_execution=False,
                detail="private-adapter-output-do-not-export D:\\private\\repo",
            )
        ],
        integrations=[
            FakeIntegration(
                name="RepoMori",
                available=False,
                detail="private-integration-output-do-not-export",
            )
        ],
        recent_packets=[{"stage": "execute", "task": "private task"}, {"stage": "execute"}],
    )


def test_diagnostics_payload_omits_paths_tasks_and_adapter_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("hamiltonian.diagnostics.build_runtime_state", lambda _repo: fake_runtime())
    monkeypatch.setattr(
        "hamiltonian.diagnostics.goal_workspace_summary",
        lambda _repo: {"total": 2, "ready_for_review": 1, "needs_correction": 0, "complete": 1},
    )

    payload = build_sanitized_diagnostics(tmp_path)
    encoded = json.dumps(payload)

    assert payload["schema"] == DIAGNOSTICS_SCHEMA
    assert payload["runtime"] == {
        "surface": "local",
        "remote_execution": False,
        "workspace_paths_included": False,
        "adapter_output_included": False,
    }
    assert payload["packets"] == {"total": 2, "by_stage": {"execute": 2}}
    assert str(tmp_path) not in encoded
    assert "private task" not in encoded
    assert "do-not-export" not in encoded


def test_diagnostics_export_stays_inside_workspace_local_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("hamiltonian.diagnostics.build_runtime_state", lambda _repo: fake_runtime())
    monkeypatch.setattr(
        "hamiltonian.diagnostics.goal_workspace_summary",
        lambda _repo: {"total": 0, "ready_for_review": 0, "needs_correction": 0, "complete": 0},
    )

    exported = export_sanitized_diagnostics(tmp_path)
    path = Path(exported["path"])
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.parent == tmp_path / ".hamiltonian" / "diagnostics"
    assert exported["sanitized"] is True
    assert exported["local_only"] is True
    assert exported["remote_execution"] is False
    assert payload["schema"] == DIAGNOSTICS_SCHEMA
    assert payload["sanitized"] is True


def test_diagnostics_export_api_is_explicit_and_local(tmp_path: Path, monkeypatch) -> None:
    captured: list[Path] = []

    def fake_export(repo: Path) -> dict[str, object]:
        captured.append(repo)
        return {
            "filename": "hamiltonian-diagnostics-test.json",
            "path": str(repo / ".hamiltonian" / "diagnostics" / "hamiltonian-diagnostics-test.json"),
            "schema": DIAGNOSTICS_SCHEMA,
            "sanitized": True,
            "local_only": True,
            "remote_execution": False,
        }

    monkeypatch.setattr("hamiltonian.server.export_sanitized_diagnostics", fake_export)

    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    Handler.strict_repo = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/diagnostics/export",
            data=json.dumps({"repo": str(tmp_path)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert response.status == 201
        assert captured == [tmp_path.resolve()]
        assert body["export"]["sanitized"] is True
        assert body["export"]["remote_execution"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
