from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from hamiltonian.desktop import run_desktop  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hamiltonian in a native desktop window.")
    parser.add_argument("--repo", default=None, help="repository path; omit to use the folder picker")
    parser.add_argument("--data-dir", default=None, help="desktop state directory")
    parser.add_argument("--debug", action="store_true", help="enable WebView developer tools")
    args = parser.parse_args()
    try:
        result = run_desktop(
            Path(args.repo) if args.repo else None,
            data_dir=Path(args.data_dir) if args.data_dir else None,
            debug=args.debug,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Hamiltonian desktop: {exc}", file=sys.stderr)
        return 2
    return 0 if result.closed_cleanly else 2


if __name__ == "__main__":
    raise SystemExit(main())
