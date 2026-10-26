import asyncio
import json
import time
import sys
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from t2_bots.connect.app import create_app
from t2_bots.connect.directory import create_app as directory_app, endpoint_url
from t2_bots.connect.hardware import Hardware
from t2_bots.connect.storage import digest
from t2_bots_so101.driver.registers import Register

class FakeBus:
    def __init__(self, port="FAKE"):
        self.port = port
        self.closed = False
        self.values = {}
        self.missing = None
        self.fail_torque = False
        self.writes = []
        for mid in range(1, 7):
            self.values[mid] = {Register.PRESENT_POSITION: 2000, Register.PRESENT_VOLTAGE: 120,
                Register.PRESENT_TEMPERATURE: 30, Register.STATUS_ERROR: 0,
                Register.MIN_ANGLE_LIMIT: 0, Register.MAX_ANGLE_LIMIT: 3300,
                Register.TORQUE_ENABLE: 0, Register.GOAL_POSITION: 2000, Register.LOCK: 1}

    def open(self): self.closed = False
    def close(self): self.closed = True
    def ping(self, mid): return True
    def read_byte(self, mid, reg):
        if reg == self.missing: return None
        return self.values[mid][reg]
    read_word = read_byte

    def write_byte(self, mid, reg, val):
        self.writes.append((mid, reg, val))
        if reg != Register.TORQUE_ENABLE or not self.fail_torque:
            self.values[mid][reg] = val
    write_word = write_byte

    def write_byte_verified(self, mid, reg, val):
        self.write_byte(mid, reg, val)
        if self.read_byte(mid, reg) != val: raise ValueError("Readback failed")

    def sync_read_positions(self, ids):
        return {mid: self.values[mid][Register.PRESENT_POSITION] for mid in ids}

    def sync_write_positions(self, targets):
        for mid, val in targets.items(): self.write_word(mid, Register.GOAL_POSITION, val)

def profile():
    from t2_bots.core.calibration import JOINT_ID_MAP
    return {name:{"id":mid,"range_min":1000,"range_max":3000,"homing_offset":0,"drive_mode":0}
            for mid,name in JOINT_ID_MAP.items()}

DEVICE = {"identity":"1234:5678:TEST","port":"FAKE","label":"Test USB", "serial":"TEST", "stable_identity":True}

