"""Installer maintenance stays isolated from real startup settings and hardware."""
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from t2_bots.connect import cli, installation as installs, startup


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).parents[1] / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    home = tmp_path / 'install'
    monkeypatch.setenv('DEXOPS_INSTALL_HOME', str(home))
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.setattr(installs, 'register_commands', lambda record: None)
    monkeypatch.setattr(startup, 'configure', lambda record, enabled: record.update(autostart=enabled))
    return home


def record(home):
    return {'app_root': str(home / 'app'), 'runtime': str(home / 'environment/python'),
            'workspace_url': installs.DEFAULT_WORKSPACE, 'repository': str(home / 'repository'),
            'installation_id': 'local-install', 'autostart': False, 'commit': 'a' * 40}


def test_repeated_setup_reuses_a_healthy_environment_without_installing(isolated, monkeypatch):
    app = isolated / 'app'
    app.mkdir(parents=True)
    (app / 'pyproject.toml').write_text('project')
    digest = installs.dependency_hash(app)
    saved = {**record(isolated), 'dependencies_sha256': digest}
    monkeypatch.setattr(installs, 'environment_ok', lambda runtime, path: True)
    monkeypatch.setattr(installs.venv.EnvBuilder, 'create', lambda *args: pytest.fail('A healthy environment was recreated'))
    assert installs.ensure_environment(app, saved) == (Path(saved['runtime']), digest)


def test_earlier_clone_environment_is_adopted(isolated, monkeypatch):
    app = isolated / 'app'
    app.mkdir(parents=True)
    (app / 'pyproject.toml').write_text('project')
    expected = installs.runtime_path(app / '.venv')
    monkeypatch.setattr(installs, 'environment_ok', lambda runtime, path: runtime == expected)
    monkeypatch.setattr(installs.venv.EnvBuilder, 'create', lambda *args: pytest.fail('Existing venv was not adopted'))
    assert installs.ensure_environment(app)[0] == expected


def test_failed_environment_preparation_preserves_registered_installation(isolated, monkeypatch):
    app = isolated / 'app'
    app.mkdir(parents=True)
    (app / 'pyproject.toml').write_text('project')
    original = record(isolated)
    installs.save_record(original)
    monkeypatch.setattr(installs.venv.EnvBuilder, 'create', lambda *args: None)
    monkeypatch.setattr(installs, 'run', lambda *args, **kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, 'pip')))
    with pytest.raises(subprocess.CalledProcessError):
        installs.ensure_environment(app, original, repair=True)
    assert installs.read_record() == original


def test_active_arms_block_update_before_any_git_or_install_work(isolated, monkeypatch):
    monkeypatch.setattr(installs, 'probe_service', lambda: {'leader_session': {'status': 'following'}})
    monkeypatch.setattr(installs, 'git', lambda *args: pytest.fail('Git ran during following'))
    with pytest.raises(ValueError, match='Stop following'):
        installs.update_installation(record(isolated), {'installation': {'commit': 'b' * 40}})


def test_dirty_repository_update_preserves_local_edits(isolated, monkeypatch):
    monkeypatch.setattr(installs, 'probe_service', lambda: None)
    monkeypatch.setattr(installs, 'check_repository', lambda repo: Path(repo))
    monkeypatch.setattr(installs, 'git', lambda *args: ' M dexops/src/local.py')
    with pytest.raises(ValueError, match='local edits'):
        installs.update_installation(record(isolated), {'installation': {'commit': 'b' * 40}})


def test_failed_handoff_restores_previous_registration_and_startup(isolated, monkeypatch):
    original = record(isolated)
    updated = {**original, 'runtime': 'new-environment/python', 'autostart': True}
    installs.save_record(original)
    monkeypatch.setattr(installs, 'probe_service', lambda: None)
    monkeypatch.setattr(installs, 'stop_service', lambda: None)
    starts, startup_settings = [], []

    def start(saved, **kwargs):
        starts.append(saved['runtime'])
        if saved['runtime'] == updated['runtime']:
            raise ValueError('new process failed')

    monkeypatch.setattr(cli, 'start', start)
    monkeypatch.setattr(startup, 'configure', lambda saved, enabled: startup_settings.append((saved['runtime'], enabled)))
    with pytest.raises(ValueError, match='new process failed'):
        installs.activate_installation(original, updated)
    assert installs.read_record() == original
    assert starts == [updated['runtime'], original['runtime']]
    assert startup_settings == [(original['runtime'], False)]


