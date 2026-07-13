from pathlib import Path
import re
import tomllib

from hamiltonian import __version__


ROOT = Path(__file__).parents[1]


def test_package_versions_match() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    metadata = tomllib.loads(pyproject)
    match = re.search(r'^version = "([0-9]+\.[0-9]+\.[0-9]+)"$', pyproject, re.MULTILINE)
    test_dependencies = metadata["project"]["optional-dependencies"]["test"]

    assert match
    assert match.group(1) == __version__
    assert len(test_dependencies) == 1
    assert re.fullmatch(r"pytest==[0-9]+\.[0-9]+\.[0-9]+", test_dependencies[0])
    assert 'license = { file = "LICENSE" }' in pyproject
    assert 'Repository = "https://github.com/Martin123132/Hamiltonian"' in pyproject


def test_publication_governance_matches_house_license() -> None:
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    assert "PolyForm Noncommercial License 1.0.0" in license_text
    assert "Copyright (c) 2026 TWO HANDS NETWORK LTD." in license_text
    assert "Hamiltonian is source-available for personal and non-commercial use" in license_text
    assert "commercial AI coding/agent products" in license_text
    assert "glyn@twohandsnetwork.co.uk" in license_text
    assert "public source-available software, not open-source software" in notice
    assert "training, fine-tuning, distilling" in notice
    assert "relicense your contribution" in contributing
    assert "GitHub private vulnerability reporting" in security
    assert "Do not open a public issue" in security


def test_public_surfaces_do_not_expose_developer_specific_paths() -> None:
    public_paths = (
        ROOT / "README.md",
        ROOT / "scripts" / "build-windows-app.ps1",
        ROOT / "scripts" / "cockpit_browser_smoke.mjs",
        ROOT / "src" / "hamiltonian" / "desktop.py",
    )

    for path in public_paths:
        assert "D:\\Codex" not in path.read_text(encoding="utf-8"), path


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
    assert 'PolyForm-Noncommercial-1.0.0' in ci
    assert '@("LICENSE", "NOTICE.md", "README.md")' in ci


def test_release_publication_requires_manual_boolean() -> None:
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in release
    assert "default: false" in release
    assert "github.event_name == 'workflow_dispatch' && inputs.publish" in release
    assert "contents: write" in release
    assert "pull_request_target" not in release
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c" in release
    assert 'PolyForm-Noncommercial-1.0.0' in release
    assert '@("LICENSE", "NOTICE.md", "README.md")' in release


def test_windows_build_writes_reviewable_release_artifacts() -> None:
    build = (ROOT / "scripts" / "build-windows-app.ps1").read_text(encoding="utf-8")

    assert "hamiltonian.desktop-release.v1" in build
    assert "source_commit" in build
    assert "source_dirty" in build
    assert "System.IO.Compression.ZipFile" in build
    assert "Compress-Archive" not in build
    assert '"D:\\Hamiltonian"' in build
    assert '@("LICENSE", "NOTICE.md", "README.md")' in build
    assert "source_available = $true" in build
    assert 'license = "PolyForm-Noncommercial-1.0.0"' in build
    assert 'license_file = "LICENSE"' in build
    assert 'notice_file = "NOTICE.md"' in build
    assert "artifact_sha256" in build
    assert "windows-portable-zip" in build
    assert "signed = $false" in build
