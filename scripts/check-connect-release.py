"""Compatibility entry point for the maintained release checks."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "dexops/scripts/check-connect-release.py"), run_name="__main__")
