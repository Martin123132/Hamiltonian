from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from .core import control_run, doctor
from .packets import (
    AGENTS,
    STAGES,
    create_task_packet,
    export_handoff_markdown,
    get_task_packet,
    list_task_packets,
    write_task_index,
)
from .server import run_cockpit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hamiltonian",
        description="Hamiltonian: flight software for agentic systems.",
    )
    sub = parser.add_subparsers(dest="command_name", required=True)

    run_p = sub.add_parser("run", help="run a command with flight-control evidence")
    run_p.add_argument("--repo", default=".", help="repository/workspace path")
    run_p.add_argument("--out", default=None, help="output root for run packets")
    run_p.add_argument("--timeout", type=int, default=900, help="command timeout in seconds")
    run_p.add_argument(
        "--runner",
        choices=("direct", "agentledger"),
        default="direct",
        help="command runner to use for the wrapped command",
    )
    run_p.add_argument(
        "--no-respect-jester-blocks",
        action="store_true",
        help="record Jester BLOCK verdicts but still run the command",
    )
    run_p.add_argument("agent_command", nargs=argparse.REMAINDER, help="command after --")

    doctor_p = sub.add_parser("doctor", help="inspect repo and optional integrations")
    doctor_p.add_argument("--repo", default=".", help="repository/workspace path")
    doctor_p.add_argument("--json", action="store_true", help="print JSON")

    cockpit_p = sub.add_parser("cockpit", help="start the local Hamiltonian cockpit")
    cockpit_p.add_argument("--repo", default=".", help="repository/workspace path")
    cockpit_p.add_argument("--host", default="127.0.0.1", help="host to bind")
    cockpit_p.add_argument("--port", type=int, default=8765, help="port to bind")

    packets_p = sub.add_parser("packets", help="inspect local task packets")
    packets_p.add_argument("--repo", default=".", help="repository/workspace path")
    packets_sub = packets_p.add_subparsers(dest="packets_command", required=True)

    packets_create_p = packets_sub.add_parser("create", help="create a local task packet")
    packets_create_p.add_argument("--task", required=True, help="operator task text")
    packets_create_p.add_argument(
        "--agent",
        "--agent-id",
        dest="agent_id",
        choices=sorted(AGENTS),
        default="codex",
        help="agent lane to assign",
    )
    packets_create_p.add_argument(
        "--stage",
        choices=sorted(STAGES),
        default="draft",
        help="packet lifecycle stage",
    )
    packets_create_p.add_argument(
        "--attach-evidence",
        action="store_true",
        help="represent optional AgentLedger evidence without executing agents",
    )
    packets_create_p.add_argument("--json", action="store_true", help="print JSON")

    packets_list_p = packets_sub.add_parser("list", help="list recent task packets")
    packets_list_p.add_argument("--limit", type=int, default=8, help="maximum packets to show")
    packets_list_p.add_argument("--json", action="store_true", help="print JSON")

    packets_rebuild_p = packets_sub.add_parser(
        "rebuild-index",
        help="rebuild the local task packet index",
    )
    packets_rebuild_p.add_argument("--json", action="store_true", help="print JSON")

    packets_detail_p = packets_sub.add_parser("detail", help="show full packet detail")
    packets_detail_p.add_argument("packet_id", help="packet id")
    packets_detail_p.add_argument("--json", action="store_true", help="print JSON")

    packets_export_p = packets_sub.add_parser("export", help="write sanitized handoff markdown")
    packets_export_p.add_argument("packet_id", help="packet id")
    packets_export_p.add_argument("--json", action="store_true", help="print JSON")

    return parser


def normalize_remainder(remainder: list[str]) -> list[str]:
    if remainder and remainder[0] == "--":
        return remainder[1:]
    return remainder


def print_packet_summary(packet: dict[str, object]) -> None:
    print(f"Packet: {packet.get('packet_id')}")
    print(f"Stage: {packet.get('stage')}")
    print(f"Status: {packet.get('status')}")
    print(f"Agent: {packet.get('agent_name')}")
    print(f"Task: {packet.get('task_excerpt') or packet.get('task')}")