def test_directory_runtime_error_does_not_report_controller_failure(local, monkeypatch):
    client, station, _, _ = local
    from t2_bots.connect import app as companion
    def missing_tls_file(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(companion.urllib.request, "urlopen", missing_tls_file)
    response = client.post("/api/identity", json={"username":"operator", "directory_url":"http://127.0.0.1:8090"})
    assert response.status_code == 400
    assert "directory connection" in response.json()["detail"]
    assert "controller" not in response.json()["detail"].lower()
    assert not station.store.data["username"]
    assert not station.store.data["directory_url"]

def test_missing_tls_data_cannot_mark_runtime_compatible(monkeypatch):
    from t2_bots.connect import runtime
    def missing_tls_file():
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(runtime.ssl, "create_default_context", missing_tls_file)
    snapshot = runtime.Runtime().snapshot()
    assert not snapshot["compatible"]
    assert next(c for c in snapshot["checks"] if c["id"] == "tls")["status"] == "missing"

@pytest.fixture
def local(tmp_path):
    bus = FakeBus()
    devices = [DEVICE.copy()]
    app = create_app(tmp_path, Hardware(lambda **kwargs: bus), lambda: devices)
    with TestClient(app, base_url="http://127.0.0.1:4840") as client:
        token = client.get("/api/state").json()["session_token"]
        client.headers["X-T2-Session"] = token
        runtime=client.get("/api/state").json()["runtime"]
        assert client.post("/api/runtime/confirm",json={"confirmed":True,"build_id":runtime["build_id"]}).status_code==200
        yield client, app.state.station, bus, devices

def assign(client, role="leader"):
    return client.post("/api/arm", json={"identity":DEVICE["identity"],"role":role})

def test_calibrated_follower_needs_no_certificate(local):
    client, station, bus, _ = local
    assert assign(client, "follower").status_code == 200
    saved = profile()
    station.store.save_profile("follower", saved)
    station.arm["calibration_hash"] = digest(saved)
    before = station.store.profile_path("follower").read_bytes()
    assert client.get("/api/state").json()["ready"]
    assert not station.arm.get("certificate")
    assert not bus.writes
    assert station.store.profile_path("follower").read_bytes() == before

def test_public_relay_failure_returns_actionable_json_instead_of_failed_fetch(local, monkeypatch):
    client, station, _, _ = local
    assert assign(client, "follower").status_code == 200
    saved = profile()
    station.store.save_profile("follower", saved)
    station.arm["calibration_hash"] = digest(saved)
    station.store.data["username"] = "operator"
    station.store.save()

    async def relay_failure(*args, **kwargs):
        raise RuntimeError("SSH process terminated unexpectedly")

    monkeypatch.setattr(station.follower_sessions, "listen", relay_failure)
    response = client.post("/api/share", json={
        "confirmed": True, "relay": True, "label": "My follower"})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert "sharing could not complete" in response.json()["detail"].lower()
    assert station.follower_sessions.status == "idle"

def test_loopback_and_mutation_guards(local):
    client, station, _, _ = local
    assert client.get("/api/state", headers={"Host":"evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"Origin":"https://evil.example"}).status_code == 403
    assert client.post("/api/inspect", headers={"X-T2-Session":"wrong"}).status_code == 403
    assert "credential" not in client.get("/api/state").json()
    assert client.post("/api/arm", content="x"*17000).status_code == 413

def test_update_handoff_requires_session_token_and_idle_station(local):
    client, station, _, _ = local
    closed = []
    client.app.state.shutdown = lambda: closed.append(True)
    assert client.post('/api/runtime/shutdown', headers={'X-T2-Session':'wrong'},
                       json={'confirmed':True}).status_code == 403
    station.publishing = True
    assert client.post('/api/runtime/shutdown', json={'confirmed':True}).status_code == 400
    station.publishing = False
    station.leader_sessions.status = 'connected'
    assert client.post('/api/runtime/shutdown', json={'confirmed':True}).status_code == 400
    station.leader_sessions.status = 'idle'
    assert client.post('/api/runtime/shutdown', json={'confirmed':True}).json() == {'stopping':True}

def test_expired_reservation_cannot_enable_movement(local):
    client, station, _, _ = local
    station.leader_sessions.status = "connected"
    station.reservation = "test-follower"
    station.reservation_deadline = time.monotonic() - 1
    response = client.post('/api/session/enable', json={'confirmed': True})
    assert response.status_code == 400
    assert "reservation expired" in response.json()['detail']
    assert not station.leader_sessions.enable_requested

def test_leader_connection_failure_returns_json_with_cors_and_releases_reservation(local, monkeypatch):
    client, station, _, _ = local
    assert assign(client, "leader").status_code == 200
    saved = profile()
    station.store.save_profile("leader", saved)
    station.arm["calibration_hash"] = digest(saved)
    station.store.data.update(username="operator", directory_url="https://directory.example")
    calls = []

    def cloud(method, path, payload=None, **kwargs):
        calls.append((method, path))
        return {"endpoint":"ws://follower.example:8765"}

    async def failed_connect(*args, **kwargs):
        raise RuntimeError("WebSocket handshake rejected")

    monkeypatch.setattr(station, "cloud", cloud)
    monkeypatch.setattr(station.leader_sessions, "connect", failed_connect)
    origin = "https://servosocialruss.vercel.app"
    response = client.post("/api/session/connect", headers={"Origin":origin},
                           json={"id":"remote-follower", "pin":"123456"})
    assert response.status_code == 400
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "WebSocket handshake rejected" in response.json()["detail"]
    assert ("DELETE", "/v1/followers/remote-follower/reserve") in calls
    assert station.reservation is None
    assert station.leader_sessions.status == "idle"

@pytest.mark.parametrize("origin", [
    "https://play.trydexops.com",
    "https://servosocialruss.vercel.app",
])
def test_deployed_workspace_can_use_loopback_companion_without_redirect(local, origin):
    client, _, _, _ = local
    response = client.get("/api/state", headers={"Origin":origin, "Sec-Fetch-Site":"cross-site"})
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    preflight = client.options("/api/runtime/check", headers={
        "Origin":origin,
        "Access-Control-Request-Method":"POST",
        "Access-Control-Request-Headers":"content-type,x-t2-session",
        "Access-Control-Request-Private-Network":"true",
    })
    assert preflight.status_code == 200, preflight.text
    assert preflight.headers["Access-Control-Allow-Origin"] == origin
    assert preflight.headers["Access-Control-Allow-Private-Network"] == "true"

def test_empty_station_and_real_device_detection(local):
    client, _, _, devices = local
    state = client.get("/api/state").json()
    assert not state["ready"] and state["session"]["status"] == "idle"
    assert assign(client).status_code == 200
    assert client.post("/api/inspect").json()["passed"]
    devices.clear()
    assert not client.get("/api/state").json()["connected"]
    assert client.post("/api/inspect").status_code == 400

def test_missing_motor_read_never_passes(local):
    client, _, bus, _ = local
    assign(client)
    bus.missing = Register.PRESENT_VOLTAGE
    assert client.post("/api/inspect").status_code == 400
    assert client.get("/api/state").json()["inspection"] is None

def test_occupied_serial_port_has_recoverable_error(local):
    client,station,_,_=local
    assign(client)
    def occupied(**kwargs): raise PermissionError("Port is in use")
    station.hardware.bus_factory=occupied
    response=client.post("/api/inspect")
    assert response.status_code==409
    assert "Close other serial apps" in response.json()["detail"]

def test_inspection_does_not_expire_while_preparing_calibration(local):
    client, station, _, _ = local
    assign(client)
    assert client.post("/api/inspect").json()["passed"]
    station.inspection["at"] -= 120
    assert client.get("/api/state").json()["inspection"]["passed"]
    # Starting calibration still measures the actual hardware again.
    station.hardware.bus_factory = lambda **kwargs: (_ for _ in ()).throw(ValueError("Fresh hardware check failed"))
    assert client.post("/api/calibration/start",json={"supported":True}).status_code == 400

def test_calibration_failure_is_visible_to_every_poll_and_tab(local):
    client, _, bus, _ = local
    assign(client)
    assert client.post("/api/inspect").json()["passed"]
    assert client.post("/api/calibration/start",json={"supported":True}).status_code == 200
    bus.missing = Register.PRESENT_POSITION
    first = client.get("/api/state").json()
    second = client.get("/api/state").json()
    assert "encoder position" in first["capture_error"]
    assert second["capture_error"] == first["capture_error"]
    assert second["capture"] is None
    bus.missing = None
    assert client.post("/api/calibration/start",json={"supported":True}).status_code == 200
    assert client.get("/api/state").json()["capture_error"] == ""

def test_inspection_cannot_open_another_bus_during_calibration(local):
    client, _, bus, _ = local
    assign(client)
    assert client.post("/api/calibration/start",json={"supported":True}).status_code == 200
    assert client.post("/api/inspect").status_code == 400
    assert not bus.closed
    assert client.get("/api/state").json()["capture"] is not None

def test_runtime_detection_alone_does_not_approve_installation(tmp_path):
    app=create_app(tmp_path,Hardware(lambda **kwargs:FakeBus()),lambda:[DEVICE])
    with TestClient(app,base_url="http://127.0.0.1:4840") as client:
        data=client.get("/api/state").json()
        assert data["version"]=="0.3.1" and data["api_version"]==1
        assert data["runtime"]["kind"]=="source"
        assert not data["runtime"]["acknowledged"]
        client.headers["X-T2-Session"]=data["session_token"]
        assert assign(client).status_code==409
        assert client.post("/api/runtime/confirm",json={"confirmed":True,"build_id":"stale"}).status_code==400
        assert client.post("/api/runtime/confirm",json={"confirmed":True,"build_id":data["runtime"]["build_id"]}).status_code==200
        assert assign(client).status_code==200
        assert client.get("/api/state").json()["runtime"]["acknowledged"]

@pytest.mark.parametrize("system",["win32","darwin","linux"])
def test_runtime_supports_readme_platforms(monkeypatch,system):
    from t2_bots.connect import runtime
    # Change the runtime's view, not ssl/asyncio's view of the real host OS.
    monkeypatch.setattr(runtime,"sys",SimpleNamespace(**{**vars(sys),"platform":system}))
    monkeypatch.setattr(runtime.shutil,"which",lambda _:None)
    result=runtime.Runtime().snapshot()
    assert result["platform"]==system and result["compatible"]
    ssh=next(c for c in result["checks"] if c["id"]=="ssh")
    assert not ssh["required"] and ssh["status"]=="optional_missing"

def test_new_build_requires_confirmation_again():
    from t2_bots.connect.runtime import Runtime
    runtime=Runtime(); approval=runtime.approval()
    assert runtime.snapshot(approval)["acknowledged"]
    runtime.build="a-new-build"
    assert not runtime.snapshot(approval)["acknowledged"]

def test_outdated_transport_is_not_a_verified_runtime(monkeypatch):
    import websockets
    from t2_bots.connect.runtime import Runtime
    monkeypatch.setattr(websockets,"__version__","11.0")
    result=Runtime().snapshot()
    assert not result["compatible"]
    assert next(c for c in result["checks"] if c["id"]=="websockets")["status"]=="missing"

def test_launcher_does_not_silently_reuse_stale_service(monkeypatch):
    from t2_bots.connect import app as companion
    from io import BytesIO
    import sys
    monkeypatch.setattr(sys,"argv",["t2-connect","--no-browser"])
    monkeypatch.setattr(companion.urllib.request,"urlopen",lambda *a,**kw:BytesIO(json.dumps({"service":"t2-connect","version":"0.3.0"}).encode()))
    def forbidden(*args,**kwargs): raise AssertionError("Launcher reused an old app or started a new listener")
    monkeypatch.setattr(companion.webbrowser,"open",forbidden)
    import uvicorn
    monkeypatch.setattr(uvicorn,"run",forbidden)
    with pytest.raises(SystemExit) as result:
        companion.main()
    assert result.value.code==1

def test_relaunch_keeps_focus_on_the_existing_workspace_tab(monkeypatch, capsys):
    from t2_bots.connect import app as companion
    from io import BytesIO
    import sys
    current = companion.Runtime()
    response = {"service":"t2-connect", "version":companion.__version__,
                "api_version":companion.API_VERSION,
                "runtime":{"build_id":current.build}}
    monkeypatch.setattr(sys,"argv",["t2-connect"])
    monkeypatch.setattr(companion.urllib.request,"urlopen",
                        lambda *a,**kw:BytesIO(json.dumps(response).encode()))
    def forbidden(*args,**kwargs):
        raise AssertionError("Relaunch opened another tab or listener")
    monkeypatch.setattr(companion.webbrowser,"open",forbidden)
    import uvicorn
    monkeypatch.setattr(uvicorn,"run",forbidden)
    companion.main()
    output = capsys.readouterr().out
    assert "already running" in output
    assert "workspace tab that is already open" in output

def test_dexops_relaunch_opens_deployed_workspace_when_companion_is_running(monkeypatch, capsys):
    from t2_bots.connect import app as companion
    from io import BytesIO
    import sys
    current = companion.Runtime()
    response = {"service":"t2-connect", "version":companion.__version__,
                "api_version":companion.API_VERSION,
                "runtime":{"build_id":current.build}}
    monkeypatch.setattr(sys,"argv",["dexops"])
    monkeypatch.setattr(companion.urllib.request,"urlopen",
                        lambda *a,**kw:BytesIO(json.dumps(response).encode()))
    opened = []
    monkeypatch.setattr(companion.webbrowser,"open",opened.append)
    import uvicorn
    monkeypatch.setattr(uvicorn,"run",lambda *a,**kw:pytest.fail("started a second companion listener"))
    companion.dexops_main()
    assert opened == ["https://servosocialruss.vercel.app/"]
    assert "Opened the deployed Dexops workspace" in capsys.readouterr().out

def test_calibration_reference_travel_and_binding(local):
    client, station, bus, _ = local
    assign(client)
    assert client.post("/api/calibration/start",json={}).status_code == 400
    assert client.post("/api/calibration/start",json={"supported":True}).status_code == 200
    assert client.post("/api/calibration/save",json={"reviewed":True}).status_code == 400
    assert client.post("/api/calibration/reference",json={}).status_code == 200
    for mid in range(1,7): bus.values[mid][Register.PRESENT_POSITION] = 2200
    state=client.get("/api/state").json()
    assert all(r["travel"]==200 for r in state["capture"]["ranges"])
    assert client.post("/api/calibration/save",json={"reviewed":True}).status_code == 200
    assert station.store.profile_path("leader").exists()
    assert client.get("/api/state").json()["ready"]
    assert bus.closed

def test_calibration_change_invalidates_readiness(local):
    client,station,_,_=local
    assign(client)
    saved=profile(); station.store.save_profile("leader",saved)
    station.arm.update(calibration_hash=digest(saved),certificate_calibration_hash=digest(saved),certificate={"grade":"legacy"})
    assert client.get("/api/state").json()["ready"]
    assert client.get("/api/certificate").status_code == 404
    saved["gripper"]["range_min"]+=1
    station.store.save_profile("leader",saved)
    assert not client.get("/api/state").json()["ready"]

def test_removed_certification_endpoint_preserves_calibration(local):
    client,station,bus,_=local
    assign(client)
    saved=profile(); station.store.save_profile("leader",saved)
    station.arm["calibration_hash"]=digest(saved)
    before=station.store.profile_path("leader").read_bytes()
    response=client.post("/api/certify",json={"confirmed":True})
    assert response.status_code==405
    assert client.get("/api/state").json()["ready"]
    assert station.store.profile_path("leader").read_bytes()==before
    assert all(bus.values[m][Register.TORQUE_ENABLE]==0 for m in range(1,7))

def test_release_attempts_every_motor_after_failure():
    class PartialFailure(FakeBus):
        def write_byte_verified(self,mid,reg,val):
            self.writes.append((mid,reg,val))
            if mid==1: raise ValueError("Unavailable motor")
            self.values[mid][reg]=val
    bus=PartialFailure()
    with pytest.raises(ValueError,match="unverified"):
        Hardware().torque(bus,False)
    assert {w[0] for w in bus.writes}==set(range(1,7))

@pytest.fixture
def hub(tmp_path):
    app=directory_app(tmp_path/"directory.sqlite3")
    with TestClient(app) as client: yield client,app.state.directory

def register(client,name="operator",device="device-a-"+"a"*24):
    identity={"username":name,"device_id":device,"credential":"secret-"+"b"*40}
    response=client.post("/v1/identity",json=identity)
    return response,{"X-Device-ID":device,"Authorization":"Bearer "+identity["credential"]}

def test_username_uniqueness_and_device_ownership(hub):
    client,_=hub
    assert register(client)[0].status_code==200
    assert register(client)[0].status_code==200
    assert register(client,"OPERATOR","device-b-"+"c"*24)[0].status_code==409
    assert client.post("/v1/identity",json={"username":"operator","device_id":"device-a-"+"a"*24,"credential":"wrong"*10}).status_code==403
    assert register(client,"../bad")[0].status_code==422

def test_directory_expiry_and_exclusive_reservation(hub):
    client,directory=hub
    _,owner=register(client,"owner")
    _,leader=register(client,"leader","device-b-"+"b"*24)
    _,other=register(client,"other","device-c-"+"c"*24)
    response=client.put("/v1/follower",headers=owner,json={"label":"Lab arm","endpoint":"ws://lab.example:8765","calibrated":True})
    assert response.status_code==200
    follower=client.get("/v1/followers").json()["followers"][0]
    assert follower["available"] and "pin" not in follower
    path=f'/v1/followers/{follower["id"]}/reserve'
    assert client.post(path,headers=leader).status_code==200
    assert client.post(path,headers=other).status_code==409
    assert not client.get("/v1/followers").json()["followers"][0]["available"]
    with directory.db() as db: db.execute("UPDATE followers SET seen=?",(time.time()-30,))
    assert client.get("/v1/followers").json()["followers"]==[]

def test_publication_requires_credential_and_calibration(hub):
    client,_=hub
    payload={"label":"Arm","endpoint":"ws://lab.example:8765","calibrated":True}
    assert client.put("/v1/follower",json=payload).status_code==403
    _,headers=register(client)
    payload["calibrated"]=False
    assert client.put("/v1/follower",headers=headers,json=payload).status_code==422

@pytest.mark.parametrize("url",["http://example.com","ws://user:pin@example.com","ws://x:99999","file:///tmp/a"])
def test_endpoint_validation(url):
    with pytest.raises(ValueError): endpoint_url(url)

@pytest.mark.asyncio
async def test_session_connect_does_not_move_then_enable_and_stop():
    from t2_bots.connect.sessions import Sessions
    follower_bus, leader_bus = FakeBus(), FakeBus()
    # A leader can start from any valid encoder position. Its current pose is
    # the relative-motion baseline and connecting never energises the follower.
    leader_bus.values[2][Register.PRESENT_POSITION] = 900
    follower_bus.values[2][Register.PRESENT_POSITION] = 900
    follower = Sessions(Hardware(lambda **kwargs: follower_bus))
    leader = Sessions(Hardware(lambda **kwargs: leader_bus))
    try:
        await follower.listen("FAKE",profile(),listen_port=0)
        port=follower.server.sockets[0].getsockname()[1]
        await leader.connect("FAKE",profile(),f"ws://127.0.0.1:{port}",follower.pin)
        await asyncio.sleep(.1)
        assert not leader.enabled and not follower.enabled
        assert not follower_bus.writes
        leader.enable_requested=True
        for _ in range(30):
            if leader.enabled: break
            await asyncio.sleep(.025)
        assert leader.enabled and follower.enabled
        assert follower_bus.values[2][Register.GOAL_POSITION] == 900
        assert all(follower_bus.values[m][Register.GOAL_POSITION] == 2000 for m in (1,3,4,5,6))
        leader_bus.values[1][Register.PRESENT_POSITION]=2100
        await asyncio.sleep(.1)
        target=follower_bus.values[1][Register.GOAL_POSITION]
        assert 2000 < target <= 2100
        await leader.stop()
        await asyncio.sleep(.05)
        assert all(follower_bus.values[m][Register.TORQUE_ENABLE]==0 for m in range(1,7))
    finally:
        await leader.stop()
        await follower.stop()

@pytest.mark.asyncio
async def test_follower_watchdog_and_exclusive_operator():
    import websockets
    from t2_bots.connect.sessions import Sessions,PROTOCOL
    bus=FakeBus(); follower=Sessions(Hardware(lambda **kwargs:bus))
    try:
        await follower.listen("FAKE",profile(),listen_port=0)
        port=follower.server.sockets[0].getsockname()[1]
        url=f"ws://127.0.0.1:{port}"
        async with websockets.connect(url) as first:
            await first.send(json.dumps({"protocol":PROTOCOL,"pin":follower.pin,"role":"leader","calibrated":True}))
            assert json.loads(await first.recv())["status"]=="connected"
            async with websockets.connect(url) as second:
                with pytest.raises(websockets.exceptions.ConnectionClosed): await second.recv()
            for index in range(6):
                await first.send(json.dumps({"op":"enable","raw":{m:2000 for m in range(1,7)}}))
                result = json.loads(await first.recv())
                if index < 5:
                    assert result["enable_pending"] and not result["enabled"]
                    assert not bus.writes
            assert result["enabled"]
            await asyncio.sleep(.7)
            assert not follower.enabled
            assert all(bus.values[m][Register.TORQUE_ENABLE]==0 for m in range(1,7))
    finally:
        await follower.stop()
