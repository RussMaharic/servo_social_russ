"""Identify the running process separately from installation/user approval."""
import hashlib
import importlib.util
import importlib
import json
import platform
import re
import shutil
import ssl
import sys
from pathlib import Path

from t2_bots import __version__

API_VERSION = 1
ASSETS = Path(__file__).parent / "static"


def source_build_id():
    source_root = Path(__file__).resolve().parents[2]
    paths = list(source_root.rglob("*.py"))
    paths += [p for p in ASSETS.iterdir() if p.suffix in (".js", ".css", ".html", ".svg")]
    checksum = hashlib.sha256()
    for path in sorted(set(paths)):
        if "__pycache__" not in path.parts:
            checksum.update(path.relative_to(source_root).as_posix().encode())
            checksum.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return checksum.hexdigest()[:20]


def launch_kind():
    if getattr(sys, "frozen", False):
        return "packaged"
    if (Path(__file__).resolve().parents[3] / "pyproject.toml").exists():
        return "source"
    return "python"


def build_id(kind=None):
    if (kind or launch_kind()) != "source":
        try:
            return json.loads((ASSETS / "build-info.json").read_text(encoding="utf-8"))["build_id"]
        except (OSError, ValueError, KeyError):
            return "unknown"
    return source_build_id()


class Runtime:
    def __init__(self):
        # Capture at process startup. Editing source files must not make an old
        # running process claim that it already loaded those new files.
        self.kind = launch_kind()
        self.build = build_id(self.kind)
        try:
            ssl.create_default_context()
            self.tls_ready = True
        except OSError:
            self.tls_ready = False

    def snapshot(self, approval=None):
        checks = [{"id": "python", "label": "Python runtime", "required": True,
                   "status": "ready" if sys.version_info >= (3, 10) else "missing",
                   "detail": platform.python_version() + (" · bundled with the app" if self.kind == "packaged" else " · this source environment"),
                   "url": "https://www.python.org/downloads/"}]
        checks.append({"id": "tls", "label": "Secure directory connection", "required": True,
                       "status": "ready" if self.tls_ready else "missing",
                       "detail": "TLS runtime and certificate data are available." if self.tls_ready else
                                 "The Python runtime cannot initialise TLS. Install the updated companion or repair its certificate data."})
        for module, label, minimum in (("serial", "USB serial support", (3, 5, 0)),
                              ("websockets", "Teleoperation transport", (12, 0, 0)),
                              ("fastapi", "Browser gateway", (0, 100, 0)),
                              ("pydantic", "Gateway data validation", (2, 0, 0)),
                              ("uvicorn", "Local web server", (0, 20, 0))):
            available = importlib.util.find_spec(module) is not None
            version = "unknown"
            current = False
            if available:
                loaded = importlib.import_module(module)
                version = str(getattr(loaded, "__version__", getattr(loaded, "VERSION", "unknown")))
                match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
                current = bool(match) and tuple(int(n or 0) for n in match.groups()) >= minimum
            checks.append({"id": module, "label": label, "required": True,
                           "status": "ready" if current else "missing",
                           "detail": f"Version {version} · minimum {'.'.join(map(str, minimum))}" if current else
                           f'Version {version} is missing or outdated. Install the current companion or run python -m pip install -e ".[gateway]"'})
        checks.append({"id": "ssh", "label": "OpenSSH client", "required": False,
                       "status": "ready" if shutil.which("ssh") else "optional_missing",
                       "detail": "Available for the SDK cloud relay" if shutil.which("ssh") else
                                 "Needed for Pinggy public links; LAN/VPN connections do not require it.",
                       "command": "Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0" if sys.platform == "win32" else
                                  "sudo apt install openssh-client" if sys.platform.startswith("linux") else "ssh -V"})
        compatible = all(c["status"] == "ready" for c in checks if c["required"]) and self.build != "unknown" and sys.platform in ("win32", "darwin", "linux")
        acknowledged = approval == {"version": __version__, "build_id": self.build, "kind": self.kind}
        return {"kind": self.kind, "version": __version__, "sdk_version": __version__,
                "build_id": self.build, "api_version": API_VERSION, "platform": sys.platform,
                "architecture": platform.machine(), "python_version": platform.python_version(),
                "compatible": compatible, "acknowledged": acknowledged,
                "checks": checks,
                "capabilities": ["bootstrap", "certification", "peer", "relay", "swarm", "deadman"],
                "workspace_capabilities": ["onboarding", "calibration", "certification", "single_follower_dashboard"]}

    def approval(self):
        return {"version": __version__, "build_id": self.build, "kind": self.kind}


def platform_audit():
    """Read-only SDK checks. Never call the bootstrap auto-fix/elevation path."""
    from t2_bots.platform.installer import (
        check_linux_udev_rules, check_linux_user_groups,
        audit_macos_serial_nodes, audit_macos_python_arch,
    )
    if sys.platform.startswith("linux"):
        rules_ok, missing = check_linux_udev_rules()
        groups_ok, present, absent = check_linux_user_groups()
        return [{"label": "Linux USB permissions", "status": "ready" if rules_ok and groups_ok else "action_needed",
                 "detail": "udev rules and serial groups are configured." if rules_ok and groups_ok else
                           "Missing udev rules or group access. Use the SDK bootstrap guidance, then sign out and back in.",
                 "command": "t2-bots bootstrap --elevate"}]
    if sys.platform == "darwin":
        nodes, arch = audit_macos_serial_nodes(), audit_macos_python_arch()
        return [{"label": "macOS USB and architecture", "status": "info",
                 "detail": "Connect the USB adapter and match your Python/app architecture to your Mac.",
                 "details": {"serial": nodes, "python": arch}}]
    if sys.platform == "win32":
        # The SDK's Windows helper swallows probe failures and returns an empty
        # list. An empty result is not proof that a missing driver is healthy.
        return [{"label": "Windows USB drivers", "status": "info",
                 "detail": "A missing controller cannot be certified from the browser. Plug it in, check Device Manager, and install only its matching CH340/CH343, FTDI or CP210x driver if needed.",
                 "command": "t2-bots bootstrap --no-auto --json"}]
    return [{"label": "Operating system", "status": "action_needed", "detail": "Use Windows, macOS or Linux."}]
