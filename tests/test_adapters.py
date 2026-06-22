import json
from pathlib import Path

from hamiltonian.adapters import run_repomori_memory_adapter, sanitized_repo_snapshot
from hamiltonian.integrations import IntegrationStatus


def test_repomori_adapter_success_marks_boundary_without_execution(tmp_path: Path) -> None:
    integration = IntegrationStatus(
        name="RepoMori",
        command="repomori",
        available=True,
        detail="test double",
    )

    result = run_repomori_memory_adapter(
        repo_path=tmp_path,
        packet_dir=tmp_path / "packet",
        integrations=[integration],
    )

    assert result.status == "checked"
    assert result.mode == "repomori-adapter-ready"
    artifact = json.loads(Path(result.artifact_path).read_text(encoding="utf-8"))
    assert artifact["adapter_available"] is True
    assert artifact["external_tool_executed"] is False
    assert artifact["content_included"] is False


def test_repomori_adapter_unavailable_writes_sanitized_fallback(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('do not include me')", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=do-not-include", encoding="utf-8")
    (tmp_path / "secret-plan.md").write_text("do not include", encoding="utf-8")

    result = run_repomori_memory_adapter(
        repo_path=tmp_path,
        packet_dir=tmp_path / "packet",
        integrations=[],
    )

    assert result.status == "checked"
    assert result.mode == "repomori-synthetic-fallback"
    artifact_text = Path(result.artifact_path).read_text(encoding="utf-8")
    artifact = json.loads(artifact_text)
    assert artifact["adapter_available"] is False
    assert artifact["external_tool_executed"] is False
    assert artifact["content_included"] is False
    assert artifact["path_names_included"] is False
    assert ".py" in artifact["extension_counts"]
    assert "TOKEN" not in artifact_text
    assert "secret-plan" not in artifact_text


def test_sanitized_repo_snapshot_does_not_include_contents_or_paths(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("private roadmap", encoding="utf-8")

    snapshot = sanitized_repo_snapshot(tmp_path)

    dumped = json.dumps(snapshot)
    assert snapshot["content_included"] is False
    assert snapshot["path_names_included"] is False
    assert "private roadmap" not in dumped
    assert "notes.md" not in dumped
