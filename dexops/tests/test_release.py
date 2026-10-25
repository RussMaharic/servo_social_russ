"""Release checks retained when the retired root tests were removed."""
import importlib.util
import json
import zipfile
from pathlib import Path


def validator():
    spec = importlib.util.spec_from_file_location("release_check", Path(__file__).parents[1] / "scripts/check-connect-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_release


def release_files(root):
    release = {"version": "0.3.1", "build_id": "test", "directory_url": "https://directory.example",
               "source": "source.zip", "windows": "windows.zip"}
    (root / "release.json").write_text(json.dumps(release))
    (root / "build-info.json").write_text(json.dumps({"version": "0.3.1", "build_id": "test"}))
    with zipfile.ZipFile(root / "source.zip", "w") as archive:
        for name in ("pyproject.toml", "scripts/start-connect.sh", "Start t2 Connect.cmd"):
            archive.writestr("t2-connect/" + name, "test")
    with zipfile.ZipFile(root / "windows.zip", "w") as archive:
        archive.writestr("t2-Connect.exe", b"portable fixture")
        archive.writestr("START-HERE.txt", "test")
    return release


def test_production_release_rejects_missing_downloads_and_directory(tmp_path):
    release = release_files(tmp_path)
    release["directory_url"] = ""
    (tmp_path / "release.json").write_text(json.dumps(release))
    (tmp_path / "windows.zip").unlink()
    errors = validator()(tmp_path, production=True)
    assert any("HTTPS URL" in error for error in errors)
    assert any("advertised download is missing" in error for error in errors)


def test_complete_release_assets_pass_without_any_service_keys(tmp_path):
    release_files(tmp_path)
    assert validator()(tmp_path, production=True) == []


def test_source_package_must_not_distribute_private_station_data(tmp_path):
    release_files(tmp_path)
    with zipfile.ZipFile(tmp_path / "source.zip", "a") as archive:
        archive.writestr("t2-connect/station.json", "private fixture")
    assert any("private station" in error for error in validator()(tmp_path))


def test_source_only_production_release_is_an_explicit_choice(tmp_path):
    release = release_files(tmp_path)
    release["windows"] = None
    (tmp_path / "release.json").write_text(json.dumps(release))
    assert any("Windows portable" in error for error in validator()(tmp_path, production=True))
    assert validator()(tmp_path, production=True, source_only=True) == []


def test_git_release_requires_published_commit_and_bootstrap(tmp_path):
    release = release_files(tmp_path)
    release['installation'] = {'strategy': 'git', 'repository': 'https://github.com/RussMaharic/servo_social_russ.git',
                               'commit': None, 'bootstrap': 'bootstrap.py'}
    (tmp_path / 'release.json').write_text(json.dumps(release))
    errors = validator()(tmp_path, production=True, source_only=True)
    assert any('committed release' in error for error in errors)
    assert any('bootstrap.py' in error for error in errors)
    release['installation']['commit'] = 'a' * 40
    (tmp_path / 'release.json').write_text(json.dumps(release))
    (tmp_path / 'bootstrap.py').write_text('# bootstrap fixture')
    assert validator()(tmp_path, production=True, source_only=True) == []
