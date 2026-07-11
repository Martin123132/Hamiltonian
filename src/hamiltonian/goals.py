from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any
from uuid import uuid4

from .core import ensure_repo, is_git_repo, run_capture, write_text
from .runners import probe_codex_command


GOAL_SCHEMA = "hamiltonian.codex-goal.v1"
GOAL_TYPES = {"maintenance", "expansion"}
GOAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
GRADE_PATTERN = re.compile(
    r"(?im)^\s*Repository health:\s*\*{0,2}([A-F](?:\+\+|[+-])?)\b"
)
GRADE_STEPS = {
    "F": "D",
    "D": "C",
    "C": "C+",
    "C+": "B-",
    "B-": "B",
    "B": "B+",
    "B+": "A-",
    "A-": "A",
    "A": "A+",
    "A+": "A+",
}
MAX_REPORT_CHARS = 40_000
MAX_EXPANSION_CHARS = 2_000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_goal_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"goal-{stamp}-{uuid4().hex[:8]}"


def _clean_goal_id(value: str | None) -> str:
    goal_id = (value or new_goal_id()).strip()
    if not GOAL_ID_PATTERN.fullmatch(goal_id):
        raise ValueError("invalid goal id")
    return goal_id


def goals_root(repo: Path) -> Path:
    return repo.resolve() / ".hamiltonian" / "goals"


def goal_dir(repo: Path, goal_id: str) -> Path:
    clean_id = _clean_goal_id(goal_id)
    root = goals_root(repo).resolve()
    target = (root / clean_id).resolve()
    if root not in target.parents:
        raise ValueError("goal path escapes local goal store")
    return target


def ensure_local_state_excluded(repo: Path) -> None:
    if not is_git_repo(repo):
        return
    git_dir_output = run_capture(("git", "rev-parse", "--git-dir"), repo).strip()
    if not git_dir_output or "failed:" in git_dir_output:
        return
    git_dir = Path(git_dir_output)
    if not git_dir.is_absolute():
        git_dir = (repo / git_dir).resolve()
    exclude_path = git_dir / "info" / "exclude"
    current = exclude_path.read_text(encoding="utf-8", errors="replace") if exclude_path.exists() else ""
    patterns = {line.strip() for line in current.splitlines()}
    if ".hamiltonian/" in patterns or "/.hamiltonian/" in patterns:
        return
    prefix = "" if not current or current.endswith("\n") else "\n"
    write_text(exclude_path, f"{current}{prefix}.hamiltonian/\n")


