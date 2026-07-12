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

from .comparisons import get_result_comparison
from .core import ensure_repo, is_git_repo, run_capture, write_text
from .runners import probe_codex_command


GOAL_SCHEMA = "hamiltonian.codex-goal.v2"
LEGACY_GOAL_SCHEMAS = {"hamiltonian.codex-goal.v1", GOAL_SCHEMA}
REVIEW_SCHEMA = "hamiltonian.goal-review.v1"
GOAL_TYPES = {"maintenance", "expansion", "corrective"}
GOAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
GRADE_PATTERN = re.compile(
    r"(?im)^\s*Repository health:\s*\*{0,2}([A-F](?:\+\+|[+-])?)(?=\*|\s|[\u2013\u2014-]|$)"
)
REVIEW_GRADE_PATTERN = re.compile(
    r"(?im)^\s*\*{0,2}(?:Maintenance health grade|Repository health):\s*\*{0,2}([A-F](?:\+\+|[+-])?)(?=\*|\s|[\u2013\u2014-]|$)"
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
MAX_RECEIPT_BYTES = 64_000
REQUIRED_RECEIPT_FIELDS = {
    "goal_id",
    "status",
    "summary",
    "files_changed",
    "tests",
    "branch",
    "commit",
    "pushed",
    "remaining_work",
}


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


def _goal_file(repo: Path, goal_id: str, filename: str) -> Path:
    root = goal_dir(repo, goal_id)
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise ValueError(f"goal {filename} escapes the local goal directory")
    return candidate


def _read_bounded_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError(f"{path.name} is too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _load_goal_payload(repo: Path, goal_id: str) -> dict[str, Any]:
    payload = _read_bounded_json(_goal_file(repo, goal_id, "goal.json"))
    if payload.get("schema") not in LEGACY_GOAL_SCHEMAS:
        raise ValueError("unsupported goal package schema")
    if payload.get("goal_id") != goal_id:
        raise ValueError("goal package id does not match its directory")
    return payload


def _sanitize_summary(value: Any, limit: int = 500) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")[:limit]
    text = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"(?i)(?:[a-z]:\\|/)[^\s\"']+", "<local-path>", text)
    text = re.sub(r"https?://\S+", "<remote-url>", text)
    return text.strip()


def inspect_goal_receipt(repo_path: Path, goal_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    try:
        path = _goal_file(repo, goal_id, "return.json")
        payload = _read_bounded_json(path)
        missing = sorted(REQUIRED_RECEIPT_FIELDS - payload.keys())
        if missing:
            raise ValueError(f"receipt is missing: {', '.join(missing)}")
        if str(payload.get("goal_id")) != goal_id:
            raise ValueError("receipt goal_id does not match the goal")
        files = payload.get("files_changed")
        tests = payload.get("tests")
        if not isinstance(files, list) or not isinstance(tests, list):
            raise ValueError("receipt files_changed and tests must be lists")
        return {
            "status": "ready",
            "valid": True,
            "goal_id": goal_id,
            "codex_status": _sanitize_summary(payload.get("status"), 80),
            "summary": _sanitize_summary(payload.get("summary")),
            "files_changed_count": len(files),
            "tests": [_sanitize_summary(item, 180) for item in tests[:12]],
            "branch": _sanitize_summary(payload.get("branch"), 120),
            "commit": _sanitize_summary(payload.get("commit"), 120),
            "pushed": bool(payload.get("pushed")),
            "remaining_work": _sanitize_summary(payload.get("remaining_work")),
        }
    except FileNotFoundError:
        return {"status": "missing", "valid": False, "goal_id": goal_id}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "valid": False,
            "goal_id": goal_id,
            "error": _sanitize_summary(exc, 240),
        }


def _review_verdict(report: str) -> str:
    normalized = re.sub(r"[*_`]", "", report).lower()
    if re.search(r"\bgoal\s+(?:is\s+)?incomplete\b", normalized):
        return "incomplete"
    if re.search(r"\bgoal\s+(?:is\s+)?complete\b", normalized):
        return "complete"
    return "unknown"


def _review_grade(report: str) -> str | None:
    match = REVIEW_GRADE_PATTERN.search(report)
    return match.group(1).upper() if match else None


def inspect_goal_review(repo_path: Path, goal_id: str) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    try:
        payload = _read_bounded_json(_goal_file(repo, goal_id, "review.json"))
        if payload.get("schema") != REVIEW_SCHEMA or payload.get("goal_id") != goal_id:
            raise ValueError("review metadata does not match the goal")
        return {
            "status": "recorded",
            "valid": True,
            "goal_id": goal_id,
            "verdict": str(payload.get("verdict") or "unknown"),
            "summary": _sanitize_summary(payload.get("summary")),
            "reviewed_at": str(payload.get("reviewed_at") or ""),
            "source_packet_id": str(payload.get("source_packet_id") or "") or None,
            "assigned_grade": str(payload.get("assigned_grade") or "") or None,
        }
    except FileNotFoundError:
        return {"status": "missing", "valid": False, "goal_id": goal_id}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "invalid",
            "valid": False,
            "goal_id": goal_id,
            "error": _sanitize_summary(exc, 240),
        }


