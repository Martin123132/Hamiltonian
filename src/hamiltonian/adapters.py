from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .core import ensure_repo, is_git_repo, write_text
from .integrations import IntegrationStatus


EXCLUDED_DIRS = {
    ".git",
    ".hamiltonian",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}
SENSITIVE_NAME_MARKERS = (
    ".env",
    "secret",
    "token",
    "credential",
    "password",
    "private",
    "key",
)


@dataclass(frozen=True)
class RepoMoriMemoryResult:
    status: str
    mode: str
    summary: str
    integration: str
    available: bool
    artifact_path: str


def integration_available(integrations: list[IntegrationStatus], name: str) -> bool:
    return any(item.name == name and item.available for item in integrations)


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in SENSITIVE_NAME_MARKERS)


def sanitized_repo_snapshot(repo: Path, max_files: int = 500) -> dict[str, object]:
    repo = ensure_repo(repo)
    extension_counts: Counter[str] = Counter()
    files_seen = 0
    files_sampled = 0
    dirs_seen = 0
    skipped_sensitive = 0

    for root, dirs, files in os.walk(repo):
        dirs[:] = [
            dirname
            for dirname in dirs
            if dirname not in EXCLUDED_DIRS
            and not dirname.startswith(".")
            and not _is_sensitive_name(dirname)
        ]
        dirs_seen += len(dirs)
        for filename in files:
            files_seen += 1
            if files_sampled >= max_files:
                continue
            if filename.startswith(".") or _is_sensitive_name(filename):
                skipped_sensitive += 1
                continue
            suffix = Path(filename).suffix.lower() or "[no-extension]"
            extension_counts[suffix] += 1
            files_sampled += 1

    return {
        "schema": "hamiltonian.repomori-memory.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_name": repo.name,
        "git_available": is_git_repo(repo),
        "content_included": False,
        "path_names_included": False,
        "remote_calls": False,
        "files_seen": files_seen,
        "files_sampled": files_sampled,
        "dirs_seen": dirs_seen,
        "skipped_sensitive_names": skipped_sensitive,
        "truncated": files_seen > max_files,
        "extension_counts": dict(sorted(extension_counts.items())),
        "privacy_note": "Sanitized fallback metadata only; no file contents, secrets, URLs, or private path names are stored.",
    }


def run_repomori_memory_adapter(
    repo_path: Path,
    packet_dir: Path,
    integrations: list[IntegrationStatus],
) -> RepoMoriMemoryResult:
    repo = ensure_repo(repo_path)
    available = integration_available(integrations, "RepoMori")
    memory_dir = packet_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = memory_dir / "repomori-memory-snapshot.json"
    snapshot = sanitized_repo_snapshot(repo)
    snapshot["integration"] = "RepoMori"
    snapshot["adapter_available"] = available
    snapshot["external_tool_executed"] = False
    write_text(artifact_path, json.dumps(snapshot, indent=2))

    if available:
        return RepoMoriMemoryResult(
            status="checked",
            mode="repomori-adapter-ready",
            summary="RepoMori is available; Hamiltonian checked the adapter boundary and wrote a sanitized local memory snapshot without executing the tool.",
            integration="RepoMori",
            available=True,
            artifact_path=str(artifact_path),
        )

    return RepoMoriMemoryResult(
        status="checked",
        mode="repomori-synthetic-fallback",
        summary="RepoMori is unavailable; Hamiltonian used the adapter boundary with sanitized fallback memory metadata.",
        integration="RepoMori",
        available=False,
        artifact_path=str(artifact_path),
    )
