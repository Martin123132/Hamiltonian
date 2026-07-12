from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path


@dataclass(frozen=True)
class IntegrationStatus:
    name: str
    command: str
    available: bool
    detail: str


INTEGRATIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("AgentLedger", "agentledger", ("agentledger", "--version")),
    ("RepoMori", "repomori", ("repomori", "--help")),
    ("Memento Mori Jester", "jester", ("jester", "--version")),
    ("Tokometer", "tokometer", ("tokometer", "--version")),
    ("TokenSquash", "tokensquash", ("tokensquash", "--version")),
    ("Sentinel Manifold", "sentinel-manifold", ("sentinel-manifold", "--help")),
    ("Hermes Agent", "hermes", ("hermes", "--version")),
)


@lru_cache(maxsize=16)
def _cached_detect_integrations(repo_key: str, hermes_override: str) -> tuple[IntegrationStatus, ...]:
    statuses: list[IntegrationStatus] = []
    repo = Path(repo_key)
    for name, binary, probe in INTEGRATIONS:
        if binary == "hermes" and hermes_override:
            try:
                prefix = _parse_command_override(hermes_override)
            except ValueError as exc:
                statuses.append(IntegrationStatus(name, binary, False, str(exc)))
                continue
            detail, available = _probe((*prefix, "--version"), repo, include_status=True)
            statuses.append(IntegrationStatus(name, binary, available, detail))
            continue
        path = shutil.which(binary)
        if not path:
            statuses.append(
                IntegrationStatus(
                    name=name,
                    command=binary,
                    available=False,
                    detail="not installed or not on PATH",
                )
            )
            continue
        if binary == "hermes":
            detail, available = _probe((path, "--version"), repo, include_status=True)
            statuses.append(IntegrationStatus(name, binary, available, detail))
            continue
        statuses.append(
            IntegrationStatus(
                name=name,
                command=binary,
                available=True,
                detail=_probe(probe, repo),
            )
        )
    return tuple(statuses)


def _parse_command_override(configured: str) -> tuple[str, ...]:
    if configured.startswith("["):
        try:
            value = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise ValueError("Hermes command override is not valid JSON") from exc
        if not isinstance(value, list) or not value or not all(
            isinstance(item, str) and item for item in value
        ):
            raise ValueError("Hermes command override must be a non-empty string array")
        return tuple(value)
    if Path(configured).exists():
        return (configured,)
    parsed = tuple(shlex.split(configured, posix=os.name != "nt"))
    if not parsed:
        raise ValueError("Hermes command override is empty")
    return parsed


def _probe(
    command: tuple[str, ...],
    cwd: Path,
    include_status: bool = False,
) -> str | tuple[str, bool]:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - platform/proc edge
        detail = f"probe failed: {exc}"
        return (detail, False) if include_status else detail
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    if output:
        detail = output[0][:180]
    else:
        detail = f"exit {proc.returncode}"
    return (detail, proc.returncode == 0) if include_status else detail


def detect_integrations(repo: Path) -> list[IntegrationStatus]:
    return list(
        _cached_detect_integrations(
            str(repo.resolve()),
            os.environ.get("HAMILTONIAN_HERMES_COMMAND", "").strip(),
        )
    )


def run_jester_command_check(repo: Path, command_text: str) -> tuple[str, str] | None:
    if not shutil.which("jester"):
        return None
    proc = subprocess.run(
        ("jester", "command", command_text),
        cwd=str(repo),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    return proc.stdout, proc.stderr
