"""Keep the existing root setup command pointing at the maintained app."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "dexops/scripts/setup-dexops.py"), run_name="__main__")
