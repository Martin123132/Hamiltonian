from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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
)


@lru_cache(maxsize=16)
def _cached_detect_integrations(repo_key: str) -> tuple[IntegrationStatus, ...]:
    statuses: list[IntegrationStatus] = []
    repo = Path(repo_key)
    for name, binary, probe in INTEGRATIONS:
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
        statuses.append(
            IntegrationStatus(
                name=name,
                command=binary,
                available=True,
                detail=_probe(probe, repo),
            )
        )
    return tuple(statuses)


def _probe(command: tuple[str, ...], cwd: Path) -> str:
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
        return f"probe failed: {exc}"
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    if output:
        return output[0][:180]
    return f"exit {proc.returncode}"


def detect_integrations(repo: Path) -> list[IntegrationStatus]:
    return list(_cached_detect_integrations(str(repo.resolve())))


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
