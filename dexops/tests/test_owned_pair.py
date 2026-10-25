"""Owner-added arms, isolated profiles, and concurrent sharing/control."""
from contextlib import AsyncExitStack

import httpx
import pytest

from test_companion import DEVICE, FakeBus, digest, profile, local
from test_end_to_end import serving, post, eventually
from t2_bots.connect.app import create_app
from t2_bots.connect.directory import create_app as directory_app
from t2_bots.connect.hardware import Hardware
from t2_bots_so101.driver.registers import Register


async def add_calibrated(client, station, device, role):
    await post(client, "arm", {"role": role, "identity": device["identity"], "name": "Desk " + role})
    saved = profile()
    station.store.save_profile(role, saved)
    station.arm.update(calibration_hash=digest(saved))
    station.store.save()


@pytest.mark.asyncio
async def test_owner_registers_pair_and_controls_own_then_remote_follower(tmp_path):
    devices = [{**DEVICE, "identity": "usb-" + role, "port": role} for role in ("leader", "follower")]
    buses = {role: FakeBus(role) for role in ("leader", "follower")}
    remote_bus = FakeBus("remote")
    async with AsyncExitStack() as stack:
        _, directory_url = await stack.enter_async_context(serving(lambda _: directory_app(tmp_path / "directory.sqlite3")))
        app, url = await stack.enter_async_context(serving(lambda port: create_app(
            tmp_path / "owner", Hardware(lambda port: buses[port]), lambda: devices, port)))
        station = app.state.station
        client = await stack.enter_async_context(httpx.AsyncClient(base_url=url, timeout=15))
        state = (await client.get("/api/state")).json()
        client.headers["X-T2-Session"] = state["session_token"]
        await post(client, "runtime/confirm", {"confirmed": True, "build_id": state["runtime"]["build_id"]})
        await post(client, "identity", {"username": "pair_owner", "directory_url": directory_url})
        for role, device in zip(("leader", "follower"), devices):
            await add_calibrated(client, station, device, role)
        state = (await client.get("/api/state")).json()
        assert all(state["arms"][r]["ready"] for r in ("leader", "follower"))
        assert (await client.post("/api/arm", json={"role": "follower", "identity": "usb-leader"})).status_code == 400
        original = station.store.profile_path("leader").read_bytes()
        await post(client, "arm/select", {"role": "leader"})
        assert station.store.profile_path("leader").read_bytes() == original
        # Sharing uses the registered follower even while leader setup is selected.
        listen = station.follower_sessions.listen
        async def ephemeral_listener(*args, **kwargs):
            result = await listen(*args, listen_port=0, **kwargs)
            return result
        station.follower_sessions.listen = ephemeral_listener
        # The application advertises a real listener address; use a prebound test
        # address selected by the test's wrapper after listening on port 0.
        def publish_local(method, path, payload=None, **kwargs):
            if method == "PUT" and path == "/v1/follower":
                port = station.follower_sessions.server.sockets[0].getsockname()[1]
                payload = {**payload, "endpoint": f"ws://127.0.0.1:{port}"}
            return cloud(method, path, payload, **kwargs)
        cloud = station.cloud
        station.cloud = publish_local
        shared = await post(client, "share", {"confirmed": True, "relay": False, "endpoint": "ws://127.0.0.1:8765", "label": "My desk follower"})
        port = station.follower_sessions.server.sockets[0].getsockname()[1]
        station.follower_sessions.endpoint = f"ws://127.0.0.1:{port}"
        assert (await client.post("/api/arm", json={"role": "follower", "identity": "usb-follower"})).status_code == 400
        for bus in buses.values(): bus.writes.clear()
        own_id = station.store.data["device_id"]
        await post(client, "session/connect", {"id": own_id, "pin": shared["pin"]})
        state = (await client.get("/api/state")).json()
        assert state["publishing"] and state["leader_session"]["status"] == "connected"
        assert state["follower_session"]["status"] == "connected"
        assert not buses["follower"].writes
        # Both directions use the explicit-enable protocol.
        await post(client, "session/enable", {"confirmed": True})
        await eventually(lambda: station.follower_sessions.enabled)
        buses["leader"].values[1][Register.PRESENT_POSITION] = 2100
        await eventually(lambda: buses["follower"].values[1][Register.GOAL_POSITION] > 2000)
        await post(client, "session/stop", {"role": "leader"})
        await eventually(lambda: station.follower_sessions.status == "sharing")
        assert station.publishing and station.follower_sessions.server is not None
        assert all(v[Register.TORQUE_ENABLE] == 0 for v in buses["follower"].values.values())
        # Connect the same leader to another owner's follower while our follower
        # remains shared. This is actual loopback WebSocket robot traffic.
        from t2_bots.connect.sessions import Sessions
        remote = Sessions(Hardware(lambda **kwargs: remote_bus))
        guest = Sessions(Hardware(lambda **kwargs: FakeBus("guest-leader")))
        await remote.listen("remote", profile(), listen_port=0)
        try:
            remote_port = remote.server.sockets[0].getsockname()[1]
            directory = await stack.enter_async_context(httpx.AsyncClient(base_url=directory_url))
            identity = {"username": "remote_owner", "device_id": "remote-device-" + "x" * 24, "credential": "private-" + "y" * 40}
            assert (await directory.post("/v1/identity", json=identity)).status_code == 200
            headers = {"X-Device-ID": identity["device_id"], "Authorization": "Bearer " + identity["credential"]}
            assert (await directory.put("/v1/follower", headers=headers, json={"label": "Remote follower", "calibrated": True, "endpoint": f"ws://127.0.0.1:{remote_port}"})).status_code == 200
            await post(client, "session/connect", {"id": identity["device_id"], "pin": remote.pin})
            assert station.publishing and station.leader_sessions.status == "connected"
            await guest.connect("guest-leader", profile(), station.follower_sessions.endpoint, shared["pin"])
            assert not station.follower_sessions.enabled
            guest.enable_requested = True
            await eventually(lambda: station.follower_sessions.enabled)
            assert station.leader_sessions.status == "connected"
            # Stopping sharing does not disconnect a leader using a remote arm.
            await post(client, "session/stop", {"role": "follower"})
            assert station.leader_sessions.status == "connected" and not station.publishing
            await post(client, "session/stop", {"role": "leader"})
        finally:
            await guest.stop()
            await remote.stop()
    restored = create_app(tmp_path / "owner", Hardware(lambda port: buses[port]), lambda: devices).state.station
    assert restored.ready("leader") and restored.ready("follower")
    assert restored.store.data["username"] == "pair_owner"


def test_arm_status_tracks_disconnected_follower_independently(local):
    # Import this fixture here for the standard isolated station.
    client, station, bus, devices = local
    follower = {**DEVICE, "identity": "follower-usb", "port": "OTHER"}
    devices.append(follower)
    assert client.post("/api/arm", json={"role": "leader", "identity": DEVICE["identity"]}).status_code == 200
    assert client.post("/api/arm", json={"role": "follower", "identity": follower["identity"]}).status_code == 200
    devices.remove(follower)
    state = client.get("/api/state").json()
    assert state["arms"]["leader"]["connected"] and not state["arms"]["follower"]["connected"]
    assert client.post("/api/arm/select", json={"role": "leader"}).status_code == 200
    assert station.role == "leader"