def _git_value(repo: Path, *args: str) -> str | None:
    if not is_git_repo(repo):
        return None
    try:
        process = subprocess.run(
            ("git", *args),
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = process.stdout.strip()
    return value if process.returncode == 0 and value else None


def _source_grade(report: str) -> tuple[str | None, str | None]:
    match = GRADE_PATTERN.search(report)
    if not match:
        return None, None
    current = match.group(1).upper()
    return current, GRADE_STEPS.get(current, "A")


@dataclass(frozen=True)
class GoalPackage:
    schema: str
    goal_id: str
    goal_type: str
    status: str
    created_at: str
    repo: str
    repo_name: str
    source_packet_id: str | None
    source_grade: str | None
    target_grade: str | None
    objective: str
    expansion_request: str | None
    baseline_commit: str | None
    baseline_branch: str | None
    baseline_status: str
    goal_markdown: str
    goal_path: str | None
    source_report_path: str | None
    return_path: str
    review_prompt: str
    remote_execution: bool
    pushed: bool


def _objective(
    repo_name: str,
    goal_type: str,
    source_grade: str | None,
    target_grade: str | None,
    expansion_request: str | None,
) -> str:
    if goal_type == "maintenance":
        if source_grade and target_grade:
            return f"Raise {repo_name} from {source_grade} to {target_grade} by resolving the highest-value confirmed findings."
        return f"Improve {repo_name} by resolving the highest-value confirmed reliability and trust findings."
    return f"Expand {repo_name} so that: {expansion_request}"


def _goal_markdown(
    *,
    goal_id: str,
    goal_type: str,
    repo: Path,
    objective: str,
    report: str,
    baseline_commit: str | None,
    source_grade: str | None,
    target_grade: str | None,
    return_relative: str,
) -> str:
    maintenance_instructions = [
        "Prioritize the highest-severity confirmed findings that directly improve reliability and trust.",
        "Preserve product scope and existing behavior unless a confirmed defect requires a narrow change.",
        "Add focused regression tests for every corrected defect.",
        "Avoid unrelated refactors, dependency churn, and cosmetic work.",
    ]
    expansion_instructions = [
        "Implement the requested capability as a bounded production slice.",
        "Reuse established project patterns and preserve existing behavior.",
        "Add focused tests for the new behavior and its failure states.",
        "Keep adjacent improvements out of scope unless they are required for the capability.",
    ]
    instructions = maintenance_instructions if goal_type == "maintenance" else expansion_instructions
    if goal_type == "maintenance":
        grade_line = (
            f"- Health target: `{source_grade}` to `{target_grade}`"
            if source_grade and target_grade
            else "- Health target: improve the current result by one defensible step"
        )
    else:
        grade_line = "- Health context: preserve the current baseline while adding the requested capability"
    lines = [
        "# Codex Goal",
        "",
        f"- Goal ID: `{goal_id}`",
        f"- Type: `{goal_type}`",
        f"- Workspace: `{repo}`",
        f"- Baseline commit: `{baseline_commit or 'unavailable'}`",
        grade_line,
        "",
        "## Workspace Lock",
        "",
        f"- Expected workspace: `{repo}`",
        "- Before reading or changing project files, resolve the current workspace and compare it with the expected workspace above.",
        "- If the paths do not match, stop immediately and report the mismatch. Do not modify either project.",
        "- Do not search for, clone, or substitute a similarly named repository.",
        "",
        "## Objective",
        "",
        objective,
        "",
        "## Work Rules",
        "",
        *(f"- {item}" for item in instructions),
        "- Work only inside the named workspace.",
        "- Do not push, publish, create a pull request, or contact anyone without explicit approval.",
        "- Keep credentials, private URLs, and local-only data out of commits and reports.",
        "",
        "## Acceptance",
        "",
        "- The requested changes are implemented and explained.",
        "- Relevant focused tests pass.",
        "- The complete existing test suite is run when practical, with any limitation stated.",
        "- The final diff contains no unrelated changes.",
        "- Remaining risks or blocked work are reported explicitly.",
        "",
        "## Hamiltonian Source Report",
        "",
        report.strip(),
        "",
        "## Return For Review",
        "",
        "When the work is ready, do not start another task. Write a JSON receipt to:",
        "",
        f"`{return_relative}`",
        "",
        "The receipt must contain: `goal_id`, `status`, `summary`, `files_changed`, `tests`, "
        "`branch`, `commit`, `pushed`, and `remaining_work`.",
        "",
        "Finish your Codex response with:",
        "",
        "```text",
        "HAMILTONIAN READY FOR REVIEW",
        f"Goal ID: {goal_id}",
        "Summary:",
        "Files changed:",
        "Tests run:",
        "Branch/commit:",
        "Pushed: yes/no",
        "Remaining concerns:",
        "```",
        "",
        "Do not mark the goal complete until the acceptance checks have passed.",
        "",
    ]
    return "\n".join(lines)


def preview_goal_package(
    repo_path: Path,
    goal_type: str,
    source_report: str,
    source_packet_id: str | None = None,
    expansion_request: str | None = None,
    goal_id: str | None = None,
) -> GoalPackage:
    repo = ensure_repo(repo_path)
    normalized_type = goal_type.lower().strip()
    if normalized_type not in GOAL_TYPES:
        raise ValueError("goal type must be maintenance or expansion")
    report = source_report.strip()
    if not report:
        raise ValueError("source report must not be empty")
    if len(report) > MAX_REPORT_CHARS:
        report = report[:MAX_REPORT_CHARS].rstrip() + "\n\n[Report truncated by Hamiltonian.]"
    expansion = (expansion_request or "").strip() or None
    if normalized_type == "expansion":
        if not expansion:
            raise ValueError("expansion goals require the capability that should become possible")
        if len(expansion) > MAX_EXPANSION_CHARS:
            raise ValueError("expansion request is too long")

    clean_id = _clean_goal_id(goal_id)
    source_grade, target_grade = _source_grade(report)
    objective = _objective(repo.name, normalized_type, source_grade, target_grade, expansion)
    baseline_commit = _git_value(repo, "rev-parse", "HEAD")
    baseline_branch = _git_value(repo, "branch", "--show-current")
    baseline_status = _git_value(repo, "status", "--short") or ""
    relative_root = Path(".hamiltonian") / "goals" / clean_id
    return_relative = str(relative_root / "return.json")
    goal_markdown = _goal_markdown(
        goal_id=clean_id,
        goal_type=normalized_type,
        repo=repo,
        objective=objective,
        report=report,
        baseline_commit=baseline_commit,
        source_grade=source_grade,
        target_grade=target_grade,
        return_relative=return_relative,
    )
    review_prompt = (
        f"Review completed Codex goal {clean_id} in this repository. Read "
        f"{relative_root / 'goal.md'} and {relative_root / 'return.json'} if present. "
        f"Compare the actual git diff against baseline commit {baseline_commit or 'recorded in the goal package'}. "
        "Run a read-only verification of the declared tests and acceptance criteria. Do not modify files. "
        "Report whether the goal is complete and, for maintenance goals, assign a new defensible health grade."
    )
    return GoalPackage(
        schema=GOAL_SCHEMA,
        goal_id=clean_id,
        goal_type=normalized_type,
        status="preview",
        created_at=_utc_now(),
        repo=str(repo),
        repo_name=repo.name,
        source_packet_id=source_packet_id,
        source_grade=source_grade,
        target_grade=target_grade,
        objective=objective,
        expansion_request=expansion,
        baseline_commit=baseline_commit,
        baseline_branch=baseline_branch,
        baseline_status=baseline_status,
        goal_markdown=goal_markdown,
        goal_path=None,
        source_report_path=None,
        return_path=str(repo / return_relative),
        review_prompt=review_prompt,
        remote_execution=False,
        pushed=False,
    )


def save_goal_package(package: GoalPackage, source_report: str) -> GoalPackage:
    repo = ensure_repo(Path(package.repo))
    target = goal_dir(repo, package.goal_id)
    target.mkdir(parents=True, exist_ok=True)
    ensure_local_state_excluded(repo)
    goal_path = target / "goal.md"
    source_path = target / "source-report.md"
    package_path = target / "goal.json"
    saved = GoalPackage(
        **{
            **asdict(package),
            "status": "saved",
            "goal_path": str(goal_path),
            "source_report_path": str(source_path),
        }
    )
    write_text(goal_path, saved.goal_markdown)
    bounded_report = source_report.strip()
    if len(bounded_report) > MAX_REPORT_CHARS:
        bounded_report = bounded_report[:MAX_REPORT_CHARS].rstrip() + "\n\n[Report truncated by Hamiltonian.]"
    write_text(source_path, bounded_report + "\n")
    write_text(package_path, json.dumps(asdict(saved), indent=2))
    return saved


def create_goal_package(
    repo_path: Path,
    goal_type: str,
    source_report: str,
    source_packet_id: str | None = None,
    expansion_request: str | None = None,
    goal_id: str | None = None,
) -> GoalPackage:
    package = preview_goal_package(
        repo_path=repo_path,
        goal_type=goal_type,
        source_report=source_report,
        source_packet_id=source_packet_id,
        expansion_request=expansion_request,
        goal_id=goal_id,
    )
    return save_goal_package(package, source_report)


def list_goal_packages(repo_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = goals_root(repo)
    if not root.exists():
        return []
    packages: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/goal.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("schema") == GOAL_SCHEMA:
            packages.append(payload)
        if len(packages) >= max(1, min(limit, 100)):
            break
    return packages


def open_codex_workspace(repo_path: Path) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    probe = probe_codex_command(repo)
    if not probe.available:
        raise ValueError(probe.detail)
    command = [*probe.command_prefix, "app", str(repo)]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(repo),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    return {
        "opened": True,
        "repo": str(repo),
        "repo_name": repo.name,
        "process_id": process.pid,
        "command": "codex app <workspace>",
        "remote_execution": False,
    }
