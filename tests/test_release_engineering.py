from pathlib import Path
import re

from hamiltonian import __version__


ROOT = Path(__file__).parents[1]


def test_package_versions_match() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', pyproject, re.MULTILINE)

    assert match
    assert match.group(1) == __version__
    assert 'test = ["pytest==9.0.3"]' in pyproject


def test_ci_uses_pinned_actions_and_read_only_defaults() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "contents: read" in ci
    assert "pull_request_target" not in ci
    assert "persist-credentials: false" in ci
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in ci
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in ci
    assert "actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e" in ci
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in ci
    assert 'python-version: ["3.10", "3.13"]' in ci
    assert "cockpit_browser_smoke.mjs" in ci
    assert "build-windows-app.ps1" in ci


def test_release_publication_requires_manual_boolean() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in release
    assert "default: false" in release
    assert "github.event_name == 'workflow_dispatch' && inputs.publish" in release
    assert "contents: write" in release
    assert "pull_request_target" not in release
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in release


def test_windows_build_writes_reviewable_release_artifacts() -> None:
    build = (ROOT / "scripts" / "build-windows-app.ps1").read_text(encoding="utf-8")

    assert "hamiltonian.desktop-release.v1" in build
    assert "source_commit" in build
    assert "source_dirty" in build
    assert "Compress-Archive" in build
    assert "artifact_sha256" in build
    assert "windows-portable-zip" in build
    assert "signed = $false" in build
