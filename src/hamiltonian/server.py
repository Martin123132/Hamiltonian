from __future__ import annotations

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .core import ensure_repo, is_git_repo
from .goals import (
    create_corrective_goal,
    create_goal_package,
    list_goal_packages,
    open_codex_workspace,
    preview_goal_package,
    save_goal_review,
)
from .integrations import detect_integrations
from .packets import (
    AGENTS,
    advance_task_packet,
    build_route_recommendations,
    create_task_packet,
    export_handoff_markdown,
    get_task_packet,
    list_task_packets,
    select_task_packet_lane,
)
from .runtime import runtime_state_dict
from .runners import (
    DEFAULT_RUN_TIMEOUT_SECONDS,
    LocalRunManager,
    cancel_packet_run,
    get_packet_run,
    start_packet_run,
)


class CockpitHandler(SimpleHTTPRequestHandler):
    repo: Path
    static_root: Path
    strict_repo = False
    run_manager = LocalRunManager()

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _requested_repo(self, value: str | None = None) -> Path:
        candidate = ensure_repo(Path(value or str(self.repo)))
        if self.strict_repo and candidate != self.repo:
            raise ValueError(
                f"desktop session is locked to {self.repo}; requested workspace was {candidate}"
            )
        return candidate

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._write_json(
                {
                    "ok": True,
                    "version": __version__,
                    "surface": "desktop" if self.strict_repo else "browser",
                    "workspace_locked": self.strict_repo,
                    "remote_execution": False,
                    "update_policy": "manual-local-package",
                    "diagnostics": "sanitized-local-only",
                }
            )
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                self._write_json(runtime_state_dict(repo))
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/packets":
            query = parse_qs(parsed.query)
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                self._write_json({"packets": list_task_packets(repo)})
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/goals":
            query = parse_qs(parsed.query)
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                self._write_json({"goals": list_goal_packages(repo)})
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/run"):
            query = parse_qs(parsed.query)
            packet_id = unquote(
                parsed.path.removeprefix("/api/packets/").removesuffix("/run")
            ).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                packet = get_task_packet(repo, packet_id)
                self._write_json({"run": get_packet_run(self.run_manager, repo, packet)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/"):
            query = parse_qs(parsed.query)
            packet_id = unquote(parsed.path.removeprefix("/api/packets/"))
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                self._write_json({"packet": get_task_packet(repo, packet_id)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/goals/") and parsed.path.endswith("/review"):
            goal_id = unquote(
                parsed.path.removeprefix("/api/goals/").removesuffix("/review")
            ).strip("/")
            try:
                payload = self._read_json()
                repo = self._requested_repo(str(payload.get("repo") or str(self.repo)))
                review = save_goal_review(
                    repo_path=repo,
                    goal_id=goal_id,
                    report=str(payload.get("report") or ""),
                    source_packet_id=str(payload.get("source_packet_id") or "") or None,
                )
                self._write_json({"review": review, "goals": list_goal_packages(repo)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/goals/") and parsed.path.endswith("/corrective"):
            goal_id = unquote(
                parsed.path.removeprefix("/api/goals/").removesuffix("/corrective")
            ).strip("/")
            try:
                payload = self._read_json()
                package = create_corrective_goal(
                    self._requested_repo(str(payload.get("repo") or str(self.repo))),
                    goal_id,
                )
                self._write_json({"goal": packet_to_dict(package)}, status=HTTPStatus.CREATED)
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/goals/preview":
            try:
                payload = self._read_json()
                package = preview_goal_package(
                    repo_path=self._requested_repo(str(payload.get("repo") or str(self.repo))),
                    goal_type=str(payload.get("goal_type") or "maintenance"),
                    source_report=str(payload.get("source_report") or ""),
                    source_packet_id=str(payload.get("source_packet_id") or "") or None,
                    expansion_request=str(payload.get("expansion_request") or "") or None,
                    goal_id=str(payload.get("goal_id") or "") or None,
                    parent_goal_id=str(payload.get("parent_goal_id") or "") or None,
                )
                self._write_json({"goal": packet_to_dict(package)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/goals":
            try:
                payload = self._read_json()
                package = create_goal_package(
                    repo_path=self._requested_repo(str(payload.get("repo") or str(self.repo))),
                    goal_type=str(payload.get("goal_type") or "maintenance"),
                    source_report=str(payload.get("source_report") or ""),
                    source_packet_id=str(payload.get("source_packet_id") or "") or None,
                    expansion_request=str(payload.get("expansion_request") or "") or None,
                    goal_id=str(payload.get("goal_id") or "") or None,
                    parent_goal_id=str(payload.get("parent_goal_id") or "") or None,
                )
                self._write_json({"goal": packet_to_dict(package)}, status=HTTPStatus.CREATED)
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/codex/open":
            try:
                payload = self._read_json()
                result = open_codex_workspace(
                    self._requested_repo(str(payload.get("repo") or str(self.repo)))
                )
                self._write_json(result)
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/routes":
            try:
                payload = self._read_json()
                repo = self._requested_repo(str(payload.get("repo") or str(self.repo)))
                agent_id = str(payload.get("agent_id") or "codex").lower().strip()
                if agent_id not in AGENTS:
                    raise ValueError(f"unknown agent lane: {agent_id}")
                routes = build_route_recommendations(
                    task=str(payload.get("task") or ""),
                    selected_agent_id=agent_id,
                    git_available=(repo / ".git").exists() and is_git_repo(repo),
                    integrations=detect_integrations(repo),
                )
                self._write_json(
                    {
                        "route_recommendations": routes,
                        "selected_agent_id": agent_id,
                    }
                )
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/run/cancel"):
            query = parse_qs(parsed.query)
            packet_id = unquote(
                parsed.path.removeprefix("/api/packets/").removesuffix("/run/cancel")
            ).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                packet = get_task_packet(repo, packet_id)
                run = cancel_packet_run(self.run_manager, repo, packet)
                self._write_json({"run": run})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/run"):
            query = parse_qs(parsed.query)
            packet_id = unquote(
                parsed.path.removeprefix("/api/packets/").removesuffix("/run")
            ).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                payload = self._read_json()
                timeout_seconds = int(payload.get("timeout_seconds") or DEFAULT_RUN_TIMEOUT_SECONDS)
                packet = get_task_packet(repo, packet_id)
                run = start_packet_run(
                    self.run_manager,
                    repo,
                    packet,
                    timeout_seconds=timeout_seconds,
                )
                self._write_json({"run": run}, status=HTTPStatus.CREATED)
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/advance"):
            query = parse_qs(parsed.query)
            packet_id = unquote(
                parsed.path.removeprefix("/api/packets/").removesuffix("/advance")
            ).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                payload = self._read_json()
                packet = advance_task_packet(
                    repo_path=repo,
                    packet_id=packet_id,
                    stage=str(payload.get("stage") or ""),
                    attach_evidence=bool(payload.get("attach_evidence", False)),
                )
                self._write_json({"packet": packet_to_dict(packet)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/lane"):
            query = parse_qs(parsed.query)
            packet_id = unquote(
                parsed.path.removeprefix("/api/packets/").removesuffix("/lane")
            ).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                payload = self._read_json()
                packet = select_task_packet_lane(
                    repo_path=repo,
                    packet_id=packet_id,
                    agent_id=str(payload.get("agent_id") or ""),
                )
                self._write_json({"packet": packet_to_dict(packet)})
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path.startswith("/api/packets/") and parsed.path.endswith("/export"):
            query = parse_qs(parsed.query)
            packet_id = unquote(parsed.path.removeprefix("/api/packets/").removesuffix("/export")).strip("/")
            try:
                repo = self._requested_repo(query.get("repo", [str(self.repo)])[0])
                self._write_json(export_handoff_markdown(repo, packet_id), status=HTTPStatus.CREATED)
            except ValueError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            except FileNotFoundError as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path != "/api/packets":
            self._write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            repo = self._requested_repo(str(payload.get("repo") or str(self.repo)))
            mode = str(payload.get("mode") or "").strip().lower()
            is_recorder_mode = mode == "recorder"
            agent_id = "codex" if is_recorder_mode else str(payload.get("agent_id") or "codex")
            stage = str(payload.get("stage") or "gate").lower().strip()
            if is_recorder_mode:
                stage = "record"
            packet = create_task_packet(
                repo_path=repo,
                task=str(payload.get("task") or ""),
                agent_id=agent_id,
                stage=stage,
                attach_evidence=True if is_recorder_mode else bool(payload.get("attach_evidence", False)),
            )
        except ValueError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._write_json({"packet": packet_to_dict(packet)}, status=HTTPStatus.CREATED)

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        relative = parsed.path.lstrip("/") or "index.html"
        target = (self.static_root / relative).resolve()
        root = self.static_root.resolve()
        if root not in target.parents and target != root:
            return str(root / "index.html")
        if target.is_dir():
            return str(target / "index.html")
        return str(target)

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length > 131_072:
            raise ValueError("request body is too large")
        data = self.rfile.read(length)
        if not data:
            return {}
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload


def packet_to_dict(packet: Any) -> dict[str, Any]:
    if hasattr(packet, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(packet)
    return dict(packet)


def create_cockpit_server(
    repo: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    strict_repo: bool = False,
) -> ThreadingHTTPServer:
    static_root = Path(str(resources.files("hamiltonian").joinpath("web")))

    class Handler(CockpitHandler):
        pass

    Handler.repo = ensure_repo(repo)
    Handler.static_root = static_root
    Handler.strict_repo = strict_repo
    Handler.run_manager = LocalRunManager()
    return ThreadingHTTPServer((host, port), Handler)


def run_cockpit(repo: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_cockpit_server(repo, host=host, port=port)
    bound_host, bound_port = server.server_address[:2]

    url = f"http://{bound_host}:{bound_port}"
    print(f"Hamiltonian cockpit: {url}")
    print(f"Repo: {repo.resolve()}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
