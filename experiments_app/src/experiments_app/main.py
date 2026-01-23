import subprocess
import sys
from pathlib import Path


def main() -> None:
    app_path = Path(__file__).resolve().parents[2] / "app.py"
    if not app_path.exists():
        raise SystemExit(f"Experiment app not found: {app_path}")
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    cmd.extend(sys.argv[1:])
    raise SystemExit(subprocess.call(cmd))
