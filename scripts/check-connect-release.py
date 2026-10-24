"""Check deployable download assets and public directory configuration. No keys needed."""
import argparse
import json
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_ASSETS = Path(__file__).resolve().parents[1] / "src/t2_bots/connect/static"


def check_release(assets, production=False, source_only=False):
    assets = Path(assets).resolve()
    errors = []
    try:
        release = json.loads((assets / "release.json").read_text(encoding="utf-8"))
        build = json.loads((assets / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ["Build release assets first: " + str(exc)]
    if not release.get("version") or not release.get("build_id") or any(release.get(k) != build.get(k) for k in ("version", "build_id")):
        errors.append("Release and build metadata do not match. Rebuild the downloads.")
    directory = urlsplit(release.get("directory_url", ""))
    if production and (directory.scheme != "https" or not directory.hostname or directory.hostname in ("localhost", "127.0.0.1", "::1") or directory.username or directory.password or directory.query or directory.fragment or directory.path not in ("", "/")):
        errors.append("Production needs the deployed Render/shared directory HTTPS URL in release.json; localhost is only for development.")
    if not release.get("source"):
        errors.append("Publish a source package so macOS and Linux users have an installation path.")
    if production and not source_only and not release.get("windows"):
        errors.append("Publish the Windows portable app before deploying this Windows/macOS/Linux download page.")
    for key in ("source", "windows", "macos", "linux"):
        target = release.get(key)
        if not target:
            continue
        parts = urlsplit(target)
        if parts.scheme:
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                errors.append(f"{key}: external downloads must use HTTPS without credentials.")
                continue
            try:
                with urllib.request.urlopen(urllib.request.Request(target, method="HEAD"), timeout=10) as response:
                    if response.status != 200:
                        errors.append(f"{key}: external download returned HTTP {response.status}.")
            except OSError as exc:
                errors.append(f"{key}: published download is unreachable: {exc}")
            continue
        path = (assets / target).resolve()
        if not path.is_relative_to(assets) or not path.is_file():
            errors.append(f"{key}: advertised download is missing or outside the assets folder: {target}")
            continue
        if key in ("source", "windows"):
            try:
                with zipfile.ZipFile(path) as archive:
                    names = archive.namelist()
                    required = ["t2-Connect.exe", "START-HERE.txt"] if key == "windows" else [
                        "t2-connect/pyproject.toml", "t2-connect/scripts/start-connect.sh", "t2-connect/Start t2 Connect.cmd"]
                    if not all(name in names for name in required) or archive.testzip():
                        errors.append(f"{key}: ZIP is incomplete or corrupted.")
                    if key == "source" and any("/downloads/" in name or "/.venv/" in name or name.endswith("/station.json") for name in names):
                        errors.append("Source ZIP contains nested downloads, environments or private station data.")
            except (OSError, zipfile.BadZipFile) as exc:
                errors.append(f"{key}: invalid ZIP: {exc}")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--source-only", action="store_true", help="Explicitly publish Python source launchers instead of standalone installers")
    args = parser.parse_args()
    errors = check_release(args.assets, args.production, args.source_only)
    for error in errors:
        print("ERROR: " + error)
    if errors:
        raise SystemExit(1)
    print("Release assets verified" + (" for production." if args.production else ". Public hosting still needs its deployed directory URL."))


if __name__ == "__main__":
    main()
