"""Generate matching, source-only download assets on every Vercel build."""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main():
    address = os.environ.get("T2_DIRECTORY_URL", "").strip().rstrip("/")
    parts = urlsplit(address)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")
            or parts.hostname in ("localhost", "127.0.0.1", "::1")
            or "REPLACE" in address.upper()):
        raise SystemExit("Set public T2_DIRECTORY_URL to the deployed Render HTTPS address before building Vercel.")
    subprocess.run([sys.executable, str(ROOT / "scripts/build-connect-release.py"),
                    "--directory-url", address], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/check-connect-release.py"),
                    "--production", "--source-only"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
