from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from hamiltonian.goals import (
    GOAL_SCHEMA,
    create_corrective_goal,
    create_goal_package,
    goal_workspace_summary,
    inspect_goal_receipt,
    list_goal_packages,
    open_codex_workspace,
    preview_goal_package,
    save_goal_review,
)
from hamiltonian.runners import AdapterProbe
from hamiltonian.server import CockpitHandler


ROOT = Path(__file__).parents[1]


def init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "hamiltonian@example.test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Hamiltonian Test"], cwd=path, check=True)
    (path / "README.md").write_text("# Test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "initial"], cwd=path, check=True)


REPORT = """Repository health: **B — strong core.**

### Main findings

| Severity | Finding |
|---|---|
| Medium | Windows release drift comparison is incorrect. |
| Medium | Schema validation ignores maxItems. |
"""


def write_receipt(repo: Path, goal_id: str, summary: str = "Completed the requested work.") -> None:
    target = repo / ".hamiltonian" / "goals" / goal_id / "return.json"
    target.write_text(
        json.dumps(
            {
                "goal_id": goal_id,
                "status": "ready-for-review",
                "summary": summary,
                "files_changed": ["src/example.py"],
                "tests": ["pytest: passed"],
                "branch": "main",
                "commit": "abc123",
                "pushed": False,
                "remaining_work": "None",
            }
        ),
        encoding="utf-8",
    )


def test_maintenance_goal_raises_one_grade_and_persists_local_contract(tmp_path: Path) -> None:
    init_git_repo(tmp_path)

    package = create_goal_package(
        repo_path=tmp_path,
        goal_type="maintenance",
        source_report=REPORT,
        source_packet_id="packet-1",
    )

    assert package.schema == GOAL_SCHEMA
    assert package.status == "saved"
    assert package.source_grade == "B"
    assert package.target_grade == "B+"
    assert package.baseline_commit
    assert package.remote_execution is False
    assert package.pushed is False
    assert "Raise" in package.objective
    assert "HAMILTONIAN READY FOR REVIEW" in package.goal_markdown
    assert "Do not push" in package.goal_markdown
    assert "## Workspace Lock" in package.goal_markdown
    assert f"Expected workspace: `{tmp_path.resolve()}`" in package.goal_markdown
    assert "If the paths do not match, stop immediately" in package.goal_markdown
    assert package.goal_path and Path(package.goal_path).exists()
    assert package.source_report_path and Path(package.source_report_path).exists()
    assert package.return_path.endswith("return.json")
    stored = json.loads((Path(package.goal_path).parent / "goal.json").read_text(encoding="utf-8"))
    assert stored["goal_id"] == package.goal_id
    assert stored["source_packet_id"] == "packet-1"
    assert ".hamiltonian/" in (tmp_path / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert [item["goal_id"] for item in list_goal_packages(tmp_path)] == [package.goal_id]


def test_expansion_goal_requires_capability_and_keeps_health_report_as_context(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    with pytest.raises(ValueError, match="capability"):
        preview_goal_package(tmp_path, "expansion", REPORT)

    package = preview_goal_package(
        repo_path=tmp_path,
        goal_type="expansion",
        source_report=REPORT,
        expansion_request="Users can compare two benchmark runs side by side.",
    )

    assert package.status == "preview"
    assert package.expansion_request == "Users can compare two benchmark runs side by side."
    assert "bounded production slice" in package.goal_markdown
    assert "Windows release drift" in package.goal_markdown
    assert "Health target" not in package.goal_markdown
    assert "preserve the current baseline" in package.goal_markdown
    assert package.goal_path is None


def test_goal_preview_handles_uncommitted_repo_and_bounds_saved_report(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    oversized_report = REPORT + ("finding detail\n" * 5_000)

    package = create_goal_package(tmp_path, "maintenance", oversized_report)

    assert package.baseline_commit is None
    assert "fatal:" not in package.goal_markdown
    assert package.source_report_path
    saved_report = Path(package.source_report_path).read_text(encoding="utf-8")
    assert saved_report.endswith("[Report truncated by Hamiltonian.]\n")
    assert len(saved_report) < len(oversized_report)


def test_receipt_review_and_corrective_goal_lifecycle(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    original = create_goal_package(tmp_path, "maintenance", REPORT)

    assert list_goal_packages(tmp_path)[0]["lifecycle_status"] == "awaiting-codex"
    write_receipt(tmp_path, original.goal_id, "Fixed the trust boundary at D:\\private\\repo.")
    receipt = inspect_goal_receipt(tmp_path, original.goal_id)
    assert receipt["valid"] is True
    assert "D:\\private" not in receipt["summary"]
    assert list_goal_packages(tmp_path)[0]["lifecycle_status"] == "ready-for-review"

    review = save_goal_review(
        tmp_path,
        original.goal_id,
        "## Verdict\n\n**Goal incomplete.**\n\nMaintenance health grade: **B**\n\nOne trust defect remains.",
        source_packet_id="review-packet",
    )
    assert review["verdict"] == "incomplete"
    assert review["assigned_grade"] == "B"
    assert review["summary"] == "Goal incomplete."
    assert list_goal_packages(tmp_path)[0]["lifecycle_status"] == "needs-correction"

    corrective = create_corrective_goal(tmp_path, original.goal_id)
    assert corrective.goal_type == "corrective"
    assert corrective.parent_goal_id == original.goal_id
    assert corrective.lineage_root_id == original.goal_id
    assert corrective.correction_index == 1
    goals = {goal["goal_id"]: goal for goal in list_goal_packages(tmp_path)}
    assert goals[original.goal_id]["lifecycle_status"] == "correction-in-progress"
    assert goals[original.goal_id]["child_goal_ids"] == [corrective.goal_id]

    write_receipt(tmp_path, corrective.goal_id)
    save_goal_review(
        tmp_path,
        corrective.goal_id,
        "## Verdict\n\n**Goal complete.**\n\nMaintenance health grade: **B+**",
    )
    goals = {goal["goal_id"]: goal for goal in list_goal_packages(tmp_path)}
    assert goals[corrective.goal_id]["lifecycle_status"] == "complete"
    assert goals[original.goal_id]["lifecycle_status"] == "corrected"
    assert goals[corrective.goal_id]["grade_movement"] == "B to B+"
    assert goal_workspace_summary(tmp_path) == {
        "total": 2,
        "ready_for_review": 0,
        "needs_correction": 0,
        "complete": 2,
    }

    with pytest.raises(ValueError, match="already has a corrective"):
        create_corrective_goal(tmp_path, original.goal_id)


def test_invalid_receipt_is_reported_without_exposing_payload(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    package = create_goal_package(tmp_path, "maintenance", REPORT)
    target = tmp_path / ".hamiltonian" / "goals" / package.goal_id / "return.json"
    target.write_text('{"goal_id": "wrong", "secret": "do-not-display"}', encoding="utf-8")

    receipt = inspect_goal_receipt(tmp_path, package.goal_id)

    assert receipt["status"] == "invalid"
    assert receipt["valid"] is False
    assert "do-not-display" not in json.dumps(receipt)
    assert list_goal_packages(tmp_path)[0]["lifecycle_status"] == "receipt-invalid"


def test_open_codex_workspace_uses_app_command_without_remote_execution(tmp_path: Path, monkeypatch) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setattr(
        "hamiltonian.goals.probe_codex_command",
        lambda _repo: AdapterProbe(True, ("codex-test",), "codex-cli test"),
    )
    captured: dict[str, object] = {}

    class Process:
        pid = 4321

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("hamiltonian.goals.subprocess.Popen", fake_popen)

    result = open_codex_workspace(tmp_path)

    assert captured["command"] == ["codex-test", "app", str(tmp_path.resolve())]
    assert result["opened"] is True
    assert result["process_id"] == 4321
    assert result["remote_execution"] is False


def test_goal_preview_save_and_open_api(tmp_path: Path, monkeypatch) -> None:
    init_git_repo(tmp_path)

    class Handler(CockpitHandler):
        pass

    Handler.repo = tmp_path
    Handler.static_root = ROOT / "src" / "hamiltonian" / "web"
    monkeypatch.setattr(
        "hamiltonian.server.open_codex_workspace",
        lambda repo: {
            "opened": True,
            "repo": str(repo.resolve()),
            "repo_name": repo.resolve().name,
            "process_id": 99,
            "command": "codex app <workspace>",
            "remote_execution": False,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        preview_request = Request(
            f"{base_url}/api/goals/preview",
            data=json.dumps(
                {
                    "repo": str(tmp_path),
                    "goal_type": "maintenance",
                    "source_report": REPORT,
                    "source_packet_id": "packet-api",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(preview_request, timeout=20) as response:
            preview = json.loads(response.read().decode("utf-8"))["goal"]
        assert preview["status"] == "preview"
        assert preview["target_grade"] == "B+"

        save_request = Request(
            f"{base_url}/api/goals",
            data=json.dumps(
                {
                    "repo": str(tmp_path),
                    "goal_type": "maintenance",
                    "source_report": REPORT,
                    "source_packet_id": "packet-api",
                    "goal_id": preview["goal_id"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(save_request, timeout=20) as response:
            saved = json.loads(response.read().decode("utf-8"))["goal"]
        assert saved["status"] == "saved"
        assert saved["goal_id"] == preview["goal_id"]

        query = urlencode({"repo": str(tmp_path)})
        with urlopen(f"{base_url}/api/goals?{query}", timeout=20) as response:
            goals = json.loads(response.read().decode("utf-8"))["goals"]
        assert goals[0]["goal_id"] == preview["goal_id"]

        write_receipt(tmp_path, saved["goal_id"])
        with urlopen(f"{base_url}/api/goals?{query}", timeout=20) as response:
            goals = json.loads(response.read().decode("utf-8"))["goals"]
        assert goals[0]["lifecycle_status"] == "ready-for-review"

        review_request = Request(
            f"{base_url}/api/goals/{saved['goal_id']}/review",
            data=json.dumps(
                {
                    "repo": str(tmp_path),
                    "report": "## Verdict\n\n**Goal incomplete.**\n\nMaintenance health grade: **B**",
                    "source_packet_id": "review-api",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(review_request, timeout=20) as response:
            reviewed = json.loads(response.read().decode("utf-8"))
        assert reviewed["review"]["verdict"] == "incomplete"
        assert reviewed["goals"][0]["lifecycle_status"] == "needs-correction"

        corrective_request = Request(
            f"{base_url}/api/goals/{saved['goal_id']}/corrective",
            data=json.dumps({"repo": str(tmp_path)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(corrective_request, timeout=20) as response:
            corrective = json.loads(response.read().decode("utf-8"))["goal"]
        assert corrective["goal_type"] == "corrective"
        assert corrective["parent_goal_id"] == saved["goal_id"]

        open_request = Request(
            f"{base_url}/api/codex/open",
            data=json.dumps({"repo": str(tmp_path)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(open_request, timeout=20) as response:
            opened = json.loads(response.read().decode("utf-8"))
        assert opened["opened"] is True
        assert opened["remote_execution"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
