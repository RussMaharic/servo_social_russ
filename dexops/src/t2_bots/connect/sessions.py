"""Two-stage browser sessions using SDK packets, servo transport and Pinggy.

This explicit-enable protocol is intentionally distinct from the legacy peer CLI,
whose first trajectory packet immediately enables follower torque.
"""
import asyncio
import json
import math
import secrets
import time

import websockets

from t2_bots.connect.directory import endpoint_url
from t2_bots.connect.hardware import required
from t2_bots.network.protocol import TeleopPacket
from t2_bots_so101.driver.registers import Register

PROTOCOL = "t2-connect/2"
FRAME_TIMEOUT = 0.5
RECONNECT_DELAYS = (1, 2, 4)
HEALTH_MAX_AGE = 1.5


class PeerTimeout(ConnectionError):
    """A network receive deadline, distinct from a USB serial TimeoutError."""


async def receive(ws, timeout, description):
    try:
        return await asyncio.wait_for(ws.recv(), timeout)
    except asyncio.TimeoutError as exc:
        raise PeerTimeout(description) from exc


class Sessions:
    def __init__(self, hardware):
        self.hardware = hardware
        self.server = self.ws = self.bus = self.worker = self.relay = None
        self.profile = None
        self.role = None
        self.status = "idle"
        self.error = ""
        self.pin = ""
        self.endpoint = ""
        self.enabled = False
        self.enable_requested = False
        self.busy = False
        self.telemetry = None
        self.io = asyncio.Lock()
        self.failures = []
        self.reconnect_attempt = 0
        self.notice = ""
        self._reconnect_pin = ""

    def snapshot(self):
        return {"status": self.status, "error": self.error, "enabled": self.enabled,
                "busy": self.busy, "endpoint": self.endpoint, "pin": self.pin,
                "telemetry": self.telemetry, "protocol": PROTOCOL,
                "reconnect_attempt": self.reconnect_attempt, "notice": self.notice}

    async def motor_call(self, callback, *args):
        # Cancellation must finish the outstanding serial transaction before
        # stop() can acquire io and close/release the bus.
        task = asyncio.create_task(asyncio.to_thread(callback, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        except OSError as exc:
            raise ValueError(f"{(self.role or 'Arm').capitalize()} USB/serial error: {exc}") from exc

    async def read(self):
        async with self.io:
            values = await self.motor_call(self.bus.sync_read_positions, list(range(1, 7)))
            if set(values) != set(range(1, 7)):
                raise ValueError("Incomplete encoder readings. Session stopped.")
            for mid, value in values.items():
                required(value, f"motor {mid} encoder")
            return values

    async def release(self):
        if self.bus:
            async with self.io:
                await self.motor_call(self.hardware.torque, self.bus, False)
        self.enabled = False

    def open_bus(self, port):
        self.bus = self.hardware.bus_factory(port=port)
        try:
            self.bus.open()
            report = self.hardware.inspect_bus(self.bus, self.role)
            if not report["passed"] or any(m["torque"] for m in report["motors"]):
                raise ValueError("Resolve motor checks and release torque before connecting.")
        except Exception:
            self.bus.close()
            self.bus = None
            raise

    async def listen(self, port, profile, listen_port=8765, public=False):
        if self.status != "idle":
            raise ValueError("Stop the current session first.")
        self.profile, self.role = profile, "follower"
        await asyncio.to_thread(self.open_bus, port)
        self.pin = f"{secrets.randbelow(900000) + 100000}"
        self.error = ""
        try:
            self.server = await websockets.serve(self.handle, "0.0.0.0", listen_port,
                                                 max_size=32768, max_queue=2)
            self.status = "sharing"
            self.endpoint = f"ws://127.0.0.1:{listen_port}"
            if public:
                from t2_bots.network.relay import PinggyRelayManager
                self.relay = PinggyRelayManager(local_port=listen_port)
                tunnel = await asyncio.to_thread(self.relay.start_tunnel)
                self.endpoint = f"ws://{tunnel.host}:{tunnel.port}"
        except Exception:
            await self.stop()
            raise

    async def handle(self, ws):
        now = time.monotonic()
        self.failures = [t for t in self.failures if now - t < 60]
        if self.status == "fault" or len(self.failures) >= 10:
            await ws.close(code=1008, reason="Resolve follower fault or too many PIN attempts before connecting.")
            return
        if self.busy:
            await ws.close(code=1013, reason="Follower is finishing the previous connection.")
            return
        # Reserve locally before the first await: only one incoming operator.
        self.busy = True
        leader_base = follower_base = last_target = None
        fault = False
        transport_timeout = False
        try:
            hello = json.loads(await receive(ws, 10, "Leader handshake timed out."))
            if hello.get("protocol") != PROTOCOL or not secrets.compare_digest(str(hello.get("pin", "")), self.pin):
                self.failures.append(now)
                raise ValueError("Incorrect PIN or incompatible companion version.")
            if hello.get("role") != "leader" or hello.get("calibrated") is not True:
                raise ValueError("Calibrate the leader before connecting.")
            self.ws = ws
            self.error = ""
            self.status = "connected"
            await ws.send(json.dumps({"protocol": PROTOCOL, "status": "connected", "role": "follower", "calibrated": True}))
            last_time = time.monotonic()
            health_seen = {}
            health_motor = 1
            while True:
                message = json.loads(await receive(ws, FRAME_TIMEOUT,
                    "Follower disconnected: no leader message arrived within 0.5 seconds."))
                op = message.get("op")
                raw = await self.read()
                # Keep error checks on every exchange, but distribute the twelve
                # voltage/temperature reads over six exchanges instead of a burst.
                async with self.io:
                    for mid in raw:
                        err = await self.motor_call(self.bus.read_byte, mid, Register.STATUS_ERROR)
                        if err != 0:
                            raise ValueError(f"Motor {mid} reported a hardware error.")
                    voltage = await self.motor_call(self.bus.read_byte, health_motor, Register.PRESENT_VOLTAGE)
                    temp = await self.motor_call(self.bus.read_byte, health_motor, Register.PRESENT_TEMPERATURE)
                    if voltage is None or voltage < 115 or temp is None or temp > 60:
                        raise ValueError(f"Motor {health_motor}: power or temperature outside operating checks.")
                    health_seen[health_motor] = time.monotonic()
                    health_motor = health_motor % 6 + 1
                health_ready = len(health_seen) == 6 and time.monotonic() - min(health_seen.values()) <= HEALTH_MAX_AGE
                if self.enabled and not health_ready:
                    raise ValueError("Motor health readings became stale. Following stopped.")
                enable_pending = op == "enable" and not health_ready
                if enable_pending:
                    op = "sample"  # Finish checks before any torque is enabled.
                if op == "enable":
                    leader_base = self.decode_raw(message["raw"])
                    follower_base = raw.copy()
                    last_target = raw.copy()
                    async with self.io:
                        await self.motor_call(self.bus.sync_write_positions, raw)
                        for mid in raw:
                            actual = await self.motor_call(self.bus.read_word, mid, Register.GOAL_POSITION)
                            if actual != raw[mid]:
                                raise ValueError("Initial holding target did not latch.")
                        await self.motor_call(self.hardware.torque, self.bus, True)
                    self.enabled = True
                    self.status = "following"
                    last_time = time.monotonic()
                elif op == "frame":
                    if not self.enabled:
                        raise ValueError("Following has not been enabled.")
                    packet = TeleopPacket.deserialize(message["packet"])
                    leader = self.decode_raw(packet.raw_ticks)
                    dt = min(time.monotonic() - last_time, 0.05)
                    target = {}
                    for mid, name in self.names():
                        p = self.profile[name]
                        delta = leader[mid] - leader_base[mid]
                        if abs(delta) > 2048:
                            raise ValueError("Leader encoder crossed its range. Stop and reposition.")
                        if mid == 6:
                            span = message.get("gripper_span")
                            if not isinstance(span, (int, float)) or not 60 <= span <= 4095:
                                raise ValueError("Invalid leader gripper calibration.")
                            delta *= (p["range_max"] - p["range_min"]) / span
                        # Starting just outside a saved range is allowed without
                        # commanding a jump. The starting pose becomes a temporary
                        # boundary, so subsequent movement can only return inward.
                        low = min(p["range_min"], follower_base[mid])
                        high = max(p["range_max"], follower_base[mid])
                        goal = min(high, max(low, follower_base[mid] + delta))
                        max_step = 30 / (360 / 4096) * dt
                        target[mid] = last_target[mid] + min(max_step, max(-max_step, goal - last_target[mid]))
                    async with self.io:
                        await self.motor_call(self.bus.sync_write_positions, {m: round(v) for m, v in target.items()})
                    last_target = target
                    last_time = time.monotonic()
                elif op != "sample":
                    raise ValueError("Unknown session command.")
                self.telemetry = {"raw": raw, "enabled": self.enabled,
                                  "health_ready": health_ready, "enable_pending": enable_pending}
                await ws.send(json.dumps(self.telemetry))
        except PeerTimeout as exc:
            self.error = str(exc)
            transport_timeout = True
        except websockets.exceptions.ConnectionClosed as exc:
            self.error = "Leader connection closed: " + (str(exc).strip() or "remote connection ended")
        except Exception as exc:
            fault = self.ws is ws
            self.error = str(exc).strip() or type(exc).__name__
            try:
                await ws.send(json.dumps({"error": str(exc)}))
            except Exception:
                pass
        finally:
            release_failed = False
            try:
                await self.release()
            except Exception as exc:
                self.error = "Torque release unverified: " + str(exc)
                release_failed = True
            await ws.close(code=1012 if transport_timeout else 1000)
            self.ws = None
            self.busy = False
            if self.server:
                self.status = "fault" if release_failed or fault else "sharing"

    @staticmethod
    def names():
        from t2_bots.core.calibration import JOINT_ID_MAP
        return JOINT_ID_MAP.items()

    @staticmethod
    def decode_raw(raw):
        if not isinstance(raw, dict):
            raise ValueError("Missing encoder data.")
        values = {int(k): v for k, v in raw.items()}
        if set(values) != set(range(1, 7)):
            raise ValueError("All six encoders are required.")
        for mid, value in values.items():
            required(value, f"motor {mid} encoder")
        return values

    async def connect(self, port, profile, endpoint, pin):
        if self.status != "idle":
            raise ValueError("Stop the current session first.")
        self.profile, self.role = profile, "leader"
        self.error = ""
        self.notice = ""
        self.reconnect_attempt = 0
        self._reconnect_pin = pin
        self.endpoint = endpoint_url(endpoint)
        self.status = "connecting"
        try:
            await asyncio.to_thread(self.open_bus, port)
            await self.open_peer()
            self.worker = asyncio.create_task(self.leader_loop())
        except Exception:
            await self.stop()
            raise

    async def open_peer(self):
        self.ws = await websockets.connect(self.endpoint, open_timeout=8,
                                            max_size=32768, max_queue=2, close_timeout=1)
        await self.ws.send(json.dumps({"protocol": PROTOCOL, "pin": self._reconnect_pin,
                                      "role": "leader", "calibrated": True}))
        response = json.loads(await receive(self.ws, 8, "Follower handshake timed out."))
        if response.get("protocol") != PROTOCOL or response.get("status") != "connected" or response.get("role") != "follower" or response.get("calibrated") is not True:
            raise ValueError(response.get("error", "Follower handshake failed."))
        self.enabled = self.enable_requested = False
        self.status = "connected"

    @staticmethod
    def retryable(exc):
        if isinstance(exc, websockets.exceptions.ConnectionClosed):
            # Owner stop, rejection, or normal close must never be undone.
            code = exc.rcvd.code if exc.rcvd else None
            return code not in (1000, 1001, 1008)
        return isinstance(exc, (PeerTimeout, OSError))

    async def reconnect(self, cause):
        self.enabled = self.enable_requested = False
        self.telemetry = None
        self.status = "reconnecting"
        self.notice = "Link interrupted. Reconnecting with movement paused."
        while self.reconnect_attempt < len(RECONNECT_DELAYS):
            if self.ws:
                await self.ws.close()
                self.ws = None
            delay = RECONNECT_DELAYS[self.reconnect_attempt]
            self.reconnect_attempt += 1
            self.error = f"{cause} Reconnect attempt {self.reconnect_attempt}/{len(RECONNECT_DELAYS)}."
            await asyncio.sleep(delay)
            try:
                # Same endpoint and private PIN, no automatic serial reopening
                # and no automatic enable. A new connection starts at rest.
                await self.open_peer()
                self.error = ""
                self.notice = "Connection restored. Check both arms, then enable following to resume."
                return
            except Exception as exc:
                if not self.retryable(exc):
                    raise
                cause = str(exc).strip() or type(exc).__name__
        raise ValueError("Automatic reconnection failed after three attempts. " + str(cause))

    async def leader_loop(self):
        seq = 0
        previous = None
        stable_since = time.monotonic()
        try:
            while True:
                start = time.monotonic()
                try:
                    raw = await self.read()
                except OSError as exc:
                    raise ValueError(f"Leader USB/serial error: {exc}") from exc
                if previous and any(abs(raw[m] - previous[m]) > 1500 for m in raw):
                    raise ValueError("Leader encoder jump detected.")
                previous = raw
                if self.enable_requested:
                    message = {"op": "enable", "raw": raw}
                    self.enable_requested = False
                elif self.enabled:
                    seq += 1
                    pkt = TeleopPacket(seq, time.time_ns(), "leader", {}, 0.0, raw_ticks=raw)
                    p = self.profile["gripper"]
                    message = {"op": "frame", "packet": pkt.serialize(),
                               "gripper_span": p["range_max"] - p["range_min"]}
                else:
                    message = {"op": "sample"}
                try:
                    await self.ws.send(json.dumps(message))
                    result = json.loads(await receive(self.ws, FRAME_TIMEOUT,
                        "Leader disconnected: the follower did not respond within 0.5 seconds."))
                except Exception as exc:
                    if not self._reconnect_pin or not self.retryable(exc):
                        raise
                    await self.reconnect(str(exc).strip() or type(exc).__name__)
                    previous = None
                    stable_since = time.monotonic()
                    continue
                if result.get("error"):
                    raise ValueError(result["error"])
                self.enabled = result.get("enabled") is True
                if result.get("enable_pending") is True:
                    self.enable_requested = True
                    self.notice = "Checking all six motors before enabling following."
                if self.enabled:
                    self.notice = ""
                self.status = "following" if self.enabled else "connected"
                self.telemetry = {"leader": raw, "follower": result.get("raw"),
                                  "loop_ms": round((time.monotonic() - start) * 1000, 1)}
                if time.monotonic() - stable_since >= 10:
                    self.reconnect_attempt = 0
                await asyncio.sleep(max(0, 1 / 60 - (time.monotonic() - start)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc).strip() or type(exc).__name__
            self.enabled = self.enable_requested = False
            self.notice = ""
            self.status = "fault"
            if self.ws:
                await self.ws.close()

    async def stop(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        if self.ws:
            await self.ws.close()
            self.ws = None
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        if self.bus:
            try:
                await self.release()
            except Exception as exc:
                self.error = "Torque release unverified: " + str(exc)
            finally:
                self.bus.close()
                self.bus = None
        if self.relay:
            await asyncio.to_thread(self.relay.stop_tunnel)
            self.relay = None
        self.enabled = self.busy = self.enable_requested = False
        self._reconnect_pin = ""
        self.reconnect_attempt = 0
        self.notice = ""
        self.status = "idle"
        self.pin = self.endpoint = ""
