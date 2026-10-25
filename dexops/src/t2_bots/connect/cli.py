"""User commands for the registered installation; ordinary start never installs."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import webbrowser

from t2_bots.connect import installation as installs


def start(record, no_browser=False, local=False):
    site = installs.workspace_url(record.get("workspace_url", installs.DEFAULT_WORKSPACE))
    existing = installs.probe_service()
    if existing:
        if existing.get("api_version") != 1 or not existing.get("runtime", {}).get("compatible"):
            raise ValueError("Another incompatible companion is running. Stop its sessions, then run dexops update.")
    else:
        runtime = Path(record["runtime"])
        if not runtime.is_file():
            raise ValueError("The saved Python environment is missing. Run the website's setup command to repair this installation.")
        logs = installs.install_home() / "logs"
        logs.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = logs / "companion.log"
        if output.exists() and output.stat().st_size > 2_000_000:
            output.replace(logs / "companion.previous.log")
        options = {"stdin": subprocess.DEVNULL, "cwd": record["app_root"]}
        if record.get("station_home"):
            options["env"] = {**os.environ, "T2_CONNECT_HOME": os.environ.get("T2_CONNECT_HOME") or record["station_home"]}
        if sys.platform == "win32":
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            options["start_new_session"] = True
        with output.open("ab") as stream:
            process = subprocess.Popen([str(runtime), "-I", "-m", "t2_bots.connect.app", "--no-browser"],
                                       stdout=stream, stderr=stream, **options)
        for _ in range(50):
            if process.poll() is not None:
                raise ValueError("Dexops could not start. Run dexops doctor; details are in " + str(output))
            existing = installs.probe_service()
            if existing:
                break
            time.sleep(.2)
        else:
            # Stop only the process this invocation just created.
            process.terminate()
            raise ValueError("Companion startup timed out. Run dexops doctor.")
    if not no_browser:
        webbrowser.open("http://127.0.0.1:4840/" if local else site + "/")
    print("Dexops is running. The website will detect it automatically.")
    return existing


def doctor(record):
    state = installs.probe_service()
    report = {"registered": bool(record), "service_reachable": state is not None,
              "git_available": shutil.which("git") is not None,
              "autostart": record.get("autostart", False),
              "application_exists": Path(record.get("app_root", "__missing__")).is_dir(),
              "runtime_exists": Path(record.get("runtime", "__missing__")).is_file(),
              "workspace_url": record.get("workspace_url", installs.DEFAULT_WORKSPACE)}
    if record.get("autostart_error"):
        report['autostart_error'] = record['autostart_error']
    if state:
        report.update(version=state.get("version"), compatible=state.get("runtime", {}).get("compatible"))
    print(json.dumps(report, indent=2))
    if not record:
        print("Copy the setup command from the website to register or reuse an existing clone.")
    elif not report["runtime_exists"]:
        print("Run the website setup command again; it repairs the environment without resetting station data.")
    elif not state:
        print("Run dexops to start this installation. Allow local access if your browser asks.")
    return report


def main(argv=None):
    if sys.stdout is None or sys.stderr is None:
        logs = installs.install_home() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stream = (logs / "startup.log").open("a", encoding="utf-8")
        sys.stdout = sys.stderr = stream
    parser = argparse.ArgumentParser(description="Start, maintain and update your registered Dexops installation")
    parser.add_argument("command", nargs="?", default="start", choices=("start", "update", "doctor", "stop", "autostart", "repair", "rollback"))
    parser.add_argument("setting", nargs="?", choices=("on", "off"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--local", action="store_true", help="Open the local development UI")
    parser.add_argument("--installation-home", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.installation_home:
        os.environ["DEXOPS_INSTALL_HOME"] = args.installation_home
    try:
        record = installs.read_record()
        if args.command == "doctor":
            doctor(record)
            return
        if args.command == "stop":
            installs.stop_service()
            print("Dexops stopped. Run dexops to start it again.")
            return
        if not record:
            raise ValueError("No installation is registered. Run the setup command from the Dexops website once.")
        if args.command == "start":
            start(record, args.no_browser, args.local)
            return
        with installs.installation_lock():
            if args.command == "autostart":
                if args.setting not in ("on", "off"):
                    parser.error("Use dexops autostart on or dexops autostart off")
                from t2_bots.connect.startup import configure
                configure(record, args.setting == "on")
                installs.save_record(record)
                print("Start at sign-in: " + args.setting)
                return
            if args.command == "update":
                record = installs.update_installation(record, installs.release_manifest(record["workspace_url"]))
            elif args.command == "repair":
                installs.assert_idle(installs.probe_service())
                runtime, digest = installs.ensure_environment(Path(record["app_root"]), record, repair=True)
                updated = {**record, "runtime": str(runtime), "dependencies_sha256": digest,
                           "previous": {k: v for k, v in record.items() if k != "previous"}}
                record = installs.activate_installation(record, updated)
            elif args.command == "rollback":
                previous = record.get("previous")
                if not previous or not installs.environment_ok(previous["runtime"], Path(previous["app_root"])):
                    raise ValueError("No verified previous environment is available.")
                record = installs.activate_installation(record, previous)
            start(record, args.no_browser, args.local)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Dexops: " + str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
