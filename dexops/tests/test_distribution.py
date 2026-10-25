"""Hardware-free builder regressions retained from the legacy root test suite."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11),
    reason="Release building uses tomllib on Python 3.11+; the release CI job uses Python 3.12.")


def builder():
    spec = importlib.util.spec_from_file_location("connect_release", Path(__file__).parents[1] / "scripts/build-connect-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_windows_package_includes_runtime_required_tls_data(tmp_path, monkeypatch):
    release = builder()
    runtime_ssl = tmp_path / "ssl.py"
    runtime_ssl.write_text("# runtime requires codex-rejected-cas.pem", encoding="utf-8")
    monkeypatch.setattr(release.ssl, "__file__", str(runtime_ssl))
    with pytest.raises(RuntimeError, match="TLS"):
        release.runtime_tls_data()
    certificate_data = tmp_path / "codex-rejected-cas.pem"
    certificate_data.write_text("runtime certificate data", encoding="utf-8")
    assert release.runtime_tls_data() == [(str(certificate_data), ".")]
    runtime_ssl.write_text("# standard Python SSL module", encoding="utf-8")
    certificate_data.unlink()
    assert release.runtime_tls_data() == []


def test_release_build_uses_uv_without_installing_into_managed_python(tmp_path, monkeypatch):
    release = builder()
    monkeypatch.setattr(release.shutil, "which", lambda name: "/usr/local/bin/uv" if name == "uv" else None)
    assert release.wheel_build_command(tmp_path) == ["/usr/local/bin/uv", "build", "--wheel", "--out-dir", str(tmp_path)]


def test_release_script_metadata_does_not_import_hardware_dependencies():
    script = Path(__file__).parents[1] / "scripts/build-connect-release.py"
    result = subprocess.run([sys.executable, "-S", str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--directory-url" in result.stdout


def test_git_release_does_not_publish_a_commit_missing_uncommitted_changes(monkeypatch):
    release = builder()
    commit = 'a' * 40
    monkeypatch.setattr(release.subprocess, 'check_output', lambda command, **kwargs: commit if command[-1] == 'HEAD' else ' M source.py')
    assert release.published_commit() is None
    monkeypatch.setattr(release.subprocess, 'check_output', lambda command, **kwargs: commit if command[-1] == 'HEAD' else '')
    monkeypatch.delenv('VERCEL_GIT_COMMIT_SHA', raising=False)
    assert release.published_commit() == commit
    monkeypatch.setenv('VERCEL_GIT_COMMIT_SHA', 'b' * 40)
    assert release.published_commit() is None


def test_git_integrated_vercel_build_can_publish_without_git_directory(monkeypatch):
    release = builder()
    def absent_git(*args, **kwargs):
        raise FileNotFoundError('git metadata is not present')
    monkeypatch.setattr(release.subprocess, 'check_output', absent_git)
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_GIT_PROVIDER', 'github')
    monkeypatch.setenv('VERCEL_GIT_REPO_OWNER', 'RussMaharic')
    monkeypatch.setenv('VERCEL_GIT_REPO_SLUG', 'servo_social_russ')
    monkeypatch.setenv('VERCEL_GIT_COMMIT_SHA', 'c' * 40)
    assert release.published_commit() == 'c' * 40
    monkeypatch.setenv('VERCEL_GIT_REPO_OWNER', 'another-owner')
    assert release.published_commit() is None


def test_vercel_git_revision_does_not_depend_on_platform_generated_checkout_state(monkeypatch):
    release = builder()
    monkeypatch.setenv('VERCEL', '1')
    monkeypatch.setenv('VERCEL_GIT_PROVIDER', 'github')
    monkeypatch.setenv('VERCEL_GIT_REPO_OWNER', 'RussMaharic')
    monkeypatch.setenv('VERCEL_GIT_REPO_SLUG', 'servo_social_russ')
    monkeypatch.setenv('VERCEL_GIT_COMMIT_SHA', 'd' * 40)
    monkeypatch.setattr(release.subprocess, 'check_output', lambda *args, **kwargs: pytest.fail('Deployment metadata must take precedence over generated Git workspace state'))
    assert release.published_commit() == 'd' * 40


def test_desktop_build_embeds_a_real_cross_platform_source_download(tmp_path, monkeypatch):
    release = builder()
    assets = tmp_path / "src/t2_bots/connect/static"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("workspace", encoding="utf-8")
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE", ".env.example", "Start t2 Connect.cmd",
                 "scripts/start-connect.ps1", "scripts/start-connect.sh", "scripts/build-connect-release.py",
                 "scripts/check-connect-release.py", "scripts/connect_entry.py", "scripts/bootstrap-dexops.py", "docs/FRONTEND.md",
                 "docs/ARCHITECTURE.md", "docs/SETUP.md", "docs/INSTALLATION.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source launcher fixture", encoding="utf-8")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release, "ASSETS", assets)
    monkeypatch.setattr(release, "source_build_id", lambda: "test-build")
    monkeypatch.setattr(release, "runtime_tls_data", lambda: [])
    monkeypatch.setattr(release.sys, "platform", "win32")
    monkeypatch.setattr(release.sys, "argv", ["build-connect-release.py", "--windows"])

    def fake_build(command, **kwargs):
        output = tmp_path / "build/connect-release"
        if "build" in command:
            (output / f"t2_bots-{release.__version__}-py3-none-any.whl").write_bytes(b"wheel fixture")
        else:
            manifest = json.loads((assets / "release.json").read_text(encoding="utf-8"))
            source = assets / manifest["source"]
            tree = ast.parse(Path(command[-1]).read_text(encoding="utf-8"))
            packaged_assets = ast.literal_eval(next(n.value for n in tree.body if isinstance(n, ast.Assign)))
            assert (str(source), "t2_bots/connect/static/downloads") in packaged_assets
            assert not any("windows.zip" in path for path, _ in packaged_assets)
            with zipfile.ZipFile(source) as archive:
                assert "t2-connect/scripts/start-connect.sh" in archive.namelist()
                assert not any("/downloads/" in name for name in archive.namelist())
                embedded = json.loads(archive.read("t2-connect/src/t2_bots/connect/static/release.json"))
                assert embedded["source"] == manifest["source"] and embedded["build_id"] == "test-build"
            executable = output / "desktop/t2-Connect.exe"
            executable.parent.mkdir(exist_ok=True)
            executable.write_bytes(b"portable fixture")

    monkeypatch.setattr(release.subprocess, "run", fake_build)
    release.main()
    checksums = tmp_path / f"dist/t2-connect-{release.__version__}-test-build-SHA256SUMS.txt"
    for line in checksums.read_text().splitlines():
        checksum, filename = line.split("  ", 1)
        assert hashlib.sha256((tmp_path / "dist" / filename).read_bytes()).hexdigest() == checksum
