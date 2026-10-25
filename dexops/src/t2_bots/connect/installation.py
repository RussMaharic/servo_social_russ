"""One registered checkout and reusable environments, independent of robot state."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv

from t2_bots.connect.storage import atomic_json

REPOSITORY = "https://github.com/RussMaharic/servo_social_russ.git"
WORKSPACES = ("https://servosocialruss.vercel.app", "https://play.trydexops.com")
DEFAULT_WORKSPACE = WORKSPACES[0]


def install_home():
    return Path(os.environ.get("DEXOPS_INSTALL_HOME", Path.home() / ".dexops")).expanduser().resolve()


def workspace_url(value):
    value = str(value).rstrip("/")
    if value not in WORKSPACES:
        raise ValueError("Use an approved hosted Dexops workspace.")
    return value


def read_record(repair=False):
    try:
        record = json.loads((install_home() / "installation.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or not all(record.get(key) for key in ("app_root", "runtime", "workspace_url")):
            raise ValueError("Incomplete installation record")
        return record
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        if repair:
            # This is installation metadata only, never station/calibration data.
            source = install_home() / "installation.json"
            backup = source.with_name("installation.invalid-" + str(int(time.time())) + "-" + secrets.token_hex(4) + ".json")
            source.replace(backup)
            return {}
        raise ValueError("The installation record needs repair. Run the website's setup command again.") from exc


def public_status():
    """Only non-secret hints; do not expose filesystem paths or station keys."""
    try:
        record = read_record()
        return {"registered": bool(record), "autostart": bool(record.get("autostart")),
                "commit": record.get("commit", "")}
    except ValueError:
        return {"registered": False, "autostart": False, "needs_repair": True}


def save_record(record):
    atomic_json(install_home() / "installation.json", record)


@contextlib.contextmanager
def installation_lock():
    home = install_home()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = home / "installation.lock"
    # Kernel locks are released on process exit, including crashes. Keep the
    # file in place so concurrent processes always lock the same inode.
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if sys.platform == "win32":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError("Another setup/update is running. Wait for it to finish.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError("Another setup/update is running. Wait for it to finish.") from exc
        locked = True
        yield
    finally:
        if locked:
            if sys.platform == "win32":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def run(args, **kwargs):
    result = subprocess.run([str(a) for a in args], check=True, **kwargs)
    return result.stdout.strip() if kwargs.get("capture_output") else result


def git(repo, *args):
    return run(["git", "-C", repo, *args], capture_output=True, text=True)


def app_root(path):
    path = Path(path).expanduser().resolve()
    for candidate in (path / "dexops", path):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src/t2_bots/connect/app.py").is_file():
            return candidate
    raise ValueError("This folder does not contain the Dexops application.")


def repository_root(app):
    try:
        return Path(git(app, "rev-parse", "--show-toplevel")).resolve()
    except (OSError, subprocess.CalledProcessError):
        return None


def check_repository(repo):
    origin = git(repo, "remote", "get-url", "origin").rstrip("/").removesuffix(".git").lower()
    if origin not in (REPOSITORY.removesuffix(".git").lower(), "git@github.com:russmaharic/servo_social_russ"):
        raise ValueError("The existing folder belongs to another repository; nothing was overwritten.")
    return Path(repo).resolve()


def release_manifest(site):
    request = urllib.request.Request(workspace_url(site) + "/release.json", headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    installation = data.get("installation", {})
    commit = installation.get("commit", "")
    if installation.get("repository") != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40,64}", str(commit)):
        raise ValueError("The website has not published a Git-based release yet. Keep your current install and retry after deployment.")
    if data.get("api_version", 1) != 1:
        raise ValueError("This setup command needs updating. Copy the current command from the website.")
    return data


def runtime_path(environment):
    return Path(environment) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def dependency_hash(app):
    checksum = hashlib.sha256((app / "pyproject.toml").read_bytes())
    lock = app / "requirements-companion.lock"
    if lock.is_file():
        checksum.update(lock.read_bytes())
    return checksum.hexdigest()


def environment_ok(runtime, app):
    if not Path(runtime).is_file():
        return False
    probe = ("import pathlib,sys;from t2_bots.connect.runtime import Runtime;"
             "import t2_bots.connect.app as a;"
             "assert pathlib.Path(a.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve());"
             "assert Runtime().snapshot()['compatible']")
    try:
        run([runtime, "-I", "-c", probe, app / "src"], capture_output=True, text=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_environment(app, previous=None, repair=False):
    digest = dependency_hash(app)
    if not repair and previous and previous.get("dependencies_sha256") == digest and Path(previous.get("app_root", "")).resolve() == app:
        runtime = Path(previous.get("runtime", ""))
        if environment_ok(runtime, app):
            return runtime, digest
    if not repair and not previous:
        # Adopt healthy environments from the earlier clone-based launchers.
        for folder in (app / ".venv", app.parent / ".venv"):
            runtime = runtime_path(folder)
            if environment_ok(runtime, app):
                return runtime, digest
    # Environments are created in their final locations; moving a venv breaks
    # absolute interpreter paths in its scripts. A failed install leaves the
    # registered, working environment untouched.
    environment = install_home() / "environments" / (digest[:10] + "-" + secrets.token_hex(4))
    venv.EnvBuilder(with_pip=True).create(environment)
    runtime = runtime_path(environment)
    lock = app / "requirements-companion.lock"
    if lock.is_file():
        run([runtime, "-m", "pip", "install", "--require-hashes", "-r", lock])
        run([runtime, "-m", "pip", "install", "--no-deps", "-e", str(app) + "[gateway]"])
    else:
        run([runtime, "-m", "pip", "install", "-e", str(app) + "[gateway]"])
    if not environment_ok(runtime, app):
        raise ValueError("Environment verification failed. The previous installation is still registered.")
    return runtime, digest


def register_commands(record):
    target = install_home() / "bin"
    target.mkdir(parents=True, exist_ok=True)
    runtime = record["runtime"]
    if sys.platform == "win32":
        if any(c in str(runtime) + str(target) for c in ('"', '%', '\r', '\n')):
            raise ValueError("Unsupported characters in the installation path.")
        (target / "dexops.cmd").write_text('@echo off\nchcp 65001 >nul\n"' + runtime + '" -I -m t2_bots.connect.cli --installation-home "' + str(install_home()) + '" %*\n', encoding="utf-8")
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            try:
                current, _ = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current = ""
            remaining = [p for p in current.split(";") if p.strip() and p.strip().lower() != str(target).lower()]
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join([str(target), *remaining]))
        # Let new Explorer-launched terminals inherit the updated user PATH.
        import ctypes
        response = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, ctypes.c_wchar_p("Environment"), 2, 1000, ctypes.byref(response))
        # Current terminals can use the absolute command printed by setup.
    else:
        import shlex
        command = target / "dexops"
        command.write_text("#!/bin/sh\nexec " + shlex.quote(runtime) + ' -I -m t2_bots.connect.cli --installation-home ' + shlex.quote(str(install_home())) + ' "$@"\n', encoding="utf-8")
        command.chmod(0o755)
        profile = Path.home() / (".zprofile" if sys.platform == "darwin" else ".profile")
        line = 'export PATH=' + shlex.quote(str(target)) + ':"$PATH"'
        existing = profile.read_text(encoding="utf-8") if profile.exists() else ""
        if line not in existing:
            with profile.open("a", encoding="utf-8") as stream:
                stream.write("\n" + line + "\n")


def install_local(path, site=DEFAULT_WORKSPACE, autostart=None, repair=False):
    app = app_root(path)
    old = read_record(repair=True)
    runtime, digest = ensure_environment(app, old, repair)
    repo = repository_root(app)
    record = {"installation_id": old.get("installation_id", secrets.token_hex(16)),
              "repository": str(repo) if repo else "", "app_root": str(app),
              "runtime": str(runtime), "dependencies_sha256": digest,
              "station_home": str(Path(os.environ.get("T2_CONNECT_HOME") or old.get("station_home") or
                                       Path.home() / ".config/t2_bots/connect").expanduser().resolve()),
              "workspace_url": workspace_url(site), "autostart": old.get("autostart", False),
              "commit": git(repo, "rev-parse", "HEAD") if repo else "", "installed_at": time.time()}
    if old and old.get("runtime") != record["runtime"]:
        record["previous"] = {k: v for k, v in old.items() if k != "previous"}
    elif old.get("previous"):
        record["previous"] = old["previous"]
    register_commands(record)
    if autostart is not None or record["autostart"]:
        from t2_bots.connect.startup import configure
        try:
            configure(record, record["autostart"] if autostart is None else autostart)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            record["autostart"] = False
            record["autostart_error"] = str(exc)
    save_record(record)
    return record


def activate_installation(record, updated):
    """Handoff only after preparation; restore the last working install on failure."""
    assert_idle(probe_service())
    stop_service()
    from t2_bots.connect.cli import start
    from t2_bots.connect.startup import configure
    try:
        save_record(updated)
        start(updated, no_browser=True)
        register_commands(updated)
        configure(updated, updated.get("autostart", False))
    except Exception:
        stop_service()
        save_record(record)
        start(record, no_browser=True)
        register_commands(record)
        configure(record, record.get("autostart", False))
        raise
    return updated


def probe_service(port=4840):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as response:
            data = json.load(response)
        return data if data.get("service") == "t2-connect" else None
    except (OSError, ValueError):
        return None


def stop_service(port=4840):
    state = probe_service(port)
    if not state:
        return
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/runtime/shutdown", method="POST",
        data=b'{"confirmed":true}', headers={"Content-Type": "application/json", "X-T2-Session": state.get("session_token", "")})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            if not json.load(response).get("stopping"):
                raise ValueError("Companion did not confirm shutdown.")
    except urllib.error.HTTPError as exc:
        raise ValueError("Stop following, sharing and calibration before stopping or updating Dexops.") from exc
    for _ in range(40):
        if not probe_service(port):
            return
        time.sleep(.2)
    raise ValueError("The previous companion has not stopped. Keep your current install and retry.")


def assert_idle(state):
    if not state:
        return
    sessions = [state.get(key, {}) for key in ("leader_session", "follower_session", "session")]
    if state.get("capture") or state.get("publishing") or any(s.get("status", "idle") != "idle" for s in sessions):
        raise ValueError("Stop following, sharing and calibration before updating Dexops.")


def update_installation(record, manifest):
    assert_idle(probe_service())
    app = Path(record["app_root"])
    repo = check_repository(record["repository"]) if record.get("repository") else None
    if not repo:
        raise ValueError("This earlier download is not a Git clone. Run the website's setup command once to register a clone.")
    if any(git(path, "status", "--porcelain", "--untracked-files=normal") for path in dict.fromkeys((repo, app))):
        raise ValueError("The clone has local edits. Commit or back them up before updating; nothing was overwritten.")
    commit = manifest["installation"]["commit"]
    if git(app, "rev-parse", "HEAD") == commit and environment_ok(record["runtime"], app):
        return record
    git(repo, "fetch", "origin", commit)
    release = install_home() / "releases" / commit
    if release.exists():
        check_repository(release)
        if git(release, "rev-parse", "HEAD") != commit or git(release, "status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("The staged release contains local changes. It was not overwritten.")
    else:
        release.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "--detach", str(release), commit)
    candidate = app_root(release)
    runtime, digest = ensure_environment(candidate)
    current = {k: v for k, v in record.items() if k != "previous"}
    updated = {**current, "app_root": str(candidate), "runtime": str(runtime),
               "dependencies_sha256": digest, "commit": commit, "previous": current}
    return activate_installation(record, updated)
