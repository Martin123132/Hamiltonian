from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

from .core import is_git_repo, write_text


RUNNER_CONTRACT_SCHEMA = "hamiltonian.runner-contract.v3"
RUNNER_RUN_SCHEMA = "hamiltonian.runner-run.v1"
RUNNER_RESULT_SCHEMA = "hamiltonian.result-receipt.v1"
RUNNER_LIFECYCLE = ("prepare", "launch", "stream", "cancel", "finish", "report")
RUNNER_LANES = {"codex", "openclaw", "hermes", "local"}
ACTIVE_RUN_STATUSES = {"starting", "running", "cancelling"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "timed-out", "cancelled", "interrupted"}
DEFAULT_RUN_TIMEOUT_SECONDS = 900
MIN_RUN_TIMEOUT_SECONDS = 5
MAX_RUN_TIMEOUT_SECONDS = 3600
MAX_RUN_LOG_BYTES = 2_000_000
MAX_RUN_EVENTS = 500


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adapter_id(lane_id: str) -> str:
    if lane_id in {"codex", "hermes"}:
        return f"{lane_id}-local"
    return f"{lane_id}-local-contract"


def _runner_label(lane_id: str) -> str:
    return {
        "codex": "Codex",
        "hermes": "Hermes Agent",
        "openclaw": "OpenClaw",
        "local": "Local runner",
    }.get(lane_id, "Local runner")


@dataclass(frozen=True)
class RunnerRequest:
    packet_id: str
    lane_id: str
    repo: Path
    task: str
    gate_status: str
    blocked_gate_ids: tuple[str, ...]
    attach_evidence: bool


@dataclass(frozen=True)
class RunnerPlan:
    schema: str
    adapter_id: str
    lane_id: str
    status: str
    mode: str
    lifecycle: tuple[str, ...]
    approval_required: bool
    adapter_available: bool
    adapter_detail: str
    launch_supported: bool
    sandbox_policy: str
    local_only: bool
    local_execution: bool
    remote_execution: bool
    workspace_name: str
    task_digest: str
    task_length: int
    artifact_path: str | None
    summary: str
    next_action: str


@dataclass(frozen=True)
class RunnerHandle:
    run_id: str
    adapter_id: str
    status: str
    process_id: int | None
    local_execution: bool
    remote_execution: bool
    summary: str


@dataclass(frozen=True)
class RunnerEvent:
    run_id: str
    sequence: int
    status: str
    message: str
    local_only: bool


@dataclass(frozen=True)
class RunnerReport:
    run_id: str
    adapter_id: str
    status: str
    exit_code: int | None
    local_execution: bool
    remote_execution: bool
    summary: str


@dataclass(frozen=True)
class AdapterProbe:
    available: bool
    command_prefix: tuple[str, ...]
    detail: str


@dataclass
class _ActiveRun:
    key: str
    adapter: RunnerAdapter
    request: RunnerRequest
    plan: RunnerPlan
    handle: RunnerHandle
    process: subprocess.Popen[bytes]
    packet_dir: Path
    run_dir: Path
    state_path: Path
    latest_path: Path
    events_path: Path
    output_path: Path
    final_message_path: Path
    report_path: Path
    result_receipt_path: Path
    timeout_seconds: int
    started_monotonic: float
    reader_thread: threading.Thread | None = None
    cancel_requested: bool = False
    output_truncated: bool = False
    events_written: int = 0


class RunnerAdapter(ABC):
    """Contract all future local agent and command adapters must implement."""

    adapter_id: str
    lane_id: str

    @abstractmethod
    def prepare(self, request: RunnerRequest, packet_dir: Path) -> RunnerPlan:
        raise NotImplementedError

    @abstractmethod
    def launch(self, plan: RunnerPlan) -> RunnerHandle:
        raise NotImplementedError

    @abstractmethod
    def stream(self, handle: RunnerHandle) -> tuple[RunnerEvent, ...]:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, handle: RunnerHandle) -> RunnerHandle:
        raise NotImplementedError

    @abstractmethod
    def finish(self, handle: RunnerHandle) -> RunnerReport:
        raise NotImplementedError

    @abstractmethod
    def report(self, handle: RunnerHandle) -> RunnerReport:
        raise NotImplementedError

    def build_command(self, request: RunnerRequest, run_dir: Path) -> list[str]:
        raise ValueError(f"{self.adapter_id} does not support launch")

    def persist_final_message(self, output_path: Path, final_message_path: Path) -> None:
        """Persist a final response when an adapter emits it through stdout."""


def runner_plan_state(
    lane_id: str,
    status: str,
    mode: str,
    summary: str,
    next_action: str,
) -> RunnerPlan:
    return RunnerPlan(
        schema=RUNNER_CONTRACT_SCHEMA,
        adapter_id=_adapter_id(lane_id),
        lane_id=lane_id,
        status=status,
        mode=mode,
        lifecycle=RUNNER_LIFECYCLE,
        approval_required=True,
        adapter_available=False,
        adapter_detail="No executable adapter is active for this packet state.",
        launch_supported=False,
        sandbox_policy="none",
        local_only=True,
        local_execution=False,
        remote_execution=False,
        workspace_name="",
        task_digest="",
        task_length=0,
        artifact_path=None,
        summary=summary,
        next_action=next_action,
    )


