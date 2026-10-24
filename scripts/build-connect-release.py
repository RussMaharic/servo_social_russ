"""Build actual downloadable artifacts; never overwrites the original dist wheel.

python scripts/build-connect-release.py [--windows] [--directory-url https://...]
The Windows option requires PyInstaller in the active build environment.
"""
import argparse
import hashlib
import json
import shutil
import ssl
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "t2_bots" / "connect" / "static"
sys.path.insert(0, str(ROOT / "src"))
from t2_bots import __version__
from t2_bots.connect.runtime import source_build_id


def runtime_tls_data():
    """Preserve TLS data required by the Python runtime used for packaging."""
    ssl_module = Path(ssl.__file__)
    certificate_data = ssl_module.with_name("codex-rejected-cas.pem")
    if "codex-rejected-cas.pem" in ssl_module.read_text(encoding="utf-8"):
        if not certificate_data.is_file():
            raise RuntimeError("The build Python runtime is missing required TLS certificate data.")
        return [(str(certificate_data), ".")]
    return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", action="store_true")
    parser.add_argument("--directory-url", default="")
    parser.add_argument("--desktop-dir", type=Path, help="Stage a new executable without stopping the running desktop app")
    args = parser.parse_args()
    if args.windows and sys.platform != "win32":
        parser.error("Build the Windows application on Windows.")
    if args.directory_url and not args.directory_url.startswith("https://"):
        parser.error("The public directory URL must use HTTPS.")
    output = ROOT / "build" / "connect-release"
    desktop = args.desktop_dir.resolve() if args.desktop_dir else output / "desktop"
    output.mkdir(parents=True, exist_ok=True)
    build = source_build_id()
    downloads = ASSETS / "downloads"
    downloads.mkdir(exist_ok=True)
    source = downloads / f"t2-connect-source-{__version__}-{build}.zip"
    metadata = {"version":__version__,"build_id":build,"directory_url":args.directory_url,
                "source":"downloads/"+source.name,"windows":None,"macos":None,"linux":None,
                "windows_signing_required":not args.windows}
    (ASSETS/"build-info.json").write_text(json.dumps({"version":__version__,"build_id":build},indent=2)+"\n",encoding="utf-8")
    (ASSETS/"release.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    # Build before copying downloads into package-data, avoiding recursive archives.
    subprocess.run([sys.executable,"-m","build","--wheel","--outdir",str(output)],cwd=ROOT,check=True)
    wheel = output / f"t2_bots-{__version__}-py3-none-any.whl"
    if not wheel.exists():
        raise RuntimeError("Expected current version wheel was not built.")
    with zipfile.ZipFile(source,"w",zipfile.ZIP_DEFLATED) as archive:
        for path in ROOT.joinpath("src").rglob("*"):
            if path.is_file() and not any(part in ("__pycache__","downloads") or part.endswith(".egg-info") for part in path.parts):
                archive.write(path,"t2-connect/"+path.relative_to(ROOT).as_posix())
        for name in ("pyproject.toml","README.md","LICENSE","Start t2 Connect.cmd",
                     "scripts/start-connect.ps1","scripts/start-connect.sh","scripts/build-connect-release.py",
                     "scripts/check-connect-release.py","scripts/connect_entry.py","docs/FRONTEND.md"):
            archive.write(ROOT/name,"t2-connect/"+name)
        cloud_guide = ROOT / "docs/CLOUD-SETUP.md"
        if cloud_guide.is_file():
            archive.write(cloud_guide, "t2-connect/docs/CLOUD-SETUP.md")
        for migration in (ROOT / "supabase/migrations").glob("*.sql"):
            archive.write(migration, "t2-connect/" + migration.relative_to(ROOT).as_posix())
        archive.writestr("t2-connect/START-HERE.txt",
            f"Dexops {__version__} | build {build}\n\n"
            "Extract the entire ZIP before launching. Python 3.10+ and internet access are required for first setup.\n"
            "Windows: open Start t2 Connect.cmd.\n"
            "macOS / Linux: open Terminal in this t2-connect folder and run: bash scripts/start-connect.sh\n"
            "Keep the launcher running while using the browser workspace.\n\n"
            "Updating: finish/cancel calibration and stop teleoperation, then close the older companion before launching this copy.\n"
            "Your username and saved calibration remain in ~/.config/t2_bots/connect (or T2_CONNECT_HOME). Do not delete or share station.json.\n\n"
            "Calibration: support the arm, start guided calibration, record the rest reference, then gently sweep all six joints and review/save.\n"
            "This build includes continuous local calibration sampling and the reference-positioning fix.\n"
            "This is a Python source package, not a signed standalone installer.\n")
    # Preserve the old URL for existing tabs; new manifests use a build-specific
    # filename so a cached earlier ZIP cannot masquerade as this release.
    shutil.copy2(source, downloads / "t2-connect-source.zip")
    # The portable workspace must advertise downloads that are inside its own
    # bundle, rather than inheriting the temporary empty build manifest.
    (ASSETS/"release.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    if args.windows:
        # Include the small, nonrecursive source package for macOS/Linux.
        # Never embed earlier Windows bundles or the whole downloads directory.
        spec = output / "t2-connect.spec"
        spec.write_text(
            "from PyInstaller.utils.hooks import collect_submodules\n"
            + "assets = " + repr([(str(p),"t2_bots/connect/static") for p in ASSETS.iterdir() if p.is_file()]
                                  + [(str(source),"t2_bots/connect/static/downloads")] + runtime_tls_data()) + "\n"
            + "a = Analysis(" + repr([str(ROOT/"scripts"/"connect_entry.py")])
            + ", pathex=" + repr([str(ROOT/"src")])
            + ", datas=assets, hiddenimports=collect_submodules('uvicorn') + collect_submodules('websockets'), excludes=['pytest','_pytest','numpy','tkinter'])\n"
            + "pyz = PYZ(a.pure)\n"
            + "exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='t2-Connect', console=True)\n",
            encoding="utf-8")
        subprocess.run([sys.executable,"-m","PyInstaller","--noconfirm",
            "--distpath",str(desktop),"--workpath",str(output/"pyinstaller"),
            str(spec)],cwd=ROOT,check=True)
        executable = desktop/"t2-Connect.exe"
        bundle = downloads/"t2-connect-windows.zip"
        with zipfile.ZipFile(bundle,"w",zipfile.ZIP_DEFLATED) as archive:
            archive.write(executable,"t2-Connect.exe")
            archive.writestr("START-HERE.txt","Extract this folder and open t2-Connect.exe.\nNo Python installation is needed.\nKeep its console open while using the browser workspace.\nThis community build is unsigned.\n")
        metadata["windows"] = "downloads/"+bundle.name
    (ASSETS/"release.json").write_text(json.dumps(metadata,indent=2)+"\n",encoding="utf-8")
    distribution = ROOT / "dist"
    distribution.mkdir(exist_ok=True)
    artifacts = [source, wheel]
    if args.windows:
        artifacts.append(bundle)
    checksums = []
    for artifact in artifacts:
        target = distribution / artifact.name
        shutil.copy2(artifact, target)
        checksums.append(hashlib.sha256(target.read_bytes()).hexdigest() + "  " + target.name)
    (distribution / f"t2-connect-{__version__}-{build}-SHA256SUMS.txt").write_text("\n".join(checksums)+"\n",encoding="utf-8")
    print("Release artifacts: " + str(downloads))
    print("Vercel output directory: src/t2_bots/connect/static")


if __name__ == "__main__":
    main()