def test_setup_failure_restarts_previous_installation(isolated, monkeypatch):
    setup = script('setup-dexops.py')
    original = record(isolated)
    installs.save_record(original)
    updated = {**original, 'runtime': 'new-runtime/python'}
    monkeypatch.setattr(installs, 'probe_service', lambda: None)
    monkeypatch.setattr(installs, 'install_local', lambda *args: updated)
    monkeypatch.setattr(sys, 'path', sys.path.copy())
    starts = []

    def start(saved, **kwargs):
        starts.append((saved['runtime'], kwargs.get('no_browser', False)))
        if saved['runtime'] == updated['runtime']:
            raise ValueError('new setup failed to start')

    monkeypatch.setattr(cli, 'start', start)
    with pytest.raises(ValueError, match='failed to start'):
        setup.main([])
    assert installs.read_record() == original
    assert starts == [(updated['runtime'], False), (original['runtime'], True)]


def test_repair_prepares_environment_before_stopping_existing_service(isolated, monkeypatch):
    saved = record(isolated)
    installs.save_record(saved)
    calls = []
    monkeypatch.setattr(installs, 'probe_service', lambda: None)
    monkeypatch.setattr(installs, 'ensure_environment', lambda *args, **kwargs: (calls.append('prepare') or Path('new-python'), 'hash'))
    monkeypatch.setattr(installs, 'activate_installation', lambda old, new: calls.append('activate') or new)
    monkeypatch.setattr(cli, 'start', lambda *args: calls.append('start'))
    cli.main(['repair', '--no-browser'])
    assert calls == ['prepare', 'activate', 'start']


def test_start_reuses_running_service_and_only_opens_the_hosted_page(isolated, monkeypatch):
    service = {'api_version': 1, 'runtime': {'compatible': True}, 'session': {'status': 'idle'}}
    monkeypatch.setattr(installs, 'probe_service', lambda: service)
    monkeypatch.setattr(cli.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('Duplicate companion started'))
    pages = []
    monkeypatch.setattr(cli.webbrowser, 'open', pages.append)
    assert cli.start(record(isolated)) == service
    assert pages == [installs.DEFAULT_WORKSPACE + '/']


def test_startup_spawn_has_no_robot_or_browser_action(isolated, monkeypatch):
    saved = record(isolated)
    saved['station_home'] = str(isolated / 'existing-station-data')
    monkeypatch.delenv('T2_CONNECT_HOME', raising=False)
    Path(saved['runtime']).parent.mkdir(parents=True)
    Path(saved['runtime']).touch()
    states = iter([None, {'service': 't2-connect', 'api_version': 1, 'runtime': {'compatible': True}}])
    monkeypatch.setattr(installs, 'probe_service', lambda: next(states))
    spawned = []
    def spawn(args, **kwargs):
        assert kwargs['env']['T2_CONNECT_HOME'] == saved['station_home']
        spawned.append(args)
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(cli.subprocess, 'Popen', spawn)
    monkeypatch.setattr(cli.webbrowser, 'open', lambda *args: pytest.fail('Startup opened a browser'))
    cli.start(saved, no_browser=True)
    assert spawned == [[saved['runtime'], '-I', '-m', 't2_bots.connect.app', '--no-browser']]


def test_installation_lock_recovers_after_exception_and_rejects_concurrency(isolated):
    with pytest.raises(RuntimeError):
        with installs.installation_lock():
            with pytest.raises(ValueError, match='Another setup'):
                with installs.installation_lock():
                    pass
            raise RuntimeError('simulated crash')
    with installs.installation_lock():
        pass


def test_public_metadata_omits_paths_and_credentials(isolated):
    installs.save_record({**record(isolated), 'credential': 'private-device-key'})
    result = installs.public_status()
    assert set(result) == {'registered', 'autostart', 'commit'}
    assert 'private-device-key' not in json.dumps(result)
    assert str(isolated) not in json.dumps(result)


def test_corrupt_installation_metadata_is_backed_up_during_setup(isolated):
    isolated.mkdir()
    damaged = isolated / 'installation.json'
    damaged.write_text('{broken json')
    assert installs.public_status()['needs_repair'] is True
    with pytest.raises(ValueError, match='needs repair'):
        installs.read_record()
    assert installs.read_record(repair=True) == {}
    backups = list(isolated.glob('installation.invalid-*.json'))
    assert len(backups) == 1 and backups[0].read_text() == '{broken json'


