"""Standalone Python entry published with the website: clone once, then reuse."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

REPOSITORY = "https://github.com/RussMaharic/servo_social_russ.git"
WORKSPACES = ("https://servosocialruss.vercel.app", "https://play.trydexops.com")


@contextlib.contextmanager
def bootstrap_lock(home):
    descriptor = os.open(home / "bootstrap.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another setup command is running. Let it finish before retrying.") from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *map(str, args)], check=True,
                          capture_output=True, text=True).stdout.strip()


def valid_repo(path):
    try:
        origin = git(path, "remote", "get-url", "origin").lower().rstrip("/").removesuffix(".git")
        return origin in (REPOSITORY.lower().removesuffix(".git"), "git@github.com:russmaharic/servo_social_russ")
    except (OSError, subprocess.SubprocessError):
        return False


def find_repository(home, explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not valid_repo(path):
            raise ValueError("That folder is not the expected repository. Nothing was overwritten.")
        return path
    registry = home / "installation.json"
    if registry.exists():
        try:
            record = json.loads(registry.read_text(encoding="utf-8"))
        except ValueError:
            record = {}
        if isinstance(record, dict) and record.get("repository") and valid_repo(record["repository"]):
            return Path(record["repository"]).resolve()
    managed = home / "repository"
    if managed.exists():
        if not valid_repo(managed):
            raise ValueError("The install folder contains other files. Nothing was overwritten; use --repo to select your clone.")
        return managed
    downloads = Path.home() / "Downloads"
    candidates = sorted(downloads.glob("dexops*"))[:40] if downloads.exists() else []
    candidates += [downloads / "t2_bots_teleop"]
    valid = list(dict.fromkeys(path.resolve() for path in candidates if path.is_dir() and valid_repo(path)))
    if len(valid) > 1:
        raise ValueError("Several earlier clones were found. Add --repo \"PATH\" to reuse one:\n" + "\n".join(map(str, valid)))
    return valid[0] if valid else None


def prepare_repository(home, commit, explicit=None):
    repo = find_repository(home, explicit)
    if repo is None:
        repo = home / "repository"
        subprocess.run(["git", "clone", "--filter=blob:none", "--depth=1", REPOSITORY, str(repo)], check=True)
        git(repo, "fetch", "--depth=1", "origin", commit)
        git(repo, "checkout", "--detach", commit)
        return repo
    if git(repo, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("The earlier clone has local edits. Commit/back them up first; setup did not overwrite them or clone again.")
    if git(repo, "rev-parse", "HEAD") == commit:
        return repo
    git(repo, "fetch", "origin", commit)
    release = home / "releases" / commit
    if release.exists():
        if not valid_repo(release) or git(release, "rev-parse", "HEAD") != commit or git(release, "status", "--porcelain", "--untracked-files=normal"):
            raise ValueError("The prepared release folder has changed. It was not overwritten.")
    else:
        release.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "--detach", str(release), commit)
    return release


def main(argv=None):
    parser = argparse.ArgumentParser(description="Clone Dexops once and connect its reusable environment to the website")
    parser.add_argument("--workspace-url", default=WORKSPACES[0])
    parser.add_argument("--repo", help="Adopt an existing clone")
    parser.add_argument("--autostart", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--install-only", action="store_true")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 10):
        parser.error("Install Python 3.10+ first, then run the same command again.")
    if not shutil.which("git"):
        parser.error("Install Git from git-scm.com, reopen your terminal, then run the same command again.")
    site = args.workspace_url.rstrip("/")
    if site not in WORKSPACES:
        parser.error("Use an approved Dexops website.")
    with urllib.request.urlopen(site + "/release.json", timeout=20) as response:
        release = json.load(response)
    published = release.get("installation", {})
    commit = published.get("commit", "")
    if published.get("repository") != REPOSITORY or not re.fullmatch(r"[0-9a-f]{40,64}", str(commit)):
        raise ValueError("This website has not published the command-based release yet. No new clone was created.")
    if release.get("api_version") != 1:
        raise ValueError("Copy the current setup command from the website; its API has changed.")
    home = Path(os.environ.get("DEXOPS_INSTALL_HOME", Path.home() / ".dexops")).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    with bootstrap_lock(home):
        repo = prepare_repository(home, commit, args.repo)
        setup = repo / "dexops/scripts/setup-dexops.py"
        if not setup.is_file():
            raise ValueError("The published commit does not contain the current setup script.")
        command = [sys.executable, str(setup), "--workspace-url", site]
        if args.autostart is not None:
            command.append("--autostart" if args.autostart else "--no-autostart")
        if args.install_only:
            command.append("--install-only")
        subprocess.run(command, check=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print("Dexops setup: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
