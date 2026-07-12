from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
import ctypes
import json
import os
from pathlib import Path
import re
import sys
import threading
import traceback
from types import ModuleType
from typing import Any

from . import __version__
from .core import ensure_repo, write_text
from .goals import ensure_local_state_excluded, goal_workspace_summary
from .server import create_cockpit_server


RECENTS_SCHEMA = "hamiltonian.desktop-recents.v1"
CRASH_SCHEMA = "hamiltonian.desktop-crash.v1"
MUTEX_NAME = "Local\\HamiltonianDesktop"
MAX_RECENT_WORKSPACES = 8


@dataclass(frozen=True)
class DesktopResult:
    repo: str | None
    data_dir: str
    url: str | None
    renderer: str
    remote_execution: bool
    closed_cleanly: bool


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def select_workspace(initial_dir: Path | None = None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError("The native repository picker is unavailable.") from exc

    if initial_dir is None:
        preferred = Path("D:/Codex/Projects")
        initial_dir = preferred if preferred.exists() else Path.cwd()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=str(initial_dir),
            title="Choose a repository for Hamiltonian",
            mustexist=True,
        )
    finally:
        root.destroy()
    return ensure_repo(Path(selected)) if selected else None


def desktop_data_dir(repo: Path | None, requested: Path | None = None) -> Path:
    if requested is not None:
        target = requested
    elif os.environ.get("HAMILTONIAN_HOME"):
        target = Path(os.environ["HAMILTONIAN_HOME"])
    elif getattr(sys, "frozen", False):
        target = Path(sys.executable).resolve().parent / "data"
    elif repo is not None:
        target = repo / ".hamiltonian" / "desktop"
    else:
        preferred = Path("D:/Codex/Data/Hamiltonian")
        target = preferred if preferred.drive and Path(f"{preferred.drive}/").exists() else Path.cwd() / ".hamiltonian" / "desktop"
    resolved = target.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def recent_workspaces_path(data_dir: Path) -> Path:
    return data_dir / "recent-workspaces.json"


def load_recent_workspaces(data_dir: Path) -> list[dict[str, Any]]:
    path = recent_workspaces_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or payload.get("schema") != RECENTS_SCHEMA:
        return []
    entries = payload.get("workspaces")
    if not isinstance(entries, list):
        return []
    recent: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_path = str(entry.get("path") or "").strip()
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser().resolve()
        key = os.path.normcase(str(candidate))
        if key in seen or not candidate.is_dir():
            continue
        seen.add(key)
        recent.append(
            {
                "path": str(candidate),
                "name": candidate.name or str(candidate),
                "last_opened": str(entry.get("last_opened") or ""),
                "goal_summary": goal_workspace_summary(candidate),
            }
        )
        if len(recent) >= MAX_RECENT_WORKSPACES:
            break
    return recent


def remember_workspace(data_dir: Path, repo: Path) -> list[dict[str, Any]]:
    resolved = ensure_repo(repo)
    key = os.path.normcase(str(resolved))
    existing = [
        item
        for item in load_recent_workspaces(data_dir)
        if os.path.normcase(item["path"]) != key
    ]
    workspaces = [
        {
            "path": str(resolved),
            "name": resolved.name or str(resolved),
            "last_opened": _utc_now(),
        },
        *[
            {
                "path": item["path"],
                "name": item["name"],
                "last_opened": item["last_opened"],
            }
            for item in existing
        ],
    ][:MAX_RECENT_WORKSPACES]
    write_text(
        recent_workspaces_path(data_dir),
        json.dumps({"schema": RECENTS_SCHEMA, "workspaces": workspaces}, indent=2) + "\n",
    )
    return load_recent_workspaces(data_dir)


def desktop_launcher_html(data_dir: Path) -> str:
    template_path = resources.files("hamiltonian").joinpath("web", "desktop-launcher.html")
    template = template_path.read_text(encoding="utf-8")
    recents = json.dumps(load_recent_workspaces(data_dir)).replace("</", "<\\/")
    return template.replace("__HAMILTONIAN_RECENTS__", recents).replace(
        "__HAMILTONIAN_VERSION__", __version__
    )


def _sanitize_crash_message(value: str) -> str:
    message = value.replace("\r", " ").replace("\n", " ")[:500]
    message = re.sub(
        r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        message,
    )
    message = re.sub(r"(?i)(?:[a-z]:\\|/)[^\s\"']+", "<local-path>", message)
    return message


def write_desktop_crash_report(
    data_dir: Path,
    error: BaseException,
    repo: Path | None = None,
) -> Path:
    timestamp = datetime.now(timezone.utc)
    crash_id = timestamp.strftime("%Y%m%dT%H%M%SZ-%f")
    frames = traceback.extract_tb(error.__traceback__)[-12:] if error.__traceback__ else []
    payload = {
        "schema": CRASH_SCHEMA,
        "crash_id": crash_id,
        "created_at": timestamp.isoformat(),
        "version": __version__,
        "surface": "desktop",
        "exception_type": type(error).__name__,
        "message": _sanitize_crash_message(str(error)),
        "workspace_name": repo.name if repo else None,
        "stack": [
            {
                "module": Path(frame.filename).stem,
                "function": frame.name,
                "line": frame.lineno,
            }
            for frame in frames
        ],
        "sanitized": True,
        "local_only": True,
        "remote_execution": False,
    }
    path = data_dir / "crashes" / f"crash-{crash_id}.json"
    write_text(path, json.dumps(payload, indent=2) + "\n")
    return path


