"""Characterize disconnect paths with real local sockets and simulated motors only."""
import asyncio
import time
import threading
from unittest.mock import AsyncMock

import pytest

from test_companion import FakeBus, profile, DEVICE
from t2_bots.connect.app import Companion, DirectoryUnavailable
from t2_bots.connect.hardware import Hardware
from t2_bots.connect.sessions import Sessions
from t2_bots_so101.driver.registers import Register


async def until(predicate, timeout=3):
    async def wait():
        while not predicate():
            await asyncio.sleep(.02)
    await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_healthy_local_following_survives_five_seconds():
    follower = Sessions(Hardware(lambda **_: FakeBus()))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        leader.enable_requested = True
        await until(lambda: leader.enabled)
        await asyncio.sleep(6)
        assert leader.status == follower.status == "following"
        assert not leader.error and not follower.error
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_browser_watchdog_stops_an_active_session_after_five_seconds(tmp_path):
    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), lambda: [DEVICE])
    station.store.data["arms"]["leader"] = DEVICE
    station.leader_sessions.status = "following"
    station.leader_sessions.stop = AsyncMock(side_effect=lambda: setattr(station.leader_sessions, "status", "idle"))
    start = station.last_browser = time.monotonic()
    worker = asyncio.create_task(station.watch())
    try:
        await until(lambda: station.leader_sessions.status == "idle", timeout=7)
        elapsed = time.monotonic() - start
        assert 5 <= elapsed < 7
        assert "browser heartbeat" in station.leader_sessions.error
        print(f"Browser watchdog stopped session at {elapsed:.2f}s")
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_directory_rejection_stops_leader_with_visible_reason(tmp_path):
    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), lambda: [])
    station.current_device = lambda role=None: {"port": "FAKE"}
    station.leader_sessions.status = "following"
    station.reservation = "test-follower"
    station.leader_sessions.stop = AsyncMock(side_effect=lambda: setattr(station.leader_sessions, "status", "idle"))

    def unavailable(*args, **kwargs):
        raise ValueError("Simulated directory outage")

    station.cloud = unavailable
    worker = asyncio.create_task(station.maintain_directory())
    try:
        await until(lambda: station.reservation is None)
        assert station.leader_sessions.status == "idle"
        assert station.directory_error == "Simulated directory outage"
        assert "reservation was rejected" in station.leader_sessions.error
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_slow_valid_motor_health_reads_no_longer_trigger_network_timeout():
    class SlowHealthBus(FakeBus):
        slow = False

        def read_byte(self, mid, reg):
            if self.slow and reg in (Register.PRESENT_VOLTAGE, Register.PRESENT_TEMPERATURE):
                time.sleep(.05)
            return super().read_byte(mid, reg)

    bus = SlowHealthBus()
    follower = Sessions(Hardware(lambda **_: bus))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        leader.enable_requested = True
        await until(lambda: leader.enabled)
        bus.slow = True
        await asyncio.sleep(3)
        assert leader.status == follower.status == "following", {
            "leader": leader.snapshot(), "follower": follower.snapshot()}
        assert not leader.error and not follower.error
        assert leader.reconnect_attempt == 0
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_local_serial_timeout_retains_usb_reason_and_never_reconnects():
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    leader.read = AsyncMock(side_effect=TimeoutError("Serial read timeout on Servo 2"))
    await leader.leader_loop()
    assert "USB/serial error" in leader.error
    assert "Servo 2" in leader.error
    assert leader.reconnect_attempt == 0


@pytest.mark.asyncio
async def test_directory_outage_keeps_connection_until_lease_expires(tmp_path):
    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), lambda: [DEVICE])
    station.store.data["arms"]["leader"] = DEVICE
    station.leader_sessions.status = "following"
    station.reservation = "test-follower"
    station.reservation_deadline = time.monotonic() + 3
    station.leader_sessions.stop = AsyncMock(side_effect=lambda: setattr(station.leader_sessions, "status", "idle"))
    station.cloud = lambda *args, **kwargs: (_ for _ in ()).throw(DirectoryUnavailable("Temporary outage"))
    tasks = [asyncio.create_task(station.watch()), asyncio.create_task(station.maintain_directory())]
    try:
        await until(lambda: bool(station.directory_error))
        assert station.leader_sessions.status == "following"
        assert station.reservation == "test-follower"
        await until(lambda: station.leader_sessions.status == "idle", timeout=4)
        assert "reservation expired" in station.leader_sessions.error
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_restores_link_but_requires_new_enable():
    follower_bus = FakeBus()
    follower = Sessions(Hardware(lambda **_: follower_bus))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        leader.enable_requested = True
        await until(lambda: leader.enabled)
        await follower.ws.close(code=1012, reason="Simulated temporary transport failure")
        await until(lambda: leader.status == "reconnecting")
        assert not leader.enabled and not leader.enable_requested
        await until(lambda: leader.status == "connected")
        assert leader.reconnect_attempt == 1
        assert "Connection restored" in leader.notice
        assert follower.pin not in str(leader.snapshot())
        await asyncio.sleep(.2)
        assert not follower.enabled
        assert all(v[Register.TORQUE_ENABLE] == 0 for v in follower_bus.values.values())
        leader.enable_requested = True
        await until(lambda: leader.enabled)
        assert follower.enabled
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_stop_cancels_pending_reconnect():
    follower = Sessions(Hardware(lambda **_: FakeBus()))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        await follower.ws.close(code=1012)
        await until(lambda: leader.status == "reconnecting")
        await leader.stop()
        await asyncio.sleep(1.2)
        assert leader.status == "idle"
        assert leader.worker is None and leader.ws is None
        assert not follower.busy
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_reconnect_attempts_are_bounded(monkeypatch):
    import t2_bots.connect.sessions as sessions
    monkeypatch.setattr(sessions, "RECONNECT_DELAYS", (.01, .01, .01))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    leader.open_peer = AsyncMock(side_effect=OSError("Link unavailable"))
    with pytest.raises(ValueError, match="three attempts"):
        await leader.reconnect("Link unavailable")
    assert leader.open_peer.await_count == 3
    assert not leader.enabled


