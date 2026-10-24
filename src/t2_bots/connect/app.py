"""Loopback-only companion and browser workspace."""
import argparse
import asyncio
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from t2_bots.connect.directory import endpoint_url
from t2_bots.connect.hardware import Hardware, discover
from t2_bots.connect.sessions import Sessions
from t2_bots.connect.storage import LocalStore, digest
from t2_bots.connect.runtime import Runtime, API_VERSION, platform_audit
from t2_bots import __version__

DEPLOYED_WORKSPACES = (
    "https://play.trydexops.com",
    "https://servosocialruss.vercel.app",
)
DIRECTORY_TIMEOUT = 70

ASSETS = Path(__file__).parent / "static"


class Companion:
    def __init__(self, root=None, hardware=None, scanner=discover):
        self.store = LocalStore(root)
        self.hardware = hardware or Hardware()
        self.scanner = scanner
        self.leader_sessions = Sessions(self.hardware)
        self.follower_sessions = Sessions(self.hardware)
        self.lock = asyncio.Lock()
        self.token = secrets.token_urlsafe(32)
        self.last_browser = time.monotonic()
        self.inspection = None
        self.capture_error = ""
        self.directory_error = ""
        self.reservation = None
        self.publishing = False
        self.label = ""
        self.runtime = Runtime()
        self.platform_checks = []

    @property
    def role(self):
        return self.store.data["active_role"]

    @property
    def arm(self):
        return self.store.data["arms"].get(self.role)

    @property
    def sessions(self):
        return self.session_for(self.role)

    def session_for(self, role):
        return self.leader_sessions if role == "leader" else self.follower_sessions

    def current_device(self, role=None):
        arm = self.store.data["arms"].get(role or self.role)
        if arm:
            return next((p for p in self.scanner() if p["identity"] == arm["identity"]), None)
        return None

    def ready(self, role=None):
        return self.calibrated(role)

    def selected(self, role=None):
        device = self.current_device(role)
        if not device:
            self.inspection = None
            raise ValueError("The selected controller is disconnected. Reconnect it or select another arm.")
        return device

    def idle(self, role=None, all_arms=False):
        sessions = (self.leader_sessions, self.follower_sessions) if all_arms else (self.session_for(role or self.role),)
        if any(session.status != "idle" for session in sessions):
            raise ValueError("Stop the current sharing or control session first.")
        if self.hardware.capture:
            raise ValueError("Finish or cancel calibration first.")

    def profile(self, role=None):
        return json.loads(self.store.profile_path(role or self.role).read_text(encoding="utf-8"))

    async def capture_action(self, callback, *args):
        try:
            result = await asyncio.to_thread(callback, *args)
        except Exception as exc:
            self.capture_error = str(exc)
            raise
        self.capture_error = ""
        return result

    def calibrated(self, role=None):
        arm = self.store.data["arms"].get(role or self.role)
        if not arm or not arm.get("calibration_hash"):
            return False
        try:
            return digest(self.profile(role)) == arm["calibration_hash"]
        except (OSError, ValueError):
            return False

    def cloud(self, method, path, payload=None, *, recover_identity=True):
        cfg = self.store.data
        url = cfg.get("directory_url", "")
        if not url:
            raise ValueError("Connect your community directory in station settings first.")
        request = urllib.request.Request(url + path, method=method,
                    data=json.dumps(payload).encode() if payload is not None else None,
                    headers={"Content-Type": "application/json", "X-Device-ID": cfg["device_id"],
                             "Authorization": "Bearer " + cfg["credential"]})
        try:
            # Render's free service can take 50+ seconds to wake. Keep the
            # browser action alive long enough for the first directory call.
            with urllib.request.urlopen(request, timeout=DIRECTORY_TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail", str(exc))
            except Exception:
                detail = str(exc)
            if (recover_identity and exc.code == 403 and detail == "Device credential required."
                    and path != "/v1/identity" and cfg.get("username")):
                self.cloud("POST", "/v1/identity", {
                    "username": cfg["username"], "device_id": cfg["device_id"],
                    "credential": cfg["credential"]}, recover_identity=False)
                return self.cloud(method, path, payload, recover_identity=False)
            raise ValueError(str(detail)) from exc
        except urllib.error.URLError as exc:
            raise ValueError("Cannot reach the directory. Check the server address and connection.") from exc
        except OSError as exc:
            logging.getLogger(__name__).error("Directory connection could not initialise",
                                             exc_info=(type(exc), exc, exc.__traceback__))
            raise ValueError("The companion could not initialise its directory connection. Restart the current companion; if this persists, install the updated package.") from exc

    async def stop(self, role=None):
        if role in (None, "follower"):
            self.publishing = False
            await self.follower_sessions.stop()
        if role in (None, "leader"):
            await self.leader_sessions.stop()
        if self.store.data.get("directory_url") and self.store.data.get("username"):
            try:
                if role in (None, "leader") and self.reservation:
                    await asyncio.to_thread(self.cloud, "DELETE", f"/v1/followers/{self.reservation}/reserve")
                if role in (None, "follower"):
                    await asyncio.to_thread(self.cloud, "DELETE", "/v1/follower")
            except Exception as exc:
                self.directory_error = str(exc)
        if role in (None, "leader"):
            self.reservation = None

    async def sample_calibration(self):
        """Keep measuring local hand movement independently of browser polls."""
        while True:
            await asyncio.sleep(.05)
            if not self.hardware.capture:
                continue
            async with self.lock:
                if not self.hardware.capture:
                    continue
                worker = asyncio.create_task(asyncio.to_thread(self.hardware.sample))
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    # Do not close the serial bus while a read is still running.
                    await asyncio.gather(worker, return_exceptions=True)
                    raise
                except Exception as exc:
                    self.capture_error = str(exc)

    async def watch(self):
        last_heartbeat = 0
        while True:
            await asyncio.sleep(1)
            try:
                if time.monotonic() - self.last_browser > 5:
                    # Passive calibration gets the reference frontend's 20 s
                    # browser grace period; powered sessions still stop at 5 s.
                    if self.hardware.capture and time.monotonic() - self.last_browser > 20:
                        async with self.lock:
                            if self.hardware.capture:
                                self.capture_error = "Calibration stopped because the browser stopped responding. Keep the arm supported and restart calibration."
                                await asyncio.to_thread(self.hardware.cancel)
                    if any(s.status != "idle" for s in (self.leader_sessions, self.follower_sessions)):
                        await self.stop()
                    continue
                if self.arm and not self.current_device():
                    self.inspection = None
                    if self.hardware.capture:
                        async with self.lock:
                            if self.hardware.capture:
                                self.capture_error = "The controller disconnected during calibration. Reconnect it, support the arm and restart calibration."
                                await asyncio.to_thread(self.hardware.cancel)
                for role in ("leader", "follower"):
                    if self.session_for(role).status != "idle" and not self.current_device(role):
                        await self.stop(role)
                if time.monotonic() - last_heartbeat > 7:
                    last_heartbeat = time.monotonic()
                    if self.publishing:
                        if not self.ready("follower") or self.follower_sessions.status not in ("sharing", "connected", "following"):
                            await self.stop("follower")
                        else:
                            await asyncio.to_thread(self.cloud, "PUT", "/v1/follower", {
                                "label": self.label, "endpoint": self.follower_sessions.endpoint,
                                "calibrated": True, "busy": self.follower_sessions.busy})
                    if self.reservation:
                        if self.leader_sessions.status not in ("connected", "following"):
                            await self.stop("leader")
                        else:
                            await asyncio.to_thread(self.cloud, "POST", f"/v1/followers/{self.reservation}/reserve")
                    self.directory_error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.directory_error = str(exc)
                if self.reservation:
                    await self.stop("leader")


def create_app(root=None, hardware=None, scanner=discover, port=4840):
    station = Companion(root, hardware, scanner)

    @asynccontextmanager
    async def lifespan(app):
        tasks = [asyncio.create_task(station.watch()), asyncio.create_task(station.sample_calibration())]
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        station.hardware.cancel()
        await station.stop()

    app = FastAPI(title="Dexops local companion", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.station = station
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DEPLOYED_WORKSPACES),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-T2-Session"],
        allow_private_network=True,
        max_age=600,
    )

    @app.middleware("http")
    async def local_guard(request, call_next):
        host = request.headers.get("host", "")
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = request.headers.get("origin")
        deployed_origin = origin in DEPLOYED_WORKSPACES
        if host not in allowed or (origin and origin != "http://" + host and not deployed_origin):
            return JSONResponse({"detail": "Only this local workspace can access the companion."}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site" and request.url.path.startswith("/api/") and not deployed_origin:
            return JSONResponse({"detail": "Cross-site companion access is blocked."}, status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(request.headers.get("X-T2-Session", ""), station.token):
                return JSONResponse({"detail": "Workspace session expired. Reload this page."}, status_code=403)
            if len(await request.body()) > 16384:
                return JSONResponse({"detail": "Request too large."}, status_code=413)
            if request.url.path not in ("/api/runtime/confirm", "/api/runtime/check", "/api/session/stop"):
                runtime = station.runtime.snapshot(station.store.data.get("runtime_approval"))
                if not runtime["compatible"] or not runtime["acknowledged"]:
                    return JSONResponse({"detail": "Verify and confirm this companion runtime in the installation step first."}, status_code=409)
        response = await call_next(request)
        if deployed_origin and request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(OSError)
    async def hardware_unavailable(request, exc):
        logging.getLogger(__name__).error("Local request failed: %s", request.url.path,
                                         exc_info=(type(exc), exc, exc.__traceback__))
        return JSONResponse({"detail": "The controller or local file is unavailable. Close other serial apps, check USB permissions, and retry. " + str(exc)}, status_code=409)

    @app.get("/api/state")
    async def state():
        station.last_browser = time.monotonic()
        async with station.lock:
            try:
                capture = await asyncio.to_thread(station.hardware.sample) if station.hardware.capture else None
            except Exception as exc:
                capture = None
                station.capture_error = str(exc)
            ports = await asyncio.to_thread(station.scanner)
            device = next((p for p in ports if station.arm and p["identity"] == station.arm["identity"]), None)
            arm = station.arm or {}
            arms = {}
            for role in ("leader", "follower"):
                saved = station.store.data["arms"].get(role, {})
                present = next((p for p in ports if saved and p["identity"] == saved["identity"]), None)
                arms[role] = {"assigned": bool(saved), "name": saved.get("name", "My " + role),
                              "identity": saved.get("identity", ""), "port": present["port"] if present else saved.get("port", ""),
                              "connected": present is not None, "calibrated": station.calibrated(role),
                              "ready": station.ready(role) and present is not None}
            return {"service": "t2-connect", "version": __version__, "api_version": API_VERSION,
                    "runtime": station.runtime.snapshot(station.store.data.get("runtime_approval")),
                    "platform_checks": station.platform_checks, "session_token": station.token,
                    "username": station.store.data["username"], "directory_url": station.store.data["directory_url"],
                    "device_id": station.store.data["device_id"], "role": station.role,
                    "ports": ports, "arm": arm, "connected": device is not None,
                    "roles": list(station.store.data["arms"]), "arms": arms,
                    "inspection": station.inspection if device else None, "capture": capture,
                    "capture_error": station.capture_error,
                    "calibrated": station.calibrated(), "ready": station.ready() and device is not None,
                    "session": station.sessions.snapshot(), "publishing": station.publishing,
                    "leader_session": station.leader_sessions.snapshot(), "follower_session": station.follower_sessions.snapshot(),
                    "directory_error": station.directory_error}

    @app.get("/api/heartbeat")
    def heartbeat():
        station.last_browser = time.monotonic()
        return {"service": "t2-connect"}

    @app.post("/api/runtime/check")
    async def runtime_check():
        station.platform_checks = await asyncio.to_thread(platform_audit)
        return {"runtime": station.runtime.snapshot(station.store.data.get("runtime_approval")),
                "platform_checks": station.platform_checks}

    @app.post("/api/runtime/confirm")
    async def runtime_confirm(payload: dict):
        runtime = station.runtime.snapshot()
        if payload.get("confirmed") is not True or payload.get("build_id") != runtime["build_id"]:
            raise ValueError("Confirm the actual detected companion build before continuing.")
        if not runtime["compatible"]:
            raise ValueError("Install the required companion runtime components first.")
        async with station.lock:
            station.store.data["runtime_approval"] = station.runtime.approval()
            station.store.save()
        return {"confirmed": True}

    @app.post("/api/identity")
    async def identity(payload: dict):
        name = str(payload.get("username", "")).strip().lower()
        url = str(payload.get("directory_url", "")).strip().rstrip("/")
        parts = urlsplit(url)
        if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/") or not (
                parts.scheme == "https" or parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")):
            raise ValueError("Use the directory HTTPS address, or HTTP localhost for development.")
        async with station.lock:
            station.idle(all_arms=True)
            old_url = station.store.data["directory_url"]
            station.store.data["directory_url"] = url
            try:
                result = await asyncio.to_thread(station.cloud, "POST", "/v1/identity", {
                    "username": name, "device_id": station.store.data["device_id"],
                    "credential": station.store.data["credential"]})
            except Exception:
                station.store.data["directory_url"] = old_url
                raise
            station.store.data["username"] = result["username"]
            station.store.save()
        return {"username": result["username"]}

    @app.post("/api/arm")
    async def assign(payload: dict):
        role = payload.get("role")
        if role not in ("leader", "follower"):
            raise ValueError("Choose leader or follower.")
        async with station.lock:
            station.idle(role)
            device = next((d for d in station.scanner() if d["identity"] == payload.get("identity")), None)
            if not device:
                raise ValueError("Select a connected USB controller.")
            other = station.store.data["arms"].get("follower" if role == "leader" else "leader", {})
            if other.get("identity") == device["identity"]:
                raise ValueError("Leader and follower need different USB controllers.")
            existing = station.store.data["arms"].get(role, {})
            if existing.get("identity") != device["identity"]:
                existing = {}
            name = str(payload.get("name", existing.get("name", "My " + role))).strip()
            if not 1 <= len(name) <= 60:
                raise ValueError("Use 1–60 characters for the arm name.")
            station.store.data["arms"][role] = {**existing, **device, "name": name}
            station.store.data["active_role"] = role
            station.store.save()
            station.inspection = None
            station.capture_error = ""
        return {"assigned": True}

    @app.post("/api/arm/select")
    async def select_arm(payload: dict):
        role = payload.get("role")
        async with station.lock:
            if role not in ("leader", "follower") or role not in station.store.data["arms"]:
                raise ValueError("Add this arm before selecting it.")
            if station.hardware.capture:
                raise ValueError("Finish or cancel calibration before switching arms.")
            station.store.data["active_role"] = role
            station.store.save()
            station.inspection = None
            station.capture_error = ""
        return {"selected": role}

    @app.post("/api/inspect")
    async def inspect():
        async with station.lock:
            station.idle()
            station.inspection = None
            report = await asyncio.to_thread(station.hardware.inspect, station.selected()["port"], station.role)
            station.inspection = report
            return report

    @app.post("/api/calibration/{action}")
    async def calibration(action: str, payload: dict):
        async with station.lock:
            if action == "cancel":
                await asyncio.to_thread(station.hardware.cancel)
                station.capture_error = ""
                return {"cancelled": True}
            station.selected()
            if station.sessions.status != "idle":
                raise ValueError("Stop sharing or controlling before calibration.")
            if action == "start":
                if payload.get("supported") is not True:
                    raise ValueError("Support the arm before releasing torque.")
                station.arm.pop("certificate", None)
                station.store.save()
                return await station.capture_action(station.hardware.begin, station.selected()["port"], station.role)
            if action == "reference":
                return await station.capture_action(station.hardware.reference)
            if action == "resume":
                return await station.capture_action(station.hardware.resume)
            if action == "save":
                if not payload.get("reviewed"):
                    raise ValueError("Review the measured ranges before saving.")
                profile = await station.capture_action(station.hardware.finish)
                station.store.save_profile(station.role, profile)
                await asyncio.to_thread(station.hardware.cancel)
                station.arm["calibration_hash"] = digest(profile)
                station.arm.pop("certificate", None)
                station.store.save()
                return {"saved": True}
            raise ValueError("Unknown calibration action.")

    @app.get("/api/followers")
    async def followers():
        if not station.store.data.get("username"):
            return {"followers": [], "configured": False}
        return {**await asyncio.to_thread(station.cloud, "GET", "/v1/followers"), "configured": True}

    @app.post("/api/share")
    async def share(payload: dict):
        async with station.lock:
            station.idle("follower")
            if not station.ready("follower"):
                raise ValueError("Select and calibrate a follower before sharing.")
            if not station.store.data.get("username"):
                raise ValueError("Choose a username and directory first.")
            if not payload.get("confirmed"):
                raise ValueError("The follower owner must approve sharing.")
            follower = station.store.data["arms"]["follower"]
            try:
                await station.follower_sessions.listen(station.selected("follower")["port"], station.profile("follower"),
                                              public=payload.get("relay") is True)
                endpoint = station.follower_sessions.endpoint if payload.get("relay") else endpoint_url(str(payload.get("endpoint", "")))
                station.follower_sessions.endpoint = endpoint
                station.label = str(payload.get("label", "My SO-101"))[:60]
                follower["name"] = station.label
                station.store.save()
                await asyncio.to_thread(station.cloud, "PUT", "/v1/follower", {
                    "label": station.label, "endpoint": endpoint, "calibrated": True, "busy": False})
                station.publishing = True
            except Exception as exc:
                await station.follower_sessions.stop()
                action = "Follower sharing could not complete."
                raise ValueError(action + " " + str(exc)) from exc
        return station.follower_sessions.snapshot()

    @app.post("/api/session/connect")
    async def connect(payload: dict):
        async with station.lock:
            station.idle("leader")
            if not station.ready("leader"):
                raise ValueError("Select and calibrate your leader first.")
            follower = str(payload.get("id", ""))
            if not follower or len(follower) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in follower):
                raise ValueError("Select a follower from the directory.")
            pin = str(payload.get("pin", "")).replace("-", "")
            if len(pin) != 6 or not pin.isascii() or not pin.isdigit():
                raise ValueError("Enter the owner's six-digit PIN.")
            reservation = await asyncio.to_thread(station.cloud, "POST", f"/v1/followers/{follower}/reserve")
            station.reservation = follower
            try:
                await station.leader_sessions.connect(station.selected("leader")["port"], station.profile("leader"), reservation["endpoint"], pin)
            except Exception:
                await station.stop("leader")
                raise
        return station.leader_sessions.snapshot()

    @app.post("/api/session/enable")
    async def enable(payload: dict):
        if not payload.get("confirmed") or station.leader_sessions.status != "connected":
            raise ValueError("Connect and confirm both workspaces are clear before enabling following.")
        station.leader_sessions.enable_requested = True
        return {"status": "enable_requested"}

    @app.post("/api/session/stop")
    async def stop(payload: dict):
        async with station.lock:
            role = payload.get("role")
            if role not in (None, "leader", "follower"):
                raise ValueError("Choose which arm to stop.")
            await station.stop(role)
        return station.sessions.snapshot()

    @app.get("/")
    def home():
        return FileResponse(ASSETS / "index.html")

    app.mount("/", StaticFiles(directory=ASSETS), name="assets")
    return app


def main(default_workspace=""):
    import uvicorn
    parser = argparse.ArgumentParser(description="Open the Dexops guided robot workspace")
    parser.add_argument("--port", type=int, default=4840)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--workspace-url", help="Open an approved hosted Dexops workspace instead of localhost")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}"
    workspace_url = str(args.workspace_url or default_workspace).rstrip("/")
    if workspace_url and workspace_url not in DEPLOYED_WORKSPACES:
        parser.error("The hosted workspace URL is not approved by this companion build.")
    try:
        with urllib.request.urlopen(url + "/api/state", timeout=0.5) as response:
            existing = json.load(response)
            if existing.get("service") == "t2-connect":
                if existing.get("version") != __version__ or existing.get("api_version") != API_VERSION or existing.get("runtime", {}).get("build_id") != Runtime().build:
                    print("An older or different companion is already using " + url)
                    print("Stop following, close the older companion, then reopen this current version. Your station data is preserved.")
                    raise SystemExit(1)
                print("The companion is already running at " + url)
                if workspace_url and not args.no_browser:
                    webbrowser.open(workspace_url + "/")
                    print("Opened the deployed Dexops workspace.")
                else:
                    print("Continue in the workspace tab that is already open.")
                return
    except (OSError, ValueError):
        pass
    if not args.no_browser:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(workspace_url + "/" if workspace_url else url)).start()
    uvicorn.run(create_app(port=args.port), host="127.0.0.1", port=args.port)


def dexops_main():
    """Global end-user command: start locally and open the hosted workspace."""
    main("https://servosocialruss.vercel.app")


if __name__ == "__main__":
    main()
