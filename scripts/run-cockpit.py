from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from hamiltonian.server import run_cockpit  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Hamiltonian cockpit from source.")
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run_cockpit(Path(args.repo), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
