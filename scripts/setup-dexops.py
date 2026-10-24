"""Install and start the source companion with a standard Python interpreter."""
import argparse
from pathlib import Path
import subprocess
import sys
import venv


def main():
    parser = argparse.ArgumentParser(description="Set up Dexops from the extracted source package")
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        parser.error("Install Python 3.10 or newer from python.org first.")
    root = Path(__file__).resolve().parents[1]
    runtime = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not runtime.exists():
        print("Creating the Dexops Python environment...", flush=True)
        venv.EnvBuilder(with_pip=True).create(root / ".venv")
    subprocess.run([str(runtime), "-m", "pip", "install", "-e", str(root) + "[gateway]"], check=True)
    print("Dexops is installed. Keep this window open while using your robot.", flush=True)
    if not args.install_only:
        subprocess.run([str(runtime), "-m", "t2_bots.connect.app", "--workspace-url",
                        "https://servosocialruss.vercel.app/"], check=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        print("Dexops setup failed: " + str(exc), file=sys.stderr)
        sys.exit(1)
