from __future__ import annotations

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .packets import create_task_packet, list_task_packets
from .runtime import runtime_state_dict


class CockpitHandler(SimpleHTTPRequestHandler):
    repo: Path
    static_root: Path

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self._write_json({"ok": True})
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            repo = Path(query.get("repo", [str(self.repo)])[0])
            try:
                self._write_json(runtime_state_dict(repo))
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/packets":
            query = parse_qs(parsed.query)
            repo = Path(query.get("repo", [str(self.repo)])[0])
            try:
                self._write_json({"packets": list_task_packets(repo)})
            except Exception as exc:
                self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/packets":
            self._write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            repo = Path(payload.get("repo") or str(self.repo))
            packet = create_task_packet(
                repo_path=repo,
                task=str(payload.get("task") or ""),
                agent_id=str(payload.get("agent_id") or "codex"),
                stage=str(payload.get("stage") or "gate"),
                attach_evidence=bool(payload.get("attach_evidence", False)),
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
        if length > 65_536:
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


def run_cockpit(repo: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    static_root = Path(str(resources.files("hamiltonian").joinpath("web")))

    class Handler(CockpitHandler):
        pass

    Handler.repo = repo.resolve()
    Handler.static_root = static_root

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Hamiltonian cockpit: {url}")
    print(f"Repo: {Handler.repo}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
