from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .core import control_run, doctor
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

    return parser


def normalize_remainder(remainder: list[str]) -> list[str]:
    if remainder and remainder[0] == "--":
        return remainder[1:]
    return remainder


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

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