def save_goal_review(
    repo_path: Path,
    goal_id: str,
    report: str,
    source_packet_id: str | None = None,
) -> dict[str, Any]:
    repo = ensure_repo(repo_path)
    _load_goal_payload(repo, goal_id)
    bounded_report = report.strip()
    if not bounded_report:
        raise ValueError("review report must not be empty")
    if len(bounded_report) > MAX_REPORT_CHARS:
        bounded_report = bounded_report[:MAX_REPORT_CHARS].rstrip() + "\n\n[Review truncated by Hamiltonian.]"
    verdict = _review_verdict(bounded_report)
    if verdict == "unknown":
        raise ValueError("review must state whether the goal is complete or incomplete")
    target = goal_dir(repo, goal_id)
    report_path = target / "review-report.md"
    metadata_path = target / "review.json"
    reviewed_at = _utc_now()
    summary_line = verdict
    for line in bounded_report.splitlines():
        cleaned = line.strip(" #*`_")
        if cleaned and cleaned.lower() not in {"verdict", "review", "goal review"}:
            summary_line = cleaned
            break
    metadata = {
        "schema": REVIEW_SCHEMA,
        "goal_id": goal_id,
        "reviewed_at": reviewed_at,
        "verdict": verdict,
        "summary": _sanitize_summary(summary_line),
        "source_packet_id": source_packet_id,
        "assigned_grade": _review_grade(bounded_report),
        "report_path": str(report_path),
        "local_only": True,
        "remote_execution": False,
    }
    write_text(report_path, bounded_report + "\n")
    write_text(metadata_path, json.dumps(metadata, indent=2) + "\n")
    return inspect_goal_review(repo, goal_id)


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
    parent_goal_id: str | None = None
    lineage_root_id: str | None = None
    correction_index: int = 0
    source_comparison_id: str | None = None


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
    if goal_type == "corrective":
        return f"Complete the blocked Hamiltonian goal for {repo_name} by resolving every confirmed review finding."
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
    parent_goal_id: str | None,
    lineage_root_id: str | None,
    correction_index: int,
    source_comparison_id: str | None,
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
    corrective_instructions = [
        "Resolve every blocking finding in the Hamiltonian review before claiming completion.",
        "Add the missing focused regressions identified by the review.",
        "Preserve the accepted work from the parent goal and avoid unrelated changes.",
        "Rerun the declared focused and full verification after the corrections.",
    ]
    instructions = (
        maintenance_instructions
        if goal_type == "maintenance"
        else corrective_instructions
        if goal_type == "corrective"
        else expansion_instructions
    )
    if goal_type == "maintenance":
        grade_line = (
            f"- Health target: `{source_grade}` to `{target_grade}`"
            if source_grade and target_grade
            else "- Health target: improve the current result by one defensible step"
        )
    elif goal_type == "expansion":
        grade_line = "- Health context: preserve the current baseline while adding the requested capability"
    else:
        grade_line = "- Review target: resolve the parent goal's confirmed blocking findings"
    lines = [
        "# Codex Goal",
        "",
        f"- Goal ID: `{goal_id}`",
        f"- Type: `{goal_type}`",
        f"- Workspace: `{repo}`",
        f"- Baseline commit: `{baseline_commit or 'unavailable'}`",
        grade_line,
        *(f"- Parent goal: `{parent_goal_id}`" for _ in [0] if parent_goal_id),
        *(f"- Lineage root: `{lineage_root_id}`" for _ in [0] if lineage_root_id),
        *(f"- Correction: `{correction_index}`" for _ in [0] if correction_index),
        *(f"- Source comparison: `{source_comparison_id}`" for _ in [0] if source_comparison_id),
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
    parent_goal_id: str | None = None,
    source_comparison_id: str | None = None,
) -> GoalPackage:
    repo = ensure_repo(repo_path)
    normalized_type = goal_type.lower().strip()
    if normalized_type not in GOAL_TYPES:
        raise ValueError("goal type must be maintenance, expansion, or corrective")
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

    parent_id = _clean_goal_id(parent_goal_id) if parent_goal_id else None
    lineage_root_id: str | None = None
    correction_index = 0
    if normalized_type == "corrective":
        if not parent_id:
            raise ValueError("corrective goals require a parent goal")
        parent = _load_goal_payload(repo, parent_id)
        lineage_root_id = str(parent.get("lineage_root_id") or parent_id)
        correction_index = int(parent.get("correction_index") or 0) + 1
    elif parent_id:
        raise ValueError("parent_goal_id is only valid for corrective goals")

    comparison_id = source_comparison_id.strip() if source_comparison_id else None
    if comparison_id:
        comparison = get_result_comparison(repo, comparison_id)
        decision = comparison.get("decision") if isinstance(comparison.get("decision"), dict) else {}
        if decision.get("status") != "selected":
            raise ValueError("comparison must have a selected result before creating a goal")
        if decision.get("selected_packet_id") != source_packet_id:
            raise ValueError("goal source packet does not match the comparison decision")

    clean_id = _clean_goal_id(goal_id)
    if lineage_root_id is None:
        lineage_root_id = clean_id
    if parent_id == clean_id:
        raise ValueError("corrective goal cannot be its own parent")
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
        parent_goal_id=parent_id,
        lineage_root_id=lineage_root_id,
        correction_index=correction_index,
        source_comparison_id=comparison_id,
    )
    review_prompt = (
        f"Review completed Codex goal {clean_id} in this repository. Read "
        f"{relative_root / 'goal.md'} and {relative_root / 'return.json'} if present. "
        f"Compare the actual git diff against baseline commit {baseline_commit or 'recorded in the goal package'}. "
        "Run a read-only verification of the declared tests and acceptance criteria. Do not modify files. "
        "Report whether the goal is complete and, for maintenance or corrective goals, assign a new defensible health grade."
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
        parent_goal_id=parent_id,
        lineage_root_id=lineage_root_id,
        correction_index=correction_index,
        source_comparison_id=comparison_id,
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
    parent_goal_id: str | None = None,
    source_comparison_id: str | None = None,
) -> GoalPackage:
    package = preview_goal_package(
        repo_path=repo_path,
        goal_type=goal_type,
        source_report=source_report,
        source_packet_id=source_packet_id,
        expansion_request=expansion_request,
        goal_id=goal_id,
        parent_goal_id=parent_goal_id,
        source_comparison_id=source_comparison_id,
    )
    return save_goal_package(package, source_report)