def _write_plan_artifact(
    plan: RunnerPlan,
    request: RunnerRequest,
    packet_dir: Path,
) -> RunnerPlan:
    runner_dir = packet_dir.resolve() / "runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = runner_dir / "runner-plan.json"
    stored_plan = RunnerPlan(**{**asdict(plan), "artifact_path": str(artifact_path)})
    artifact = asdict(stored_plan)
    artifact["artifact_path"] = artifact_path.name
    artifact["packet_id"] = request.packet_id
    artifact["gate_status"] = request.gate_status
    artifact["blocked_gate_ids"] = list(request.blocked_gate_ids)
    artifact["attach_evidence"] = request.attach_evidence
    artifact["task_included"] = False
    artifact["workspace_path_included"] = False
    write_text(artifact_path, json.dumps(artifact, indent=2))
    return stored_plan


class LocalDryRunRunnerAdapter(RunnerAdapter):
    """Persists a sanitized launch plan while deliberately executing nothing."""

    def __init__(self, lane_id: str) -> None:
        normalized = lane_id.lower().strip()
        if normalized not in RUNNER_LANES:
            raise ValueError(f"unknown runner lane: {lane_id}")
        self.lane_id = normalized
        self.adapter_id = _adapter_id(normalized)

    def prepare(self, request: RunnerRequest, packet_dir: Path) -> RunnerPlan:
        if request.lane_id != self.lane_id:
            raise ValueError("runner request lane does not match adapter lane")
        if request.blocked_gate_ids:
            return runner_plan_state(
                lane_id=self.lane_id,
                status="blocked",
                mode="local-dry-run",
                summary="Runner plan refused because one or more gates blocked the packet.",
                next_action="Clear blocked gates before preparing a launch plan.",
            )

        plan = RunnerPlan(
            schema=RUNNER_CONTRACT_SCHEMA,
            adapter_id=self.adapter_id,
            lane_id=self.lane_id,
            status="prepared",
            mode="local-dry-run",
            lifecycle=RUNNER_LIFECYCLE,
            approval_required=True,
            adapter_available=False,
            adapter_detail="This lane has a dry-run contract only.",
            launch_supported=False,
            sandbox_policy="none",
            local_only=True,
            local_execution=False,
            remote_execution=False,
            workspace_name=request.repo.resolve().name,
            task_digest=sha256(request.task.encode("utf-8")).hexdigest(),
            task_length=len(request.task),
            artifact_path=None,
            summary="Runner contract prepared a sanitized local launch plan; no process or agent executed.",
            next_action="Review the plan before a future local adapter is allowed to launch.",
        )
        return _write_plan_artifact(plan, request, packet_dir)

    def launch(self, plan: RunnerPlan) -> RunnerHandle:
        return RunnerHandle(
            run_id=f"{plan.lane_id}-dry-run",
            adapter_id=self.adapter_id,
            status="launch-disabled",
            process_id=None,
            local_execution=False,
            remote_execution=False,
            summary="This adapter stops at prepare; no process was launched.",
        )

    def stream(self, handle: RunnerHandle) -> tuple[RunnerEvent, ...]:
        return (
            RunnerEvent(
                run_id=handle.run_id,
                sequence=1,
                status=handle.status,
                message="No output stream exists because launch is disabled.",
                local_only=True,
            ),
        )

    def cancel(self, handle: RunnerHandle) -> RunnerHandle:
        return RunnerHandle(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status="not-running",
            process_id=None,
            local_execution=False,
            remote_execution=False,
            summary="Nothing was running, so cancellation was a local no-op.",
        )

    def finish(self, handle: RunnerHandle) -> RunnerReport:
        return RunnerReport(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status="not-executed",
            exit_code=None,
            local_execution=False,
            remote_execution=False,
            summary="Dry-run contract completed without starting a process.",
        )

    def report(self, handle: RunnerHandle) -> RunnerReport:
        return self.finish(handle)


