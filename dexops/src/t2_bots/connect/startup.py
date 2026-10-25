"""Per-user sign-in startup. It starts an idle service, never a robot session."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def _ps(value):
    return "'" + str(value).replace("'", "''") + "'"


def configure(record, enabled):
    from t2_bots.connect.installation import install_home
    runtime = Path(record["runtime"]).resolve()
    args = ["-I", "-m", "t2_bots.connect.cli", "start", "--no-browser", "--installation-home", str(install_home())]
    if sys.platform == "win32":
        folder = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
        target = folder / "Dexops.lnk"
        if enabled:
            pythonw = runtime.with_name("pythonw.exe")
            if not pythonw.is_file():
                raise ValueError("This Python environment has no pythonw.exe. Dexops can still be started with its command.")
            folder.mkdir(parents=True, exist_ok=True)
            startup_args = subprocess.list2cmdline(args)
            script = ("$ErrorActionPreference='Stop';$s=(New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps(target) + ");"
                      "$s.TargetPath=" + _ps(pythonw) + ";$s.Arguments=" + _ps(startup_args) + ";"
                      "$s.WorkingDirectory=" + _ps(record["app_root"]) + ";$s.WindowStyle=7;$s.Save()")
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           check=True, capture_output=True, text=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            target.unlink(missing_ok=True)
    elif sys.platform == "darwin":
        target = Path.home() / "Library/LaunchAgents/com.trydexops.companion.plist"
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as stream:
                plistlib.dump({"Label": "com.trydexops.companion", "ProgramArguments": [str(runtime), *args],
                               "RunAtLoad": True, "KeepAlive": False,
                               "WorkingDirectory": record["app_root"]}, stream)
        else:
            target.unlink(missing_ok=True)
    elif sys.platform.startswith("linux"):
        # Desktop autostart works without requiring a systemd user bus, root,
        # or a persistent terminal. The browser runs in this same login session.
        target = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart/dexops.desktop"
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            def quote(value):
                if '\n' in value or '\r' in value:
                    raise ValueError("Unsupported installation path.")
                return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'
            command = " ".join(quote(value) for value in [str(runtime), *args])
            target.write_text("[Desktop Entry]\nType=Application\nName=Dexops\nTerminal=false\nExec=" + command + "\n", encoding="utf-8")
        else:
            target.unlink(missing_ok=True)
    else:
        raise ValueError("Sign-in startup supports Windows, macOS and desktop Linux.")
    record["autostart"] = bool(enabled)
