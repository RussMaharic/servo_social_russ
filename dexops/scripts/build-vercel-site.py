"""Generate matching, source-only download assets on every Vercel build."""
import os
import argparse
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-development", action="store_true", help="Validate local assets without advertising an uncommitted Git release")
    args = parser.parse_args()
    if args.allow_development and os.environ.get("VERCEL"):
        parser.error("Development release checks cannot be used on Vercel.")
    address = os.environ.get("T2_DIRECTORY_URL", "").strip().rstrip("/")
    parts = urlsplit(address)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")
            or parts.hostname in ("localhost", "127.0.0.1", "::1")
            or "REPLACE" in address.upper()):
        raise SystemExit("Set T2_DIRECTORY_URL to the deployed directory's public HTTPS address before building Vercel.")
    subprocess.run([sys.executable, str(ROOT / "scripts/build-connect-release.py"),
                    "--directory-url", address], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/check-connect-release.py"),
                    "--source-only"] + ([] if args.allow_development else ["--production"]), cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