def print_packet_detail(packet: dict[str, object]) -> None:
    lane = packet.get("lane") if isinstance(packet.get("lane"), dict) else {}
    gate_run = packet.get("gate_run") if isinstance(packet.get("gate_run"), dict) else {}
    execution = packet.get("execution_boundary") if isinstance(packet.get("execution_boundary"), dict) else {}
    handoff = packet.get("handoff") if isinstance(packet.get("handoff"), dict) else {}
    gates = packet.get("gates") if isinstance(packet.get("gates"), list) else []

    print(f"Packet: {packet.get('packet_id')}")
    print(f"Stage: {packet.get('stage')}")
    print(f"Status: {packet.get('status')}")
    print(f"Agent: {packet.get('agent_name')}")
    print(f"Lane: {lane.get('status', 'unknown')} / {lane.get('execution', 'unknown')}")
    print(f"Gate run: {gate_run.get('status', 'unknown')} ({gate_run.get('completed', 0)}/{gate_run.get('total', 0)})")
    print(f"Execution: {execution.get('status', 'unknown')} / {execution.get('mode', 'unknown')}")
    print(f"Handoff: {handoff.get('status', 'unknown')} / {'ready' if handoff.get('ready') else 'not ready'}")
    print(f"Task: {packet.get('task')}")
    print("Gates:")
    for gate in gates:
        if isinstance(gate, dict):
            print(f"- {gate.get('name')}: {gate.get('status')} ({gate.get('mode')})")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command_name == "doctor":
        data = doctor(Path(args.repo))
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"Repo: {data['repo']}")
            print("Integrations:")
            for item in data["integrations"]:
                state = "ok" if item["available"] else "missing"
                print(f"- {item['name']}: {state} ({item['detail']})")
        return 0

    if args.command_name == "run":
        command = normalize_remainder(args.agent_command)
        run = control_run(
            repo_path=Path(args.repo),
            command=command or None,
            out_root=Path(args.out) if args.out else None,
            timeout=args.timeout,
            respect_jester_blocks=not args.no_respect_jester_blocks,
            runner=args.runner,
        )
        print(f"Hamiltonian verdict: {run.verdict}")
        print(f"Report: {Path(run.out_dir) / 'hamiltonian-report.md'}")
        return 0 if run.verdict in {"pass", "warn"} else 2

    if args.command_name == "cockpit":
        run_cockpit(Path(args.repo), host=args.host, port=args.port)
        return 0

    if args.command_name == "packets":
        try:
            if args.packets_command == "create":
                packet = create_task_packet(
                    repo_path=Path(args.repo),
                    task=args.task,
                    agent_id=args.agent_id,
                    stage=args.stage,
                    attach_evidence=args.attach_evidence,
                )
                packet_data = asdict(packet)
                if args.json:
                    print(json.dumps({"packet": packet_data}, indent=2))
                else:
                    print_packet_summary(packet_data)
                return 0

            if args.packets_command == "list":
                packets = list_task_packets(Path(args.repo), limit=args.limit)
                if args.json:
                    print(json.dumps({"packets": packets}, indent=2))
                else:
                    if not packets:
                        print("No packets found.")
                    for packet in packets:
                        print_packet_summary(packet)
                        print()
                return 0

            if args.packets_command == "rebuild-index":
                index = write_task_index(Path(args.repo))
                if args.json:
                    print(json.dumps({"index": index}, indent=2))
                else:
                    print(f"Rebuilt packet index: {index['packet_count']} packets")
                return 0

            if args.packets_command == "detail":
                packet = get_task_packet(Path(args.repo), args.packet_id)
                if args.json:
                    print(json.dumps({"packet": packet}, indent=2))
                else:
                    print_packet_detail(packet)
                return 0

            if args.packets_command == "export":
                result = export_handoff_markdown(Path(args.repo), args.packet_id)
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"Export: {result['export']['path']}")
                    print("Sanitized: true")
                return 0
        except (FileNotFoundError, ValueError) as exc:
            print(f"hamiltonian packets: {exc}", file=sys.stderr)
            return 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
