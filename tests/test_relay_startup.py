import io
import threading
import time

import pytest

from t2_bots.network import relay


class Process:
    def __init__(self, stream, code=None):
        self.stdout = stream
        self.returncode = code
        self.stopped = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.stopped = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


@pytest.mark.parametrize('platform,expected', [('win32','NUL'),('darwin','/dev/null'),('linux','/dev/null')])
def test_relay_startup_uses_valid_options_and_reads_endpoint(monkeypatch, platform, expected):
    process = Process(io.StringIO('Welcome\ntcp://relay.example:12345\n'))
    commands = []
    monkeypatch.setattr(relay.sys, 'platform', platform)
    monkeypatch.setattr(relay.shutil, 'which', lambda _: 'ssh')
    monkeypatch.setattr(relay.subprocess, 'Popen', lambda cmd, **kw: commands.append(cmd) or process)
    manager = relay.PinggyRelayManager()
    monkeypatch.setattr(manager, '_monitor_stream', lambda: None)
    result = manager.start_tunnel(timeout_s=1)
    assert (result.host, result.port) == ('relay.example', 12345)
    assert 'UserKnownHostsFile=' + expected in commands[0]
    assert '-R0:127.0.0.1:8765' in commands[0]
    manager.stop_tunnel()
    assert process.stopped


def test_relay_preserves_ssh_failure_and_cleans_up(monkeypatch):
    process = Process(io.StringIO('Permission denied\n'), 255)
    monkeypatch.setattr(relay.shutil, 'which', lambda _: 'ssh')
    monkeypatch.setattr(relay.subprocess, 'Popen', lambda *a, **kw: process)
    manager = relay.PinggyRelayManager()
    with pytest.raises(RuntimeError, match='Permission denied'):
        manager.start_tunnel(timeout_s=1)
    assert process.stopped
    assert manager.process is None


def test_silent_ssh_cannot_block_timeout(monkeypatch):
    released = threading.Event()

    class Silent:
        def __iter__(self):
            released.wait(2)
            return iter(())

    process = Process(Silent())
    monkeypatch.setattr(relay.shutil, 'which', lambda _: 'ssh')
    monkeypatch.setattr(relay.subprocess, 'Popen', lambda *a, **kw: process)
    manager = relay.PinggyRelayManager()
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            manager.start_tunnel(timeout_s=.1)
        assert time.monotonic() - start < 1
        assert process.stopped
    finally:
        released.set()