def _configured_codex_command() -> tuple[str, ...]:
    configured = os.environ.get("HAMILTONIAN_CODEX_COMMAND", "").strip()
    if configured:
        if configured.startswith("["):
            try:
                value = json.loads(configured)
            except json.JSONDecodeError as exc:
                raise ValueError("HAMILTONIAN_CODEX_COMMAND must be a command or JSON array") from exc
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                raise ValueError("HAMILTONIAN_CODEX_COMMAND JSON must be a non-empty string array")
            return tuple(value)
        if Path(configured).exists():
            return (configured,)
        return tuple(shlex.split(configured, posix=os.name != "nt"))

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        runtime_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
        try:
            runtime_candidates = sorted(
                runtime_root.glob("*/codex.exe"),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
        except OSError:
            runtime_candidates = []
        if runtime_candidates:
            return (str(runtime_candidates[0]),)

    executable = shutil.which("codex")
    return (executable,) if executable else ()


def _configured_hermes_command() -> tuple[str, ...]:
    configured = os.environ.get("HAMILTONIAN_HERMES_COMMAND", "").strip()
    if configured:
        if configured.startswith("["):
            try:
                value = json.loads(configured)
            except json.JSONDecodeError as exc:
                raise ValueError("HAMILTONIAN_HERMES_COMMAND must be a command or JSON array") from exc
            if not isinstance(value, list) or not value or not all(
                isinstance(item, str) and item for item in value
            ):
                raise ValueError("HAMILTONIAN_HERMES_COMMAND JSON must be a non-empty string array")
            return tuple(value)
        if Path(configured).exists():
            return (configured,)
        return tuple(shlex.split(configured, posix=os.name != "nt"))
    executable = shutil.which("hermes")
    return (executable,) if executable else ()


def probe_codex_command(
    repo: Path,
    command_prefix: tuple[str, ...] | None = None,
) -> AdapterProbe:
    try:
        prefix = command_prefix if command_prefix is not None else _configured_codex_command()
    except ValueError as exc:
        return AdapterProbe(False, (), str(exc))
    if not prefix:
        return AdapterProbe(False, (), "Codex CLI is not installed or not on PATH.")
    try:
        proc = subprocess.run(
            [*prefix, "--version"],
            cwd=str(repo.resolve()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception as exc:
        return AdapterProbe(False, prefix, f"Codex CLI probe failed: {type(exc).__name__}.")
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    detail = output[0][:180] if output else f"Codex CLI exited {proc.returncode}."
    return AdapterProbe(proc.returncode == 0, prefix, detail)


def probe_hermes_command(
    repo: Path,
    command_prefix: tuple[str, ...] | None = None,
) -> AdapterProbe:
    try:
        prefix = command_prefix if command_prefix is not None else _configured_hermes_command()
    except ValueError as exc:
        return AdapterProbe(False, (), str(exc))
    if not prefix:
        return AdapterProbe(False, (), "Hermes Agent CLI is not installed or not on PATH.")
    try:
        proc = subprocess.run(
            [*prefix, "--version"],
            cwd=str(repo.resolve()),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except Exception as exc:
        return AdapterProbe(False, prefix, f"Hermes Agent CLI probe failed: {type(exc).__name__}.")
    output = (proc.stdout or proc.stderr or "").strip().splitlines()
    detail = output[0][:180] if output else f"Hermes Agent CLI exited {proc.returncode}."
    return AdapterProbe(proc.returncode == 0, prefix, detail)


class CodexLocalRunnerAdapter(RunnerAdapter):
    """Builds a workspace-bounded `codex exec` command for local supervision."""

    lane_id = "codex"
    adapter_id = "codex-local"

    def __init__(self, command_prefix: tuple[str, ...] | None = None) -> None:
        self.command_prefix = command_prefix
        self._probe: AdapterProbe | None = None

    def _probe_for(self, repo: Path) -> AdapterProbe:
        self._probe = probe_codex_command(repo, self.command_prefix)
        return self._probe

    def prepare(self, request: RunnerRequest, packet_dir: Path) -> RunnerPlan:
        if request.lane_id != self.lane_id:
            raise ValueError("runner request lane does not match adapter lane")
        if request.blocked_gate_ids:
            return runner_plan_state(
                lane_id=self.lane_id,
                status="blocked",
                mode="local-codex",
                summary="Codex runner plan refused because readiness gates blocked the packet.",
                next_action="Clear blocked gates before preparing a Codex launch.",
            )

        probe = self._probe_for(request.repo)
        git_ready = is_git_repo(request.repo)
        available = probe.available and git_ready
        detail = probe.detail if git_ready else "Codex launch requires a Git worktree."
        summary = (
            "Codex CLI is ready for an explicit workspace-bounded local launch."
            if available
            else "Codex runner contract is prepared, but the local CLI boundary is unavailable."
        )
        next_action = (
            "Review the timeout and explicitly launch the local Codex run."
            if available
            else "Install or expose a callable Codex CLI, then create a fresh execute packet."
        )
        plan = RunnerPlan(
            schema=RUNNER_CONTRACT_SCHEMA,
            adapter_id=self.adapter_id,
            lane_id=self.lane_id,
            status="prepared",
            mode="local-codex",
            lifecycle=RUNNER_LIFECYCLE,
            approval_required=True,
            adapter_available=available,
            adapter_detail=detail,
            launch_supported=available,
            sandbox_policy="workspace-write",
            local_only=True,
            local_execution=False,
            remote_execution=False,
            workspace_name=request.repo.resolve().name,
            task_digest=sha256(request.task.encode("utf-8")).hexdigest(),
            task_length=len(request.task),
            artifact_path=None,
            summary=summary,
            next_action=next_action,
        )
        return _write_plan_artifact(plan, request, packet_dir)

    def launch(self, plan: RunnerPlan) -> RunnerHandle:
        if not plan.launch_supported or not plan.adapter_available:
            return RunnerHandle(
                run_id=f"codex-unavailable-{uuid4().hex[:8]}",
                adapter_id=self.adapter_id,
                status="launch-disabled",
                process_id=None,
                local_execution=False,
                remote_execution=False,
                summary=plan.adapter_detail,
            )
        return RunnerHandle(
            run_id=f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
            adapter_id=self.adapter_id,
            status="starting",
            process_id=None,
            local_execution=True,
            remote_execution=False,
            summary="Codex launch was explicitly approved for local supervision.",
        )

    def stream(self, handle: RunnerHandle) -> tuple[RunnerEvent, ...]:
        return (
            RunnerEvent(
                run_id=handle.run_id,
                sequence=1,
                status=handle.status,
                message="Local Codex process entered the supervised runner boundary.",
                local_only=True,
            ),
        )

    def cancel(self, handle: RunnerHandle) -> RunnerHandle:
        return RunnerHandle(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status="cancelling",
            process_id=handle.process_id,
            local_execution=handle.local_execution,
            remote_execution=False,
            summary="Cancellation requested for the local process tree.",
        )

    def finish(self, handle: RunnerHandle) -> RunnerReport:
        summary_by_status = {
            "succeeded": "Local Codex process completed successfully.",
            "cancelled": "Local Codex process was cancelled by the operator.",
            "timed-out": "Local Codex process exceeded its bounded timeout.",
            "failed": "Local Codex process exited with a failure.",
        }
        return RunnerReport(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status=handle.status,
            exit_code=None,
            local_execution=handle.local_execution,
            remote_execution=False,
            summary=summary_by_status.get(handle.status, handle.summary),
        )

    def report(self, handle: RunnerHandle) -> RunnerReport:
        return self.finish(handle)

    def build_command(self, request: RunnerRequest, run_dir: Path) -> list[str]:
        probe = self._probe_for(request.repo)
        if not probe.available:
            raise ValueError(probe.detail)
        final_message_path = run_dir / "last-message.txt"
        return [
            *probe.command_prefix,
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--cd",
            str(request.repo.resolve()),
            "exec",
            "--ephemeral",
            "--json",
            "--output-last-message",
            str(final_message_path),
            request.task,
        ]


class HermesLocalRunnerAdapter(RunnerAdapter):
    """Builds an official one-shot Hermes CLI command for local supervision."""

    lane_id = "hermes"
    adapter_id = "hermes-local"

    def __init__(self, command_prefix: tuple[str, ...] | None = None) -> None:
        self.command_prefix = command_prefix
        self._probe: AdapterProbe | None = None

    def _probe_for(self, repo: Path) -> AdapterProbe:
        self._probe = probe_hermes_command(repo, self.command_prefix)
        return self._probe

    def prepare(self, request: RunnerRequest, packet_dir: Path) -> RunnerPlan:
        if request.lane_id != self.lane_id:
            raise ValueError("runner request lane does not match adapter lane")
        if request.blocked_gate_ids:
            return runner_plan_state(
                lane_id=self.lane_id,
                status="blocked",
                mode="local-hermes-one-shot",
                summary="Hermes runner plan refused because readiness gates blocked the packet.",
                next_action="Clear blocked gates before preparing a Hermes launch.",
            )

        probe = self._probe_for(request.repo)
        git_ready = is_git_repo(request.repo)
        available = probe.available and git_ready
        detail = probe.detail if git_ready else "Hermes launch requires a Git worktree."
        plan = RunnerPlan(
            schema=RUNNER_CONTRACT_SCHEMA,
            adapter_id=self.adapter_id,
            lane_id=self.lane_id,
            status="prepared",
            mode="local-hermes-one-shot",
            lifecycle=RUNNER_LIFECYCLE,
            approval_required=True,
            adapter_available=available,
            adapter_detail=detail,
            launch_supported=available,
            sandbox_policy="hermes-safe-mode-checkpoints",
            local_only=True,
            local_execution=False,
            remote_execution=False,
            workspace_name=request.repo.resolve().name,
            task_digest=sha256(request.task.encode("utf-8")).hexdigest(),
            task_length=len(request.task),
            artifact_path=None,
            summary=(
                "Hermes Agent CLI is ready for an explicit local one-shot launch."
                if available
                else "Hermes runner contract is prepared, but the local CLI boundary is unavailable."
            ),
            next_action=(
                "Review the timeout and explicitly launch Hermes in safe mode with checkpoints."
                if available
                else "Install or expose a callable Hermes Agent CLI, then create a fresh execute packet."
            ),
        )
        return _write_plan_artifact(plan, request, packet_dir)

    def launch(self, plan: RunnerPlan) -> RunnerHandle:
        if not plan.launch_supported or not plan.adapter_available:
            return RunnerHandle(
                run_id=f"hermes-unavailable-{uuid4().hex[:8]}",
                adapter_id=self.adapter_id,
                status="launch-disabled",
                process_id=None,
                local_execution=False,
                remote_execution=False,
                summary=plan.adapter_detail,
            )
        return RunnerHandle(
            run_id=f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}",
            adapter_id=self.adapter_id,
            status="starting",
            process_id=None,
            local_execution=True,
            remote_execution=False,
            summary="Hermes launch was explicitly approved for local supervision.",
        )

    def stream(self, handle: RunnerHandle) -> tuple[RunnerEvent, ...]:
        return (
            RunnerEvent(
                run_id=handle.run_id,
                sequence=1,
                status=handle.status,
                message="Local Hermes Agent process entered the supervised runner boundary.",
                local_only=True,
            ),
        )

    def cancel(self, handle: RunnerHandle) -> RunnerHandle:
        return RunnerHandle(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status="cancelling",
            process_id=handle.process_id,
            local_execution=handle.local_execution,
            remote_execution=False,
            summary="Cancellation requested for the local Hermes process tree.",
        )

    def finish(self, handle: RunnerHandle) -> RunnerReport:
        return RunnerReport(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status=handle.status,
            exit_code=None,
            local_execution=handle.local_execution,
            remote_execution=False,
            summary=handle.summary,
        )

    def report(self, handle: RunnerHandle) -> RunnerReport:
        return self.finish(handle)

    def build_command(self, request: RunnerRequest, run_dir: Path) -> list[str]:
        probe = self._probe_for(request.repo)
        if not probe.available:
            raise ValueError(probe.detail)
        bounded_task = (
            "Work only inside the current Git workspace. Do not access parent or sibling paths. "
            "Do not start gateways, delivery services, remote terminals, SSH, or Docker backends. "
            "Complete this bounded local task and return a concise final response:\n\n"
            f"{request.task}"
        )
        return [
            *probe.command_prefix,
            "--safe-mode",
            "--source",
            "tool",
            "--max-turns",
            "24",
            "--checkpoints",
            "-z",
            bounded_task,
        ]

    def persist_final_message(self, output_path: Path, final_message_path: Path) -> None:
        message = _read_tail(output_path, 4000).strip()
        if message:
            write_text(final_message_path, message)


def runner_adapter_for_lane(lane_id: str) -> RunnerAdapter:
    normalized = lane_id.lower().strip()
    if normalized == "codex":
        return CodexLocalRunnerAdapter()
    if normalized == "hermes":
        return HermesLocalRunnerAdapter()
    return LocalDryRunRunnerAdapter(normalized)


def runner_plan_from_dict(data: dict[str, Any]) -> RunnerPlan:
    return RunnerPlan(
        schema=str(data.get("schema") or RUNNER_CONTRACT_SCHEMA),
        adapter_id=str(data.get("adapter_id") or "unknown"),
        lane_id=str(data.get("lane_id") or "unknown"),
        status=str(data.get("status") or "unknown"),
        mode=str(data.get("mode") or "unknown"),
        lifecycle=tuple(str(item) for item in data.get("lifecycle") or RUNNER_LIFECYCLE),
        approval_required=bool(data.get("approval_required", True)),
        adapter_available=bool(data.get("adapter_available", False)),
        adapter_detail=str(data.get("adapter_detail") or "Adapter status unavailable."),
        launch_supported=bool(data.get("launch_supported", False)),
        sandbox_policy=str(data.get("sandbox_policy") or "none"),
        local_only=bool(data.get("local_only", True)),
        local_execution=bool(data.get("local_execution", False)),
        remote_execution=bool(data.get("remote_execution", False)),
        workspace_name=str(data.get("workspace_name") or ""),
        task_digest=str(data.get("task_digest") or ""),
        task_length=int(data.get("task_length") or 0),
        artifact_path=str(data["artifact_path"]) if data.get("artifact_path") else None,
        summary=str(data.get("summary") or "Runner plan unavailable."),
        next_action=str(data.get("next_action") or "Review runner state."),
    )


def runner_root(packet_dir: Path) -> Path:
    return packet_dir.resolve() / "runner"


def latest_run_path(packet_dir: Path) -> Path:
    return runner_root(packet_dir) / "latest-run.json"


def read_latest_runner_state(packet_dir: Path) -> dict[str, Any] | None:
    path = latest_run_path(packet_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) and payload.get("schema") == RUNNER_RUN_SCHEMA else None


def _safe_runner_event(line: str, sequence: int) -> dict[str, Any]:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return {"sequence": sequence, "type": "output", "status": "received", "summary": "Runner emitted local output."}
    event_type = str(payload.get("type") or "event")[:80]
    item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
    item_type = str(item.get("type") or "")[:80]
    item_status = str(item.get("status") or "")[:80]
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    summary = event_type.replace(".", " ")
    if item_type:
        summary = f"{summary}: {item_type.replace('_', ' ')}"
    if item_status:
        summary = f"{summary} ({item_status})"
    event: dict[str, Any] = {
        "sequence": sequence,
        "type": event_type,
        "status": item_status or ("failed" if "failed" in event_type or event_type == "error" else "received"),
        "summary": summary,
    }
    if item_type:
        event["item_type"] = item_type
    safe_usage = {
        key: int(value)
        for key, value in usage.items()
        if key in {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"}
        and isinstance(value, int)
    }
    if safe_usage:
        event["usage"] = safe_usage
    return event


def _read_json_lines(path: Path, limit: int = 40) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _read_tail(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]


class LocalRunManager:
    """Supervises bounded local processes and persists operator-readable state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveRun] = {}

    def start(
        self,
        adapter: RunnerAdapter,
        request: RunnerRequest,
        plan: RunnerPlan,
        packet_dir: Path,
        timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        timeout = int(timeout_seconds)
        if timeout < MIN_RUN_TIMEOUT_SECONDS or timeout > MAX_RUN_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be between {MIN_RUN_TIMEOUT_SECONDS} and {MAX_RUN_TIMEOUT_SECONDS}"
            )
        key = str(packet_dir.resolve())
        with self._lock:
            active = self._active.get(key)
            if active and active.process.poll() is None:
                raise ValueError("a local runner is already active for this packet")

        handle = adapter.launch(plan)
        if handle.status != "starting":
            raise ValueError(handle.summary or "runner launch is disabled")

        root = runner_root(packet_dir)
        run_dir = root / "runs" / handle.run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        state_path = run_dir / "state.json"
        latest_path = root / "latest-run.json"
        events_path = run_dir / "events.jsonl"
        output_path = run_dir / "runner-output.log"
        final_message_path = run_dir / "last-message.txt"
        report_path = run_dir / "runner-report.json"
        result_receipt_path = run_dir / "result-receipt.json"
        command = adapter.build_command(request, run_dir)
        started_at = _utc_now()
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                subprocess, "CREATE_NO_WINDOW", 0
            )
        try:
            process = subprocess.Popen(
                command,
                cwd=str(request.repo.resolve()),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=creationflags,
                start_new_session=os.name != "nt",
            )
        except Exception:
            label = _runner_label(request.lane_id)
            failed = self._base_state(
                handle=handle,
                request=request,
                plan=plan,
                status="failed",
                started_at=started_at,
                timeout_seconds=timeout,
                process_id=None,
                run_dir=run_dir,
                output_path=output_path,
                events_path=events_path,
                final_message_path=final_message_path,
                report_path=report_path,
                result_receipt_path=result_receipt_path,
                summary=f"Local {label} process could not be started.",
                error="process-start-failed",
            )
            failed["finished_at"] = _utc_now()
            self._write_state(state_path, latest_path, failed)
            raise ValueError(f"local {label} process could not be started")

        label = _runner_label(request.lane_id)
        running_handle = RunnerHandle(
            run_id=handle.run_id,
            adapter_id=handle.adapter_id,
            status="running",
            process_id=process.pid,
            local_execution=True,
            remote_execution=False,
            summary=f"Local {label} process is running under {plan.sandbox_policy}.",
        )
        active = _ActiveRun(
            key=key,
            adapter=adapter,
            request=request,
            plan=plan,
            handle=running_handle,
            process=process,
            packet_dir=packet_dir.resolve(),
            run_dir=run_dir,
            state_path=state_path,
            latest_path=latest_path,
            events_path=events_path,
            output_path=output_path,
            final_message_path=final_message_path,
            report_path=report_path,
            result_receipt_path=result_receipt_path,
            timeout_seconds=timeout,
            started_monotonic=time.monotonic(),
        )
        state = self._base_state(
            handle=running_handle,
            request=request,
            plan=plan,
            status="running",
            started_at=started_at,
            timeout_seconds=timeout,
            process_id=process.pid,
            run_dir=run_dir,
            output_path=output_path,
            events_path=events_path,
            final_message_path=final_message_path,
            report_path=report_path,
            result_receipt_path=result_receipt_path,
            summary=running_handle.summary,
        )
        self._write_state(state_path, latest_path, state)
        for event in adapter.stream(running_handle):
            self._append_event(active, {
                "sequence": event.sequence,
                "type": "runner.started",
                "status": event.status,
                "summary": event.message,
            })

        with self._lock:
            self._active[key] = active
        reader = threading.Thread(target=self._capture_output, args=(active,), daemon=True)
        watcher = threading.Thread(target=self._watch, args=(active,), daemon=True)
        active.reader_thread = reader
        reader.start()
        watcher.start()
        return self.get(packet_dir)

    def get(self, packet_dir: Path) -> dict[str, Any]:
        packet_dir = packet_dir.resolve()
        state = read_latest_runner_state(packet_dir)
        if state is None:
            return {
                "schema": RUNNER_RUN_SCHEMA,
                "status": "not-started",
                "local_execution": False,
                "remote_execution": False,
                "events": [],
                "last_message": "",
                "summary": "No local runner has started for this packet.",
            }
        events_path = Path(str(state.get("events_path") or ""))
        final_message_path = Path(str(state.get("final_message_path") or ""))
        result = dict(state)
        result["events"] = _read_json_lines(events_path)
        result["last_message"] = _read_tail(final_message_path, 4000)
        key = str(packet_dir)
        with self._lock:
            active = self._active.get(key)
            if active and result.get("status") in ACTIVE_RUN_STATUSES:
                result["duration_seconds"] = round(time.monotonic() - active.started_monotonic, 3)
                result["output_truncated"] = active.output_truncated
        return result

    def cancel(self, packet_dir: Path) -> dict[str, Any]:
        key = str(packet_dir.resolve())
        with self._lock:
            active = self._active.get(key)
            if not active or active.process.poll() is not None:
                state = self.get(packet_dir)
                if state.get("status") in TERMINAL_RUN_STATUSES:
                    return state
                raise ValueError("no active local runner exists for this packet")
            active.cancel_requested = True
            cancelling = active.adapter.cancel(active.handle)
            state = self.get(packet_dir)
            state.update(
                {
                    "status": "cancelling",
                    "updated_at": _utc_now(),
                    "summary": cancelling.summary,
                    "cancel_requested": True,
                }
            )
            state.pop("events", None)
            state.pop("last_message", None)
            self._write_state(active.state_path, active.latest_path, state)
        self._terminate_process_tree(active.process)
        return self.get(packet_dir)

    def _capture_output(self, active: _ActiveRun) -> None:
        stream = active.process.stdout
        if stream is None:
            return
        bytes_written = 0
        with active.output_path.open("wb") as output:
            for raw_line in iter(stream.readline, b""):
                if bytes_written < MAX_RUN_LOG_BYTES:
                    allowed = raw_line[: MAX_RUN_LOG_BYTES - bytes_written]
                    output.write(allowed)
                    output.flush()
                    bytes_written += len(allowed)
                    if len(allowed) < len(raw_line):
                        active.output_truncated = True
                else:
                    active.output_truncated = True
                if active.events_written < MAX_RUN_EVENTS:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line:
                        self._append_event(active, _safe_runner_event(line, active.events_written + 1))
        stream.close()

    def _watch(self, active: _ActiveRun) -> None:
        timed_out = False
        try:
            returncode = active.process.wait(timeout=active.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_process_tree(active.process)
            try:
                returncode = active.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                active.process.kill()
                returncode = active.process.wait(timeout=5)
        if active.reader_thread:
            active.reader_thread.join(timeout=5)
        active.adapter.persist_final_message(active.output_path, active.final_message_path)

        label = _runner_label(active.request.lane_id)
        if active.cancel_requested:
            status = "cancelled"
            summary = f"Local {label} run was cancelled by the operator."
        elif timed_out:
            status = "timed-out"
            summary = f"Local {label} run exceeded the {active.timeout_seconds}-second timeout."
        elif returncode == 0:
            status = "succeeded"
            summary = f"Local {label} run completed successfully inside the bounded workspace."
        else:
            status = "failed"
            summary = f"Local {label} run exited with code {returncode}."

        final_handle = RunnerHandle(
            run_id=active.handle.run_id,
            adapter_id=active.handle.adapter_id,
            status=status,
            process_id=active.process.pid,
            local_execution=True,
            remote_execution=False,
            summary=summary,
        )
        report = active.adapter.report(final_handle)
        finished_at = _utc_now()
        state = self._base_state(
            handle=final_handle,
            request=active.request,
            plan=active.plan,
            status=status,
            started_at=json.loads(active.state_path.read_text(encoding="utf-8")).get("started_at", finished_at),
            timeout_seconds=active.timeout_seconds,
            process_id=active.process.pid,
            run_dir=active.run_dir,
            output_path=active.output_path,
            events_path=active.events_path,
            final_message_path=active.final_message_path,
            report_path=active.report_path,
            result_receipt_path=active.result_receipt_path,
            summary=summary,
        )
        state.update(
            {
                "updated_at": finished_at,
                "finished_at": finished_at,
                "exit_code": returncode,
                "timed_out": timed_out,
                "cancel_requested": active.cancel_requested,
                "duration_seconds": round(time.monotonic() - active.started_monotonic, 3),
                "output_truncated": active.output_truncated,
            }
        )
        final_message = _read_tail(active.final_message_path, 4000).strip()
        result_receipt = {
            "schema": RUNNER_RESULT_SCHEMA,
            "run_id": active.handle.run_id,
            "packet_id": active.request.packet_id,
            "adapter_id": active.plan.adapter_id,
            "lane_id": active.request.lane_id,
            "status": status,
            "completed_at": finished_at,
            "exit_code": returncode,
            "duration_seconds": state["duration_seconds"],
            "workspace_name": active.plan.workspace_name,
            "task_digest": active.plan.task_digest,
            "result_available": bool(final_message),
            "result_digest": sha256(final_message.encode("utf-8")).hexdigest(),
            "result_length": len(final_message),
            "result_included": False,
            "evidence_requested": active.request.attach_evidence,
            "local_execution": True,
            "remote_execution": False,
        }
        write_text(active.result_receipt_path, json.dumps(result_receipt, indent=2))
        state["result_receipt_path"] = str(active.result_receipt_path)
        state["result_receipt"] = result_receipt
        report_payload = {
            **asdict(report),
            "exit_code": returncode,
            "timed_out": timed_out,
            "cancel_requested": active.cancel_requested,
            "duration_seconds": state["duration_seconds"],
            "sandbox_policy": active.plan.sandbox_policy,
            "workspace_name": active.plan.workspace_name,
            "task_digest": active.plan.task_digest,
            "task_included": False,
            "remote_execution": False,
        }
        write_text(active.report_path, json.dumps(report_payload, indent=2))
        self._append_event(
            active,
            {
                "sequence": active.events_written + 1,
                "type": f"runner.{status}",
                "status": status,
                "summary": summary,
            },
        )
        self._write_state(active.state_path, active.latest_path, state)
        with self._lock:
            self._active.pop(active.key, None)

    def _append_event(self, active: _ActiveRun, event: dict[str, Any]) -> None:
        if active.events_written >= MAX_RUN_EVENTS:
            return
        active.events_path.parent.mkdir(parents=True, exist_ok=True)
        with active.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=True) + "\n")
        active.events_written += 1

    @staticmethod
    def _base_state(
        handle: RunnerHandle,
        request: RunnerRequest,
        plan: RunnerPlan,
        status: str,
        started_at: str,
        timeout_seconds: int,
        process_id: int | None,
        run_dir: Path,
        output_path: Path,
        events_path: Path,
        final_message_path: Path,
        report_path: Path,
        result_receipt_path: Path,
        summary: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": RUNNER_RUN_SCHEMA,
            "run_id": handle.run_id,
            "packet_id": request.packet_id,
            "adapter_id": plan.adapter_id,
            "lane_id": request.lane_id,
            "status": status,
            "started_at": started_at,
            "updated_at": _utc_now(),
            "finished_at": None,
            "timeout_seconds": timeout_seconds,
            "process_id": process_id,
            "exit_code": None,
            "timed_out": False,
            "cancel_requested": False,
            "duration_seconds": 0.0,
            "sandbox_policy": plan.sandbox_policy,
            "workspace_name": plan.workspace_name,
            "task_digest": plan.task_digest,
            "task_included": False,
            "local_only": True,
            "local_execution": status in ACTIVE_RUN_STATUSES or status in TERMINAL_RUN_STATUSES,
            "remote_execution": False,
            "run_dir": str(run_dir),
            "output_path": str(output_path),
            "events_path": str(events_path),
            "final_message_path": str(final_message_path),
            "report_path": str(report_path),
            "result_receipt_path": str(result_receipt_path),
            "summary": summary,
            "error": error,
        }

    def _write_state(self, state_path: Path, latest_path: Path, state: dict[str, Any]) -> None:
        encoded = json.dumps(state, indent=2)
        with self._lock:
            self._atomic_write(state_path, encoded)
            self._atomic_write(latest_path, encoded)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(text, encoding="utf-8", errors="replace")
        for attempt in range(20):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except Exception:
                pass
        try:
            process.terminate()
        except OSError:
            return


def _packet_run_request(repo: Path, packet: dict[str, Any]) -> tuple[RunnerRequest, Path]:
    lane = packet.get("lane") if isinstance(packet.get("lane"), dict) else {}
    gate_run = packet.get("gate_run") if isinstance(packet.get("gate_run"), dict) else {}
    execution = packet.get("execution_boundary") if isinstance(packet.get("execution_boundary"), dict) else {}
    if str(packet.get("stage")) != "execute":
        raise ValueError("packet must be at execute stage before local launch")
    if str(packet.get("status")) != "execution-ready":
        raise ValueError("packet is not execution-ready")
    lane_id = str(lane.get("id") or packet.get("agent_id")).lower().strip()
    if lane_id not in {"codex", "hermes"}:
        raise ValueError("this lane does not have a live local adapter")
    if int(gate_run.get("blocked") or 0) > 0:
        raise ValueError("blocked gates prevent local launch")
    if int(gate_run.get("warnings") or 0) > 0:
        raise ValueError("gate warnings must be cleared before local launch")
    if str(execution.get("status")) != "awaiting-approval":
        raise ValueError("execution boundary is not awaiting explicit launch")
    if bool(execution.get("remote_execution")):
        raise ValueError("remote execution is not permitted")

    packet_repo = Path(str(packet.get("repo") or repo)).resolve()
    if packet_repo != repo.resolve():
        raise ValueError("packet repo does not match the selected workspace")
    root = (repo.resolve() / ".hamiltonian" / "tasks").resolve()
    packet_dir = Path(str(packet.get("packet_dir") or "")).resolve()
    if root not in packet_dir.parents:
        raise ValueError("packet directory is outside local task storage")
    task = str(packet.get("task") or "").strip()
    if not task:
        raise ValueError("packet task is empty")
    return (
        RunnerRequest(
            packet_id=str(packet.get("packet_id") or ""),
            lane_id=lane_id,
            repo=repo.resolve(),
            task=task,
            gate_status=str(gate_run.get("status") or "unknown"),
            blocked_gate_ids=tuple(str(item) for item in gate_run.get("blocked_gate_ids") or []),
            attach_evidence=bool(packet.get("attach_evidence")),
        ),
        packet_dir,
    )


def start_packet_run(
    manager: LocalRunManager,
    repo: Path,
    packet: dict[str, Any],
    timeout_seconds: int = DEFAULT_RUN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    request, packet_dir = _packet_run_request(repo.resolve(), packet)
    adapter = runner_adapter_for_lane(request.lane_id)
    plan = adapter.prepare(request, packet_dir)
    if not plan.launch_supported:
        raise ValueError(plan.adapter_detail)
    packet_json = packet_dir / "task-packet.json"
    stored_packet = dict(packet)
    stored_packet.pop("runner_run", None)
    stored_packet["runner_plan"] = asdict(plan)
    stored_packet.setdefault("files", {})["runner_plan"] = str(plan.artifact_path)
    write_text(packet_json, json.dumps(stored_packet, indent=2))
    return manager.start(adapter, request, plan, packet_dir, timeout_seconds)


def get_packet_run(
    manager: LocalRunManager,
    repo: Path,
    packet: dict[str, Any],
) -> dict[str, Any]:
    _, packet_dir = _packet_run_request_for_status(repo, packet)
    return manager.get(packet_dir)


def cancel_packet_run(
    manager: LocalRunManager,
    repo: Path,
    packet: dict[str, Any],
) -> dict[str, Any]:
    _, packet_dir = _packet_run_request_for_status(repo, packet)
    return manager.cancel(packet_dir)


def _packet_run_request_for_status(repo: Path, packet: dict[str, Any]) -> tuple[str, Path]:
    root = (repo.resolve() / ".hamiltonian" / "tasks").resolve()
    packet_dir = Path(str(packet.get("packet_dir") or "")).resolve()
    if root not in packet_dir.parents:
        raise ValueError("packet directory is outside local task storage")
    return str(packet.get("packet_id") or ""), packet_dir
