from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
