from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import time

from hamiltonian.integrations import _cached_detect_integrations, detect_integrations
from hamiltonian.runners import (
    RUNNER_CONTRACT_SCHEMA,
    RUNNER_LIFECYCLE,
    RUNNER_RESULT_SCHEMA,
    CodexLocalRunnerAdapter,
    HermesLocalRunnerAdapter,
    LocalRunManager,
    LocalDryRunRunnerAdapter,
    RunnerRequest,
    _configured_codex_command,
    _configured_hermes_command,
    probe_hermes_command,
    read_latest_runner_state,
    runner_adapter_for_lane,
)


def init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def wait_for_terminal_run(manager: LocalRunManager, packet_dir: Path, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.get(packet_dir)
        if state["status"] not in {"starting", "running", "cancelling"}:
            return state
        time.sleep(0.05)
    raise AssertionError("runner did not reach a terminal state")


def test_codex_discovery_prefers_newest_app_managed_user_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "OpenAI" / "Codex" / "bin"
    older = runtime_root / "older" / "codex.exe"
    newest = runtime_root / "newest" / "codex.exe"
    older.parent.mkdir(parents=True)
    newest.parent.mkdir(parents=True)
    older.write_bytes(b"older")
    newest.write_bytes(b"newest")
    older.touch()
    newest.touch()
    older_stat = older.stat()
    newest_stat = newest.stat()
    if newest_stat.st_mtime_ns <= older_stat.st_mtime_ns:
        import os

        os.utime(newest, ns=(newest_stat.st_atime_ns, older_stat.st_mtime_ns + 1_000_000))

    monkeypatch.delenv("HAMILTONIAN_CODEX_COMMAND", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("hamiltonian.runners.shutil.which", lambda _name: "C:\\protected\\codex.exe")

    assert _configured_codex_command() == (str(newest),)


def test_local_dry_run_runner_implements_complete_contract_without_execution(
    tmp_path: Path,
) -> None:
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-1"
    request = RunnerRequest(
        packet_id="packet-1",
        lane_id="codex",
        repo=tmp_path,
        task="Patch the local UI and run focused tests.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = LocalDryRunRunnerAdapter("codex")

    plan = adapter.prepare(request, packet_dir)
    artifact = json.loads(Path(plan.artifact_path or "").read_text(encoding="utf-8"))

    assert plan.schema == RUNNER_CONTRACT_SCHEMA
    assert plan.lifecycle == RUNNER_LIFECYCLE
    assert plan.status == "prepared"
    assert plan.mode == "local-dry-run"
    assert plan.approval_required is True
    assert plan.launch_supported is False
    assert plan.local_only is True
    assert plan.local_execution is False
    assert plan.remote_execution is False
    assert artifact["artifact_path"] == "runner-plan.json"
    assert artifact["task_included"] is False
    assert artifact["workspace_path_included"] is False
    assert request.task not in json.dumps(artifact)
    assert str(tmp_path.resolve()) not in json.dumps(artifact)

    handle = adapter.launch(plan)
    events = adapter.stream(handle)
    cancelled = adapter.cancel(handle)
    finished = adapter.finish(handle)
    reported = adapter.report(handle)

    assert handle.status == "launch-disabled"
    assert handle.process_id is None
    assert handle.local_execution is False
    assert handle.remote_execution is False
    assert events[0].status == "launch-disabled"
    assert cancelled.status == "not-running"
    assert finished.status == "not-executed"
    assert reported == finished
    assert asdict(reported)["exit_code"] is None


def test_runner_adapter_rejects_lane_mismatch_and_blocked_plan_stays_in_memory(
    tmp_path: Path,
) -> None:
    adapter = runner_adapter_for_lane("local")
    mismatch = RunnerRequest(
        packet_id="packet-2",
        lane_id="codex",
        repo=tmp_path,
        task="Run a local smoke check.",
        gate_status="ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    try:
        adapter.prepare(mismatch, tmp_path / "packet-2")
        raise AssertionError("lane mismatch should fail")
    except ValueError as exc:
        assert "does not match" in str(exc)

    blocked = RunnerRequest(
        packet_id="packet-3",
        lane_id="local",
        repo=tmp_path,
        task="Unsafe task",
        gate_status="blocked",
        blocked_gate_ids=("intent",),
        attach_evidence=False,
    )
    plan = adapter.prepare(blocked, tmp_path / "packet-3")

    assert plan.status == "blocked"
    assert plan.artifact_path is None
    assert not (tmp_path / "packet-3" / "runner").exists()


def test_codex_adapter_builds_official_bounded_exec_command(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
) -> None:
    init_git_repo(tmp_path)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-codex"
    request = RunnerRequest(
        packet_id="packet-codex",
        lane_id="codex",
        repo=tmp_path,
        task="Implement the bounded local change.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = CodexLocalRunnerAdapter(command_prefix=fake_codex_command)

    plan = adapter.prepare(request, packet_dir)
    run_dir = packet_dir / "runner" / "runs" / "preview"
    command = adapter.build_command(request, run_dir)

    assert plan.adapter_available is True
    assert plan.launch_supported is True
    assert plan.mode == "local-codex"
    assert plan.sandbox_policy == "workspace-write"
    assert command[: len(fake_codex_command)] == list(fake_codex_command)
    exec_index = command.index("exec")
    assert exec_index > len(fake_codex_command)
    assert "--ephemeral" in command
    assert "--json" in command
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert command[command.index("--cd") + 1] == str(tmp_path.resolve())
    assert command.index("--sandbox") < exec_index
    assert command.index("--ask-for-approval") < exec_index
    assert command.index("--cd") < exec_index
    assert command.index("--ephemeral") > exec_index
    assert command.index("--json") > exec_index
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "danger-full-access" not in command
    assert command[-1] == request.task


def test_hermes_discovery_and_probe_support_safe_local_override(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    monkeypatch.setenv("HAMILTONIAN_HERMES_COMMAND", json.dumps(list(fake_hermes_command)))

    assert _configured_hermes_command() == fake_hermes_command
    probe = probe_hermes_command(tmp_path)
    assert probe.available is True
    assert probe.command_prefix == fake_hermes_command
    assert "Hermes Agent 9.9.9-test" in probe.detail

    unavailable = probe_hermes_command(tmp_path, (str(tmp_path / "missing-hermes"),))
    assert unavailable.available is False
    assert "probe failed" in unavailable.detail.lower()


def test_hermes_integration_status_requires_successful_version_probe(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
    monkeypatch,
) -> None:
    _cached_detect_integrations.cache_clear()
    monkeypatch.delenv("HAMILTONIAN_HERMES_COMMAND", raising=False)
    monkeypatch.setattr(
        "hamiltonian.integrations.shutil.which",
        lambda name: fake_hermes_command[1] if name == "hermes" else None,
    )
    monkeypatch.setattr(
        "hamiltonian.integrations._probe",
        lambda command, cwd, include_status=False: ("Hermes probe failed", False)
        if include_status
        else "missing",
    )

    status = next(item for item in detect_integrations(tmp_path) if item.name == "Hermes Agent")

    assert status.available is False
    assert status.detail == "Hermes probe failed"
    _cached_detect_integrations.cache_clear()


def test_hermes_adapter_builds_official_safe_one_shot_command(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
) -> None:
    init_git_repo(tmp_path)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-hermes"
    request = RunnerRequest(
        packet_id="packet-hermes",
        lane_id="hermes",
        repo=tmp_path,
        task="Review the bounded local change.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = HermesLocalRunnerAdapter(command_prefix=fake_hermes_command)

    plan = adapter.prepare(request, packet_dir)
    command = adapter.build_command(request, packet_dir / "runner" / "runs" / "preview")

    assert plan.adapter_available is True
    assert plan.launch_supported is True
    assert plan.mode == "local-hermes-one-shot"
    assert plan.sandbox_policy == "hermes-safe-mode-checkpoints"
    assert command[: len(fake_hermes_command)] == list(fake_hermes_command)
    assert "--safe-mode" in command
    assert command[command.index("--source") + 1] == "tool"
    assert command[command.index("--max-turns") + 1] == "24"
    assert "--checkpoints" in command
    assert "-z" in command
    assert command[-1].endswith(request.task)
    assert str(tmp_path.resolve()) not in command[-1]
    assert "--yolo" not in command
    assert "gateway" not in command[:-1]
    assert "deliver" not in command[:-1]


def test_hermes_unavailable_falls_back_to_non_launching_plan(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    request = RunnerRequest(
        packet_id="packet-hermes-missing",
        lane_id="hermes",
        repo=tmp_path,
        task="Review the local packet.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = HermesLocalRunnerAdapter(command_prefix=(str(tmp_path / "missing-hermes"),))

    plan = adapter.prepare(request, tmp_path / ".hamiltonian" / "tasks" / request.packet_id)

    assert plan.status == "prepared"
    assert plan.adapter_available is False
    assert plan.launch_supported is False
    assert plan.local_execution is False
    assert plan.remote_execution is False


def test_local_run_manager_captures_hermes_one_shot_response(
    tmp_path: Path,
    fake_hermes_command: tuple[str, ...],
) -> None:
    init_git_repo(tmp_path)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-hermes-success"
    request = RunnerRequest(
        packet_id="packet-hermes-success",
        lane_id="hermes",
        repo=tmp_path,
        task="Complete the synthetic Hermes run.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = HermesLocalRunnerAdapter(command_prefix=fake_hermes_command)
    plan = adapter.prepare(request, packet_dir)
    manager = LocalRunManager()

    manager.start(adapter, request, plan, packet_dir, timeout_seconds=10)
    completed = wait_for_terminal_run(manager, packet_dir)

    assert completed["status"] == "succeeded"
    assert completed["adapter_id"] == "hermes-local"
    assert completed["lane_id"] == "hermes"
    assert completed["last_message"] == "Synthetic Hermes Agent run completed locally."
    assert completed["local_execution"] is True
    assert completed["remote_execution"] is False
    assert Path(completed["output_path"]).name == "runner-output.log"
    assert completed["result_receipt"]["schema"] == RUNNER_RESULT_SCHEMA
    assert completed["result_receipt"]["lane_id"] == "hermes"
    assert completed["result_receipt"]["result_included"] is False
    assert any(event["type"] == "runner.succeeded" for event in completed["events"])


def test_local_run_manager_streams_sanitized_events_and_report(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
) -> None:
    init_git_repo(tmp_path)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-success"
    request = RunnerRequest(
        packet_id="packet-success",
        lane_id="codex",
        repo=tmp_path,
        task="Complete the synthetic bounded run.",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = CodexLocalRunnerAdapter(command_prefix=fake_codex_command)
    plan = adapter.prepare(request, packet_dir)
    manager = LocalRunManager()

    started = manager.start(adapter, request, plan, packet_dir, timeout_seconds=10)
    completed = wait_for_terminal_run(manager, packet_dir)

    assert started["status"] in {"running", "succeeded"}
    assert completed["status"] == "succeeded"
    assert completed["local_execution"] is True
    assert completed["remote_execution"] is False
    assert completed["exit_code"] == 0
    assert completed["timed_out"] is False
    assert completed["last_message"] == "Synthetic Codex run completed locally."
    event_text = json.dumps(completed["events"])
    assert "private command" not in event_text
    assert "private final text" not in event_text
    assert "command_execution" in event_text
    assert any(event["type"] == "runner.succeeded" for event in completed["events"])
    assert Path(completed["report_path"]).exists()
    receipt = completed["result_receipt"]
    assert receipt["schema"] == RUNNER_RESULT_SCHEMA
    assert receipt["lane_id"] == "codex"
    assert receipt["status"] == "succeeded"
    assert receipt["result_available"] is True
    assert receipt["result_length"] == len("Synthetic Codex run completed locally.")
    assert receipt["result_included"] is False
    assert receipt["remote_execution"] is False
    stored_receipt = Path(completed["result_receipt_path"]).read_text(encoding="utf-8")
    assert "Synthetic Codex run completed locally." not in stored_receipt
    assert read_latest_runner_state(packet_dir)["status"] == "succeeded"


def test_local_run_manager_cancels_process_tree(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
) -> None:
    init_git_repo(tmp_path)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-cancel"
    request = RunnerRequest(
        packet_id="packet-cancel",
        lane_id="codex",
        repo=tmp_path,
        task="WAIT_FOR_CANCEL",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = CodexLocalRunnerAdapter(command_prefix=fake_codex_command)
    plan = adapter.prepare(request, packet_dir)
    manager = LocalRunManager()

    manager.start(adapter, request, plan, packet_dir, timeout_seconds=20)
    cancelling = manager.cancel(packet_dir)
    completed = wait_for_terminal_run(manager, packet_dir)

    assert cancelling["status"] in {"cancelling", "cancelled"}
    assert completed["status"] == "cancelled"
    assert completed["cancel_requested"] is True
    assert completed["remote_execution"] is False


def test_local_run_manager_enforces_timeout(
    tmp_path: Path,
    fake_codex_command: tuple[str, ...],
    monkeypatch,
) -> None:
    init_git_repo(tmp_path)
    monkeypatch.setattr("hamiltonian.runners.MIN_RUN_TIMEOUT_SECONDS", 1)
    packet_dir = tmp_path / ".hamiltonian" / "tasks" / "packet-timeout"
    request = RunnerRequest(
        packet_id="packet-timeout",
        lane_id="codex",
        repo=tmp_path,
        task="WAIT_FOR_TIMEOUT",
        gate_status="execution-ready",
        blocked_gate_ids=(),
        attach_evidence=False,
    )
    adapter = CodexLocalRunnerAdapter(command_prefix=fake_codex_command)
    plan = adapter.prepare(request, packet_dir)
    manager = LocalRunManager()

    manager.start(adapter, request, plan, packet_dir, timeout_seconds=1)
    completed = wait_for_terminal_run(manager, packet_dir)

    assert completed["status"] == "timed-out"
    assert completed["timed_out"] is True
    assert completed["duration_seconds"] < 5
    assert completed["remote_execution"] is False