class SingleInstanceLock:
    def __init__(self, name: str = MUTEX_NAME) -> None:
        self.name = name
        self._handle: int | None = None
        self._kernel32: Any | None = None

    def acquire(self) -> None:
        if os.name != "nt":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_bool
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise RuntimeError("Hamiltonian could not create its single-instance lock.")
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(handle)
            raise RuntimeError("Hamiltonian is already open.")
        self._kernel32 = kernel32
        self._handle = int(handle)

    def release(self) -> None:
        if self._handle and self._kernel32:
            self._kernel32.CloseHandle(ctypes.c_void_p(self._handle))
        self._handle = None
        self._kernel32 = None


class DesktopSession:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.repo: Path | None = None
        self.url: str | None = None
        self._server: Any | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def activate_workspace(self, repo_path: Path) -> dict[str, Any]:
        repo = ensure_repo(repo_path)
        with self._lock:
            if self.repo is not None and repo != self.repo:
                raise RuntimeError(f"This window is already locked to {self.repo}.")
            if self.url:
                return {"ok": True, "url": self.url, "repo": str(repo), "repo_name": repo.name}
            ensure_local_state_excluded(repo)
            server = create_cockpit_server(
                repo,
                host="127.0.0.1",
                port=0,
                strict_repo=True,
            )
            host, port = server.server_address[:2]
            thread = threading.Thread(
                target=server.serve_forever,
                name="hamiltonian-cockpit",
                daemon=True,
            )
            thread.start()
            self.repo = repo
            self.url = f"http://{host}:{port}/"
            self._server = server
            self._thread = thread
            remember_workspace(self.data_dir, repo)
            return {
                "ok": True,
                "url": self.url,
                "repo": str(repo),
                "repo_name": repo.name,
                "remote_execution": False,
            }

    def open_workspace(self, path: str) -> dict[str, Any]:
        try:
            return self.activate_workspace(Path(path))
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def choose_workspace(self) -> dict[str, Any]:
        try:
            initial = self.repo.parent if self.repo else None
            selected = select_workspace(initial)
            if selected is None:
                return {"ok": False, "cancelled": True}
            return self.activate_workspace(selected)
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def close(self) -> bool:
        with self._lock:
            if self._server is not None:
                self._server.shutdown()
                self._server.server_close()
            if self._thread is not None:
                self._thread.join(timeout=5)
            closed = self._thread is None or not self._thread.is_alive()
            self._server = None
            self._thread = None
            return closed


def _load_webview() -> ModuleType:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Hamiltonian desktop support is not installed. Install the desktop extra with "
            "'python -m pip install -e .[desktop]'."
        ) from exc
    return webview


def run_desktop(
    repo_path: Path | None = None,
    *,
    data_dir: Path | None = None,
    debug: bool = False,
    webview_module: ModuleType | None = None,
    single_instance: bool = True,
) -> DesktopResult:
    repo = ensure_repo(repo_path) if repo_path is not None else None
    storage_root = desktop_data_dir(repo, data_dir)
    webview = webview_module or _load_webview()
    instance_lock = SingleInstanceLock()
    if single_instance:
        instance_lock.acquire()
    session = DesktopSession(storage_root)
    closed_cleanly = True
    try:
        initial = session.activate_workspace(repo) if repo is not None else None
        window_options: dict[str, Any] = {
            "js_api": session,
            "width": 1440,
            "height": 900,
            "min_size": (960, 640),
            "background_color": "#080a0d",
            "resizable": True,
            "zoomable": True,
        }
        if initial:
            window_options["url"] = initial["url"]
            title = f"Hamiltonian | {repo.name}"
        else:
            window_options["html"] = desktop_launcher_html(storage_root)
            title = "Hamiltonian"
        webview.create_window(title, **window_options)
        start_options: dict[str, Any] = {
            "debug": debug,
            "private_mode": True,
            "storage_path": str(storage_root / "webview"),
        }
        if os.name == "nt":
            start_options["gui"] = "edgechromium"
        webview.start(**start_options)
    except Exception as exc:
        try:
            write_desktop_crash_report(storage_root, exc, session.repo)
        except OSError:
            pass
        raise
    finally:
        closed_cleanly = session.close()
        instance_lock.release()
    return DesktopResult(
        repo=str(session.repo) if session.repo else None,
        data_dir=str(storage_root),
        url=session.url,
        renderer="edgechromium" if os.name == "nt" else "default",
        remote_execution=False,
        closed_cleanly=closed_cleanly,
    )