@pytest.mark.asyncio
async def test_hung_directory_call_cannot_delay_expiry_or_revive_stopped_session(tmp_path):
    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), lambda: [DEVICE])
    station.store.data["arms"]["leader"] = DEVICE
    station.leader_sessions.status = "reconnecting"
    station.reservation = "test-follower"
    station.reservation_deadline = time.monotonic() + 2
    station.leader_sessions.stop = AsyncMock(side_effect=lambda: setattr(station.leader_sessions, "status", "idle"))
    entered, finish = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        finish.wait(5)
        return {"reserved_until": time.time() + 45}

    station.cloud = blocked
    tasks = [asyncio.create_task(station.watch()), asyncio.create_task(station.maintain_directory())]
    try:
        await until(entered.is_set)
        await until(lambda: station.leader_sessions.status == "idle")
        assert "reservation expired" in station.leader_sessions.error
        finish.set()
        await asyncio.sleep(.15)
        assert station.reservation is None and station.reservation_deadline == 0
    finally:
        finish.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_transient_directory_failure_recovers_without_disconnecting(tmp_path):
    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), lambda: [DEVICE])
    station.store.data["arms"]["leader"] = DEVICE
    station.leader_sessions.status = "following"
    station.reservation = "test-follower"
    original_deadline = station.reservation_deadline = time.monotonic() + 5
    calls = []

    def intermittent(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise DirectoryUnavailable("Temporary outage")
        return {"reserved_until": time.time() + 45}

    station.cloud = intermittent
    tasks = [asyncio.create_task(station.watch()), asyncio.create_task(station.maintain_directory())]
    try:
        await until(lambda: bool(station.directory_error))
        await until(lambda: station.reservation_deadline > original_deadline)
        assert station.leader_sessions.status == "following"
        assert station.directory_error == ""
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_motor_fault_does_not_auto_reconnect_or_reenable():
    bus = FakeBus()
    follower = Sessions(Hardware(lambda **_: bus))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        leader.enable_requested = True
        await until(lambda: leader.enabled)
        bus.values[2][Register.STATUS_ERROR] = 4
        await until(lambda: leader.status == "fault")
        await until(lambda: follower.status == "fault")
        assert "Motor 2" in leader.error
        assert leader.reconnect_attempt == 0
        assert not follower.enabled
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_owner_stopping_follower_is_not_treated_as_transient_failure():
    follower = Sessions(Hardware(lambda **_: FakeBus()))
    leader = Sessions(Hardware(lambda **_: FakeBus()))
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        await follower.stop()
        await until(lambda: leader.status == "fault")
        assert leader.reconnect_attempt == 0
        assert not leader.enabled
    finally:
        await leader.stop()
        await follower.stop()


@pytest.mark.asyncio
async def test_slow_usb_enumeration_does_not_block_motor_exchange(tmp_path):
    def slow_scanner():
        time.sleep(.6)  # Longer than the network watchdog, but not on its loop.
        return [DEVICE]

    station = Companion(tmp_path, Hardware(lambda **_: FakeBus()), slow_scanner)
    station.store.data["arms"]["leader"] = DEVICE
    follower = Sessions(Hardware(lambda **_: FakeBus()))
    watcher = None
    try:
        await follower.listen("FAKE", profile(), listen_port=0)
        port = follower.server.sockets[0].getsockname()[1]
        await station.leader_sessions.connect("FAKE", profile(), f"ws://127.0.0.1:{port}", follower.pin)
        station.leader_sessions.enable_requested = True
        await until(lambda: station.leader_sessions.enabled)
        watcher = asyncio.create_task(station.watch())
        await asyncio.sleep(2)
        assert station.leader_sessions.status == follower.status == "following"
        assert station.leader_sessions.reconnect_attempt == 0
    finally:
        if watcher:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await station.leader_sessions.stop()
        await follower.stop()
