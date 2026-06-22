from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .integrations import detect_integrations, run_jester_command_check


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int | None
    stdout_path: str
    stderr_path: str
    timed_out: bool
    duration_seconds: float


@dataclass(frozen=True)
class ControlRun:
    run_id: str
    repo: str
    out_dir: str
    verdict: str
    warnings: list[str]
    command_result: CommandResult | None
    integrations: list[dict[str, Any]]
    artifacts: dict[str, str]


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_repo(path: Path) -> Path:
    repo = path.resolve()
    if not repo.exists():
        raise FileNotFoundError(f"repo path does not exist: {repo}")
    return repo


def run_capture(command: tuple[str, ...], cwd: Path, timeout: int = 20) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return f"{command[0]} failed: {exc}\n"
    return proc.stdout or ""


def is_git_repo(path: Path) -> bool:
    proc = subprocess.run(
        ("git", "rev-parse", "--is-inside-work-tree"),
        cwd=str(path),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_command(command: list[str], repo: Path, artifacts_dir: Path, timeout: int) -> CommandResult:
    stdout_path = artifacts_dir / "command.stdout.txt"
    stderr_path = artifacts_dir / "command.stderr.txt"
    started = datetime.now(timezone.utc)
    timed_out = False
    returncode: int | None
    try:
        proc = subprocess.run(
            command,
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        returncode = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr += f"\nTimed out after {timeout} seconds.\n"
    finished = datetime.now(timezone.utc)
    write_text(stdout_path, stdout or "")
    write_text(stderr_path, stderr or "")
    return CommandResult(
        command=command,
        returncode=returncode,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        timed_out=timed_out,
        duration_seconds=(finished - started).total_seconds(),
    )


def agentledger_command(command: list[str], repo: Path, out_dir: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "agentledger",
        "run",
        "--repo",
        str(repo),
        "--out",
        str(out_dir / "agentledger"),
        "--",
        *command,
    ]


def build_report(run: ControlRun) -> str:
    result = run.command_result
    lines = [
        "# Hamiltonian Report",
        "",
        f"- Run: `{run.run_id}`",
        f"- Repo: `{run.repo}`",
        f"- Verdict: **{run.verdict.upper()}**",
        "",
        "## Command",
    ]
    if result is None:
        lines.append("No command executed.")
    else:
        lines.extend(
            [
                f"- Command: `{' '.join(result.command)}`",
                f"- Return code: `{result.returncode}`",
                f"- Timed out: `{result.timed_out}`",
                f"- Duration seconds: `{result.duration_seconds:.2f}`",
            ]
        )
    lines.extend(["", "## Warnings"])
    if run.warnings:
        lines.extend(f"- {warning}" for warning in run.warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Integrations"])
    for item in run.integrations:
        state = "available" if item["available"] else "missing"
        lines.append(f"- {item['name']}: {state} - {item['detail']}")
    lines.extend(["", "## Artifacts"])
    for name, path in run.artifacts.items():
        lines.append(f"- {name}: `{path}`")
    lines.extend(
        [
            "",
            "## Product Note",
            "",
            "This packet is the first proof of Hamiltonian: flight software for agentic systems.",
            "",
        ]
    )
    return "\n".join(lines)


def control_run(
    repo_path: Path,
    command: list[str] | None,
    out_root: Path | None = None,
    timeout: int = 900,
    respect_jester_blocks: bool = True,
    runner: str = "direct",
) -> ControlRun:
    repo = ensure_repo(repo_path)
    run_id = utc_run_id()
    root = (out_root or (repo / ".hamiltonian" / "runs")).resolve()
    out_dir = root / run_id
    artifacts_dir = out_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    artifacts: dict[str, str] = {}
    git_available = is_git_repo(repo)
    if git_available:
        before_path = artifacts_dir / "git-status-before.txt"
        write_text(before_path, run_capture(("git", "status", "--short"), repo))
        artifacts["git_status_before"] = str(before_path)

    integrations = [asdict(item) for item in detect_integrations(repo)]
    warnings: list[str] = [
        f"{item['name']} missing; integration will be a warning only"
        for item in integrations
        if not item["available"]
    ]

    verdict = "pass"
    command_result: CommandResult | None = None

    if command:
        command_text = " ".join(command)
        jester_result = run_jester_command_check(repo, command_text)
        if jester_result is None:
            warnings.append("Jester command safety check skipped because jester is not installed")
        else:
            jester_out, jester_err = jester_result
            jester_path = artifacts_dir / "jester-command-check.txt"
            write_text(jester_path, (jester_out or "") + ("\n" + jester_err if jester_err else ""))
            artifacts["jester_command_check"] = str(jester_path)
            if respect_jester_blocks and "BLOCK" in (jester_out or "").upper():
                verdict = "block"

        if verdict != "block":
            effective_command = command
            if runner == "agentledger":
                has_agentledger = any(
                    item["name"] == "AgentLedger" and item["available"]
                    for item in integrations
                )
                if has_agentledger:
                    effective_command = agentledger_command(command, repo, out_dir)
                    artifacts["agentledger_out"] = str(out_dir / "agentledger")
                else:
                    warnings.append("AgentLedger runner requested but AgentLedger is not installed; using direct runner")
            command_result = run_command(effective_command, repo, artifacts_dir, timeout)
            if command_result.timed_out or command_result.returncode not in (0, None):
                verdict = "block"
    else:
        warnings.append("No command was supplied; doctor-style packet only")

    if git_available:
        after_path = artifacts_dir / "git-status-after.txt"
        diff_path = artifacts_dir / "git-diff-after.patch"
        write_text(after_path, run_capture(("git", "status", "--short"), repo))
        write_text(diff_path, run_capture(("git", "diff", "--stat"), repo) + "\n\n" + run_capture(("git", "diff"), repo, timeout=60))
        artifacts["git_status_after"] = str(after_path)
        artifacts["git_diff_after"] = str(diff_path)
    else:
        warnings.append("Git evidence skipped because the target path is not inside a git worktree")

    if verdict == "pass" and warnings:
        verdict = "warn"

    run = ControlRun(
        run_id=run_id,
        repo=str(repo),
        out_dir=str(out_dir),
        verdict=verdict,
        warnings=warnings,
        command_result=command_result,
        integrations=integrations,
        artifacts=artifacts,
    )

    json_path = out_dir / "hamiltonian-report.json"
    md_path = out_dir / "hamiltonian-report.md"
    write_text(json_path, json.dumps(asdict(run), indent=2))
    write_text(md_path, build_report(run))

    manifest = {
        "run_id": run_id,
        "files": [
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(out_dir.rglob("*"))
            if path.is_file()
        ],
        "python": sys.version,
        "platform": os.name,
    }
    write_text(out_dir / "manifest.json", json.dumps(manifest, indent=2))
    return run


def doctor(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    git_available = is_git_repo(repo)
    return {
        "repo": str(repo),
        "git_available": git_available,
        "git_status": run_capture(("git", "status", "--short"), repo) if git_available else "",
        "integrations": [asdict(item) for item in detect_integrations(repo)],
    }
