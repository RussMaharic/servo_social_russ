"""Real HTTP/WebSocket onboarding between isolated stations and simulated motors."""
import asyncio
import json
import socket
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
import pytest
import uvicorn

from test_connect import FakeBus, DEVICE
from t2_bots.connect.app import create_app
from t2_bots.connect.directory import create_app as directory_app
from t2_bots.connect.hardware import Hardware
from t2_bots_so101.driver.registers import Register


@asynccontextmanager
async def serving(factory):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    app = factory(port)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.01)
        assert server.started
        yield app, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        listener.close()


async def post(client, path, body):
    response = await client.post("/api/" + path, json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def eventually(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(.02)
    assert predicate()


@pytest.mark.asyncio
async def test_complete_onboarding_remote_following_and_restart(tmp_path):
    buses = {role: FakeBus() for role in ("leader", "follower")}
    for values in buses["leader"].values.values():
        values[Register.PRESENT_VOLTAGE] = 53
    devices = {role: {**DEVICE, "identity": DEVICE["identity"] + role, "port": "FAKE-" + role}
               for role in buses}
    async with AsyncExitStack() as stack:
        _, directory_url = await stack.enter_async_context(serving(lambda _: directory_app(tmp_path / "directory.sqlite3")))
        clients, stations = {}, {}
        for role, bus in buses.items():
            app, url = await stack.enter_async_context(serving(
                lambda port, r=role, b=bus: create_app(tmp_path / r, Hardware(lambda **_: b), lambda: [devices[r]], port)))
            station = stations[role] = app.state.station
            client = clients[role] = await stack.enter_async_context(httpx.AsyncClient(base_url=url, timeout=15))
            state = (await client.get("/api/state")).json()
            client.headers["X-T2-Session"] = state["session_token"]
            # Detection alone cannot unlock operations.
            assert (await client.post("/api/arm", json={"role":role,"identity":devices[role]["identity"]})).status_code == 409
            await post(client, "runtime/confirm", {"confirmed":True,"build_id":state["runtime"]["build_id"]})
            await post(client, "identity", {"username":"test_" + role,"directory_url":directory_url})
            await post(client, "arm", {"role":role,"identity":devices[role]["identity"]})
            assert (await post(client, "inspect", {}))["passed"]
            await post(client, "calibration/start", {"supported":True})
            await post(client, "calibration/reference", {})
            for position in (1700, 2300, 2000):
                for values in bus.values.values():
                    values[Register.PRESENT_POSITION] = position
                assert (await client.get("/api/state")).json()["capture"]
            await post(client, "calibration/save", {"reviewed":True})
            profile_before = station.store.profile_path(role).read_bytes()
            certificate = await post(client, "certify", {"confirmed":True})
            assert certificate["grade"] == "A+"
            assert station.store.profile_path(role).read_bytes() == profile_before
            state = (await client.get("/api/state")).json()
            assert state["calibrated"] and state["certified"]
            assert (await client.get("/api/certificate")).json()["arm_id"] == certificate["arm_id"]
            assert all(v[Register.TORQUE_ENABLE] == 0 for v in bus.values.values())
            bus.writes.clear()

        # Reserve an isolated listener port; never use the operator's real 8765.
        with socket.socket() as temporary:
            temporary.bind(("127.0.0.1", 0))
            follower_port = temporary.getsockname()[1]
        listen = stations["follower"].sessions.listen
        async def test_listener(*args, **kwargs):
            return await listen(*args, listen_port=follower_port, **kwargs)
        stations["follower"].sessions.listen = test_listener
        shared = await post(clients["follower"], "share", {"confirmed":True,"relay":False,
                            "endpoint":f"ws://127.0.0.1:{follower_port}","label":"Test follower"})
        directory = (await clients["leader"].get("/api/followers")).json()
        follower = directory["followers"][0]
        assert follower["available"] and follower["owner"] == "test_follower"
        assert "pin" not in json.dumps(directory)
        await post(clients["leader"], "session/connect", {"id":follower["id"],"pin":shared["pin"]})
        await asyncio.sleep(.1)
        assert not stations["leader"].sessions.enabled
        assert not buses["follower"].writes  # Connecting must remain read-only.
        await post(clients["leader"], "session/enable", {"confirmed":True})
        await eventually(lambda: stations["follower"].sessions.enabled)
        for values in buses["leader"].values.values():
            values[Register.PRESENT_POSITION] += 100
        await eventually(lambda: buses["follower"].values[1][Register.GOAL_POSITION] > 2000)
        assert all(1730 <= v[Register.GOAL_POSITION] <= 2270 for v in buses["follower"].values.values())
        await post(clients["leader"], "session/stop", {})
        await eventually(lambda: not stations["follower"].sessions.enabled)
        assert all(v[Register.TORQUE_ENABLE] == 0 for v in buses["follower"].values.values())
        assert (await clients["leader"].get("/api/followers")).json()["followers"][0]["available"]
        await post(clients["follower"], "session/stop", {})
        assert not (await clients["leader"].get("/api/followers")).json()["followers"]

    # Restart from persisted station state without redoing username/calibration.
    app = create_app(tmp_path / "leader", Hardware(lambda **_: buses["leader"]), lambda: [devices["leader"]])
    station = app.state.station
    assert station.store.data["username"] == "test_leader"
    assert station.calibrated() and station.ready()