def create_corrective_goal(repo_path: Path, parent_goal_id: str) -> GoalPackage:
    repo = ensure_repo(repo_path)
    parent_id = _clean_goal_id(parent_goal_id)
    review = inspect_goal_review(repo, parent_id)
    if not review.get("valid") or review.get("verdict") != "incomplete":
        raise ValueError("a corrective goal requires an incomplete recorded review")
    if any(
        goal.get("parent_goal_id") == parent_id
        for goal in list_goal_packages(repo, limit=100)
    ):
        raise ValueError("this goal already has a corrective follow-up")
    report_path = _goal_file(repo, parent_id, "review-report.md")
    if not report_path.is_file() or report_path.stat().st_size > MAX_REPORT_CHARS * 2:
        raise ValueError("parent review report is unavailable or too large")
    report = report_path.read_text(encoding="utf-8")
    return create_goal_package(
        repo_path=repo,
        goal_type="corrective",
        source_report=report,
        source_packet_id=str(review.get("source_packet_id") or "") or None,
        parent_goal_id=parent_id,
    )


def list_goal_packages(repo_path: Path, limit: int = 20) -> list[dict[str, Any]]:
    repo = ensure_repo(repo_path)
    root = goals_root(repo)
    if not root.exists():
        return []
    candidates: list[tuple[int, Path]] = []
    for path in root.glob("*/goal.json"):
        try:
            safe_path = _goal_file(repo, path.parent.name, "goal.json")
            candidates.append((safe_path.stat().st_mtime_ns, safe_path))
        except (OSError, ValueError):
            continue
    raw: list[dict[str, Any]] = []
    for _, path in sorted(candidates, key=lambda item: item[0], reverse=True):
        try:
            payload = _read_bounded_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            payload.get("schema") in LEGACY_GOAL_SCHEMAS
            and payload.get("goal_id") == path.parent.name
            and GOAL_ID_PATTERN.fullmatch(str(payload.get("goal_id") or ""))
        ):
            raw.append(payload)

    by_id = {str(item["goal_id"]): item for item in raw}
    children: dict[str, list[str]] = {}
    for item in raw:
        parent_id = str(item.get("parent_goal_id") or "")
        if parent_id:
            children.setdefault(parent_id, []).append(str(item["goal_id"]))
    reviews = {
        str(item["goal_id"]): inspect_goal_review(repo, str(item["goal_id"]))
        for item in raw
    }

    packages: list[dict[str, Any]] = []
    for payload in raw:
        goal_id = str(payload["goal_id"])
        receipt = inspect_goal_receipt(repo, goal_id)
        review = reviews[goal_id]
        child_ids = children.get(goal_id, [])
        corrected = any(
            reviews.get(child_id, {}).get("verdict") == "complete"
            for child_id in child_ids
        )
        if review.get("verdict") == "complete":
            lifecycle_status = "complete"
        elif review.get("verdict") == "incomplete" and corrected:
            lifecycle_status = "corrected"
        elif review.get("verdict") == "incomplete" and child_ids:
            lifecycle_status = "correction-in-progress"
        elif review.get("verdict") == "incomplete":
            lifecycle_status = "needs-correction"
        elif receipt.get("valid"):
            lifecycle_status = "ready-for-review"
        elif receipt.get("status") == "invalid":
            lifecycle_status = "receipt-invalid"
        else:
            lifecycle_status = "awaiting-codex"

        parent_id = str(payload.get("parent_goal_id") or "") or None
        starting_grade = str(payload.get("source_grade") or "") or None
        if not starting_grade and parent_id and parent_id in by_id:
            parent_review = reviews[parent_id]
            starting_grade = str(parent_review.get("assigned_grade") or "") or None
        ending_grade = str(review.get("assigned_grade") or "") or None
        grade_movement = (
            f"{starting_grade} to {ending_grade}"
            if starting_grade and ending_grade and starting_grade != ending_grade
            else ending_grade or starting_grade
        )
        packages.append(
            {
                **payload,
                "schema": GOAL_SCHEMA,
                "parent_goal_id": parent_id,
                "lineage_root_id": str(payload.get("lineage_root_id") or goal_id),
                "correction_index": int(payload.get("correction_index") or 0),
                "lifecycle_status": lifecycle_status,
                "receipt": receipt,
                "review": review,
                "child_goal_ids": child_ids,
                "grade_movement": grade_movement,
            }
        )
        if len(packages) >= max(1, min(limit, 100)):
            break
    return packages


def goal_workspace_summary(repo_path: Path) -> dict[str, int]:
    goals = list_goal_packages(repo_path, limit=100)
    return {
        "total": len(goals),
        "ready_for_review": sum(goal.get("lifecycle_status") == "ready-for-review" for goal in goals),
        "needs_correction": sum(goal.get("lifecycle_status") == "needs-correction" for goal in goals),
        "complete": sum(goal.get("lifecycle_status") in {"complete", "corrected"} for goal in goals),
    }


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
