from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def fake_codex_command(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "fake_codex.py"
    script.write_text(
        """from __future__ import annotations
import json
from pathlib import Path
import sys
import time

if "--version" in sys.argv:
    print("codex-cli 9.9.9-test")
    raise SystemExit(0)

if "exec" not in sys.argv:
    raise SystemExit(2)

prompt = sys.argv[-1]

def emit(payload):
    print(json.dumps(payload), flush=True)

emit({"type": "thread.started", "thread_id": "synthetic-thread"})
emit({"type": "turn.started"})
emit({"type": "item.started", "item": {"id": "item-1", "type": "command_execution", "command": "private command", "status": "in_progress"}})

if "WAIT_FOR_CANCEL" in prompt:
    time.sleep(30)
if "WAIT_FOR_TIMEOUT" in prompt:
    time.sleep(5)
if "FAIL_RUN" in prompt:
    emit({"type": "turn.failed", "error": {"message": "synthetic failure"}})
    raise SystemExit(3)

if "--output-last-message" in sys.argv:
    output_index = sys.argv.index("--output-last-message") + 1
    Path(sys.argv[output_index]).write_text("Synthetic Codex run completed locally.", encoding="utf-8")

emit({"type": "item.completed", "item": {"id": "item-1", "type": "agent_message", "text": "private final text", "status": "completed"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 120, "cached_input_tokens": 80, "output_tokens": 24, "reasoning_output_tokens": 4}})
""",
        encoding="utf-8",
    )
    return (sys.executable, str(script))


@pytest.fixture
def fake_hermes_command(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "fake_hermes.py"
    script.write_text(
        """from __future__ import annotations
import sys
import time

if "--version" in sys.argv:
    print("Hermes Agent 9.9.9-test")
    raise SystemExit(0)

if "-z" not in sys.argv:
    raise SystemExit(2)

prompt = sys.argv[-1]
if "WAIT_FOR_CANCEL" in prompt:
    time.sleep(30)
if "WAIT_FOR_TIMEOUT" in prompt:
    time.sleep(5)
if "FAIL_RUN" in prompt:
    raise SystemExit(3)

print("Synthetic Hermes Agent run completed locally.", flush=True)
""",
        encoding="utf-8",
    )
    return (sys.executable, str(script))