def test_bootstrap_can_reuse_managed_clone_when_registry_is_damaged(isolated, monkeypatch):
    bootstrap = script('bootstrap-dexops.py')
    managed = isolated / 'repository'
    managed.mkdir(parents=True)
    (isolated / 'installation.json').write_text('{broken json')
    monkeypatch.setattr(bootstrap, 'valid_repo', lambda path: path == managed)
    assert bootstrap.find_repository(isolated) == managed


def test_release_manifest_refuses_unpublished_or_unapproved_sources(isolated, monkeypatch):
    with pytest.raises(ValueError, match='approved'):
        installs.release_manifest('https://untrusted.example')
    monkeypatch.setattr(installs.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'{"installation":{}}'))
    with pytest.raises(ValueError, match='not published'):
        installs.release_manifest(installs.DEFAULT_WORKSPACE)


def test_bootstrap_adopts_registered_clone_without_clone_or_checkout(isolated, monkeypatch):
    bootstrap = script('bootstrap-dexops.py')
    isolated.mkdir()
    saved = record(isolated)
    installs.save_record(saved)
    monkeypatch.setattr(bootstrap, 'valid_repo', lambda path: str(path) == saved['repository'])
    calls = []

    def git(path, *args):
        calls.append(args)
        return '' if args[0] == 'status' else 'a' * 40

    monkeypatch.setattr(bootstrap, 'git', git)
    assert bootstrap.prepare_repository(isolated, 'a' * 40) == Path(saved['repository'])
    assert all(args[0] in ('status', 'rev-parse') for args in calls)


def test_bootstrap_migration_chooses_one_clone_and_refuses_ambiguity(isolated, monkeypatch):
    bootstrap = script('bootstrap-dexops.py')
    downloads = isolated.parent / 'Downloads'
    first = downloads / 'dexops-previous'
    first.mkdir(parents=True)
    monkeypatch.setattr(bootstrap, 'valid_repo', lambda path: path in (first, downloads / 'dexops-second'))
    assert bootstrap.find_repository(isolated) == first
    (downloads / 'dexops-second').mkdir()
    with pytest.raises(ValueError, match='Several earlier clones'):
        bootstrap.find_repository(isolated)


def test_bootstrap_stages_deployed_commit_without_changing_existing_clone(isolated, monkeypatch):
    bootstrap = script('bootstrap-dexops.py')
    repo = isolated / 'repository'
    monkeypatch.setattr(bootstrap, 'find_repository', lambda *args: repo)
    calls = []

    def git(path, *args):
        calls.append(args)
        return 'a' * 40 if args[0] == 'rev-parse' else ''

    monkeypatch.setattr(bootstrap, 'git', git)
    expected = isolated / 'releases' / ('b' * 40)
    assert bootstrap.prepare_repository(isolated, 'b' * 40) == expected
    assert ('fetch', 'origin', 'b' * 40) in calls
    assert ('worktree', 'add', '--detach', str(expected), 'b' * 40) in calls
    assert all(args[0] not in ('checkout', 'reset', 'pull') for args in calls)


@pytest.mark.parametrize('platform', ['win32', 'darwin', 'linux'])
def test_signin_startup_is_per_user_and_can_be_disabled(isolated, tmp_path, monkeypatch, platform):
    # Use the real implementation but route all files to tmp_path and mock COM.
    configure = script('../src/t2_bots/connect/startup.py').configure
    saved = record(isolated)
    runtime = Path(saved['runtime'])
    runtime.parent.mkdir(parents=True)
    runtime.with_name('pythonw.exe').touch()
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setattr(sys, 'platform', platform)
    commands = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kwargs: commands.append(args))
    configure(saved, True)
    assert saved['autostart'] is True
    if platform == 'win32':
        assert 'CreateShortcut' in commands[0][-1]
        assert 'pythonw.exe' in commands[0][-1]
        assert '--no-browser' in commands[0][-1]
        assert 'ExecutionPolicy' not in commands[0][-1]
    elif platform == 'darwin':
        target = tmp_path / 'Library/LaunchAgents/com.trydexops.companion.plist'
        data = plistlib.loads(target.read_bytes())
        assert data['RunAtLoad'] is True
        assert '--no-browser' in data['ProgramArguments']
    else:
        target = tmp_path / 'config/autostart/dexops.desktop'
        assert '--no-browser' in target.read_text()
        assert 'Terminal=false' in target.read_text()
    configure(saved, False)
    assert saved['autostart'] is False
    if platform != 'win32':
        assert not target.exists()
