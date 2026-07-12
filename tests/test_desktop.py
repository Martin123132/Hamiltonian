from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

import pytest

from hamiltonian import __version__
from hamiltonian.desktop import (
    CRASH_SCHEMA,
    DesktopSession,
    SingleInstanceLock,
    desktop_data_dir,
    desktop_launcher_html,
    load_recent_workspaces,
    remember_workspace,
    run_desktop,
    write_desktop_crash_report,
)
from hamiltonian.goals import create_goal_package
from hamiltonian.server import create_cockpit_server


class FakeWebview:
    def __init__(self) -> None:
        self.window_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.start_calls: list[dict[str, object]] = []

    def create_window(self, *args, **kwargs) -> object:
        self.window_calls.append((args, kwargs))
        return object()

    def start(self, **kwargs) -> None:
        self.start_calls.append(kwargs)


class CrashingWebview(FakeWebview):
    def start(self, **kwargs) -> None:
        super().start(**kwargs)
        raise RuntimeError("Failed at D:\\private\\workspace with SECRET=do-not-store")


def test_desktop_data_stays_in_repo_local_store_by_default(tmp_path: Path) -> None:
    data_dir = desktop_data_dir(tmp_path)

    assert data_dir == tmp_path / ".hamiltonian" / "desktop"
    assert data_dir.is_dir()


def test_desktop_runs_strict_local_server_and_closes_it_with_window(tmp_path: Path) -> None:
    fake_webview = FakeWebview()
    data_dir = tmp_path / "desktop-data"

    result = run_desktop(
        tmp_path,
        data_dir=data_dir,
        webview_module=fake_webview,
        single_instance=False,
    )

    assert result.repo == str(tmp_path.resolve())
    assert result.data_dir == str(data_dir.resolve())
    assert result.url.startswith("http://127.0.0.1:")
    assert result.remote_execution is False
    assert result.closed_cleanly is True
    assert fake_webview.window_calls[0][0][0] == f"Hamiltonian | {tmp_path.name}"
    assert fake_webview.window_calls[0][1]["url"] == result.url
    assert fake_webview.window_calls[0][1]["js_api"].repo == tmp_path.resolve()
    assert fake_webview.start_calls[0]["private_mode"] is True
    assert fake_webview.start_calls[0]["storage_path"] == str(data_dir.resolve() / "webview")
    if os.name == "nt":
        assert fake_webview.start_calls[0]["gui"] == "edgechromium"


def test_desktop_without_repo_starts_branded_launcher_without_server(tmp_path: Path) -> None:
    fake_webview = FakeWebview()

    result = run_desktop(
        None,
        data_dir=tmp_path / "desktop-data",
        webview_module=fake_webview,
        single_instance=False,
    )

    assert result.repo is None
    assert result.url is None
    assert result.closed_cleanly is True
    assert fake_webview.window_calls[0][0] == ("Hamiltonian",)
    assert "Choose a workspace" in fake_webview.window_calls[0][1]["html"]
    assert "url" not in fake_webview.window_calls[0][1]


def test_recent_workspaces_are_local_deduplicated_and_drop_missing_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    remember_workspace(data_dir, first)
    remember_workspace(data_dir, second)
    remember_workspace(data_dir, first)
    second.rmdir()

    recent = load_recent_workspaces(data_dir)

    assert recent == [
        {
            "path": str(first.resolve()),
            "name": "first",
            "last_opened": recent[0]["last_opened"],
            "goal_summary": {
                "total": 0,
                "ready_for_review": 0,
                "needs_correction": 0,
                "complete": 0,
            },
        }
    ]


