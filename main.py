"""Compatibility entry point for the shared directory service."""

from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent / "dexops/src"))
    runpy.run_module("t2_bots.connect.directory", run_name="__main__")
