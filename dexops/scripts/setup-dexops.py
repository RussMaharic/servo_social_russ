"""Register this checkout, reuse its environment, and open the hosted workspace."""
import argparse
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up or reuse this Dexops checkout")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--workspace-url", default="https://servosocialruss.vercel.app")
    parser.add_argument("--autostart", action=argparse.BooleanOptionalAction, default=None)
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Install Python 3.10 or newer from python.org first.")
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from t2_bots.connect import installation as installs
    with installs.installation_lock():
        if not args.install_only:
            installs.assert_idle(installs.probe_service())
        old = installs.read_record(repair=True)
        record = installs.install_local(root, args.workspace_url, args.autostart)
        if not args.install_only:
            from t2_bots.connect.runtime import source_build_id
            running = installs.probe_service()
            if running and running.get("runtime", {}).get("build_id") != source_build_id():
                installs.stop_service()
            from t2_bots.connect.cli import start
            try:
                start(record)
            except Exception:
                if old:
                    installs.save_record(old)
                    start(old, no_browser=True)
                    installs.register_commands(old)
                    from t2_bots.connect.startup import configure
                    configure(old, old.get("autostart", False))
                raise
    command = installs.install_home() / "bin" / ("dexops.cmd" if sys.platform == "win32" else "dexops")
    print("Dexops installation reused or prepared successfully.")
    print("In new terminals use: dexops")
    print("In this terminal you can use: " + ("& '" + str(command).replace("'", "''") + "'" if sys.platform == "win32" else str(command)))
    if record.get("autostart_error"):
        print("Start at sign-in was not enabled: " + record["autostart_error"])


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Dexops setup: " + str(exc), file=sys.stderr)
        sys.exit(1)