def test_launcher_renders_recent_workspace_without_unescaped_html(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    repo = tmp_path / "repo-name"
    repo.mkdir()
    remember_workspace(data_dir, repo)

    html = desktop_launcher_html(data_dir)

    assert "Choose a workspace" in html
    assert "Remote execution off" in html
    assert f"Version {__version__}" in html
    assert str(repo.resolve()).replace("\\", "\\\\") in html
    assert "__HAMILTONIAN_RECENTS__" not in html


def test_launcher_surfaces_workspace_goal_ready_for_review(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    goal = create_goal_package(repo, "maintenance", "Repository health: **B**")
    receipt = repo / ".hamiltonian" / "goals" / goal.goal_id / "return.json"
    receipt.write_text(
        json.dumps(
            {
                "goal_id": goal.goal_id,
                "status": "ready",
                "summary": "Done",
                "files_changed": [],
                "tests": [],
                "branch": "main",
                "commit": "abc",
                "pushed": False,
                "remaining_work": "None",
            }
        ),
        encoding="utf-8",
    )
    remember_workspace(data_dir, repo)

    html = desktop_launcher_html(data_dir)

    assert '"ready_for_review": 1' in html
    assert "goals ready for review" in html


def test_desktop_session_locks_to_first_activated_workspace(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    session = DesktopSession(data_dir)
    try:
        opened = session.activate_workspace(first)
        rejected = session.open_workspace(str(second))

        assert opened["ok"] is True
        assert opened["url"].startswith("http://127.0.0.1:")
        assert rejected["ok"] is False
        assert "already locked" in rejected["error"]
    finally:
        assert session.close() is True


def test_crash_report_is_sanitized_and_remains_in_local_data_dir(tmp_path: Path) -> None:
    error = RuntimeError("Failed at D:\\private\\workspace with TOKEN=do-not-store")

    path = write_desktop_crash_report(tmp_path, error, tmp_path / "private-repo")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == CRASH_SCHEMA
    assert payload["sanitized"] is True
    assert payload["local_only"] is True
    assert payload["remote_execution"] is False
    assert payload["workspace_name"] == "private-repo"
    assert "do-not-store" not in path.read_text(encoding="utf-8")
    assert "D:\\private" not in path.read_text(encoding="utf-8")
    assert path.parent == tmp_path / "crashes"


def test_desktop_runtime_failure_writes_sanitized_crash_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "desktop-data"

    with pytest.raises(RuntimeError, match="Failed at"):
        run_desktop(
            tmp_path,
            data_dir=data_dir,
            webview_module=CrashingWebview(),
            single_instance=False,
        )

    reports = list((data_dir / "crashes").glob("crash-*.json"))
    assert len(reports) == 1
    text = reports[0].read_text(encoding="utf-8")
    assert "do-not-store" not in text
    assert "D:\\private" not in text


def test_desktop_server_rejects_a_different_workspace(tmp_path: Path) -> None:
    locked_repo = tmp_path / "locked"
    other_repo = tmp_path / "other"
    locked_repo.mkdir()
    other_repo.mkdir()
    server: ThreadingHTTPServer = create_cockpit_server(
        locked_repo,
        host="127.0.0.1",
        port=0,
        strict_repo=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        with urlopen(
            f"{base_url}/api/state?{urlencode({'repo': str(locked_repo)})}",
            timeout=10,
        ) as response:
            assert response.status == 200

        with urlopen(f"{base_url}/api/health", timeout=10) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["version"] == __version__
        assert health["surface"] == "desktop"
        assert health["workspace_locked"] is True
        assert health["remote_execution"] is False

        try:
            urlopen(
                f"{base_url}/api/state?{urlencode({'repo': str(other_repo)})}",
                timeout=10,
            )
        except HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 400
            assert "locked to" in payload["error"]
        else:
            raise AssertionError("strict desktop server accepted a different workspace")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex behavior")
def test_single_instance_lock_rejects_a_second_desktop_process() -> None:
    name = f"Local\\HamiltonianDesktopTest-{uuid4().hex}"
    first = SingleInstanceLock(name)
    second = SingleInstanceLock(name)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already open"):
            second.acquire()
    finally:
        first.release()

    replacement = SingleInstanceLock(name)
    replacement.acquire()
    replacement.release()
