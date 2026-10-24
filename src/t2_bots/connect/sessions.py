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
from t2_bots.core.certification import verify_certificate
from t2_bots.network.protocol import TeleopPacket
from t2_bots_so101.driver.registers import Register

PROTOCOL = "t2-connect/1"


class Sessions:
    def __init__(self, hardware):
        self.hardware = hardware
        self.server = self.ws = self.bus = self.worker = self.relay = None
        self.profile = self.certificate = None
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

    def snapshot(self):
        return {"status": self.status, "error": self.error, "enabled": self.enabled,
                "busy": self.busy, "endpoint": self.endpoint, "pin": self.pin,
                "telemetry": self.telemetry, "protocol": PROTOCOL}

    async def read(self):
        async with self.io:
            values = await asyncio.to_thread(self.bus.sync_read_positions, list(range(1, 7)))
            if set(values) != set(range(1, 7)):
                raise ValueError("Incomplete encoder readings. Session stopped.")
            for mid, value in values.items():
                required(value, f"motor {mid} encoder")
            return values

    async def release(self):
        if self.bus:
            async with self.io:
                await asyncio.to_thread(self.hardware.torque, self.bus, False)
        self.enabled = False

    def open_bus(self, port):
        self.bus = self.hardware.bus_factory(port=port)
        try:
            self.bus.open()
            report = self.hardware.inspect_bus(self.bus, self.certificate["role"])
            if not report["passed"] or any(m["torque"] for m in report["motors"]):
                raise ValueError("Resolve motor checks and release torque before connecting.")
            for mid, name in self.names():
                motor = report["motors"][mid - 1]
                bounds = self.profile[name]
                if not bounds["range_min"] <= motor["position"] <= bounds["range_max"]:
                    raise ValueError(f"Move {name.replace('_', ' ')} inside its saved calibration range before connecting.")
        except Exception:
            self.bus.close()
            self.bus = None
            raise

    async def listen(self, port, profile, certificate, listen_port=8765, public=False):
        if self.status != "idle":
            raise ValueError("Stop the current session first.")
        self.profile, self.certificate = profile, certificate
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
        if self.busy or len(self.failures) >= 10:
            await ws.close(code=1008, reason="Busy or too many PIN attempts.")
            return
        # Reserve locally before the first await: only one incoming operator.
        self.busy = True
        leader_base = follower_base = last_target = None
        try:
            hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if hello.get("protocol") != PROTOCOL or not secrets.compare_digest(str(hello.get("pin", "")), self.pin):
                self.failures.append(now)
                raise ValueError("Incorrect PIN or incompatible companion version.")
            leader_cert = hello.get("certificate", {})
            if not verify_certificate(leader_cert) or leader_cert.get("role") != "leader" or leader_cert.get("grade") != "A+":
                raise ValueError("The leader needs a current passing certificate.")
            if not verify_certificate(self.certificate):
                raise ValueError("Follower certificate expired.")
            self.ws = ws
            self.error = ""
            self.status = "connected"
            await ws.send(json.dumps({"protocol": PROTOCOL, "status": "connected", "certificate": self.certificate}))
            last_time = time.monotonic()
            last_health = 0
            while True:
                message = json.loads(await asyncio.wait_for(ws.recv(), 0.5))
                op = message.get("op")
                raw = await self.read()
                if op == "enable":
                    leader_base = self.decode_raw(message["raw"])
                    follower_base = raw.copy()
                    last_target = raw.copy()
                    for mid, name in self.names():
                        p = self.profile[name]
                        if not p["range_min"] <= raw[mid] <= p["range_max"]:
                            raise ValueError(f"{name}: current position is outside calibrated limits.")
                    async with self.io:
                        await asyncio.to_thread(self.bus.sync_write_positions, raw)
                        for mid in raw:
                            actual = await asyncio.to_thread(self.bus.read_word, mid, Register.GOAL_POSITION)
                            if actual != raw[mid]:
                                raise ValueError("Initial holding target did not latch.")
                        await asyncio.to_thread(self.hardware.torque, self.bus, True)
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
                        goal = min(p["range_max"], max(p["range_min"], follower_base[mid] + delta))
                        max_step = 30 / (360 / 4096) * dt
                        target[mid] = last_target[mid] + min(max_step, max(-max_step, goal - last_target[mid]))
                    async with self.io:
                        await asyncio.to_thread(self.bus.sync_write_positions, {m: round(v) for m, v in target.items()})
                    last_target = target
                    last_time = time.monotonic()
                elif op != "sample":
                    raise ValueError("Unknown session command.")
                # Read status every exchange; read failures stop instead of passing.
                async with self.io:
                    for mid in raw:
                        err = await asyncio.to_thread(self.bus.read_byte, mid, Register.STATUS_ERROR)
                        if err != 0:
                            raise ValueError(f"Motor {mid} reported a hardware error.")
                    if time.monotonic() - last_health > 1:
                        for mid in raw:
                            voltage = await asyncio.to_thread(self.bus.read_byte, mid, Register.PRESENT_VOLTAGE)
                            temp = await asyncio.to_thread(self.bus.read_byte, mid, Register.PRESENT_TEMPERATURE)
                            if voltage is None or voltage < 115 or temp is None or temp > 60:
                                raise ValueError(f"Motor {mid}: power or temperature outside operating checks.")
                        last_health = time.monotonic()
                self.telemetry = {"raw": raw, "enabled": self.enabled}
                await ws.send(json.dumps(self.telemetry))
        except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError):
            pass
        except Exception as exc:
            self.error = str(exc)
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
            await ws.close()
            self.ws = None
            self.busy = False
            if self.server:
                self.status = "fault" if release_failed else "sharing"

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

    async def connect(self, port, profile, certificate, endpoint, pin):
        if self.status != "idle":
            raise ValueError("Stop the current session first.")
        self.profile, self.certificate = profile, certificate
        self.error = ""
        try:
            await asyncio.to_thread(self.open_bus, port)
            self.ws = await websockets.connect(endpoint_url(endpoint), open_timeout=8,
                                                max_size=32768, max_queue=2)
            await self.ws.send(json.dumps({"protocol": PROTOCOL, "pin": pin, "certificate": certificate}))
            response = json.loads(await asyncio.wait_for(self.ws.recv(), 8))
            remote_cert = response.get("certificate", {})
            if response.get("protocol") != PROTOCOL or response.get("status") != "connected" or not verify_certificate(remote_cert) or remote_cert.get("role") != "follower" or remote_cert.get("grade") != "A+":
                raise ValueError(response.get("error", "Follower handshake or certificate failed."))
            self.endpoint, self.status = endpoint, "connected"
            self.worker = asyncio.create_task(self.leader_loop())
        except Exception:
            await self.stop()
            raise

    async def leader_loop(self):
        seq = 0
        previous = None
        try:
            while True:
                start = time.monotonic()
                raw = await self.read()
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
                await self.ws.send(json.dumps(message))
                result = json.loads(await asyncio.wait_for(self.ws.recv(), 0.5))
                if result.get("error"):
                    raise ValueError(result["error"])
                self.enabled = result.get("enabled") is True
                self.status = "following" if self.enabled else "connected"
                self.telemetry = {"leader": raw, "follower": result.get("raw"),
                                  "loop_ms": round((time.monotonic() - start) * 1000, 1)}
                await asyncio.sleep(max(0, 1 / 60 - (time.monotonic() - start)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)
            self.enabled = False
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
        self.status = "idle"
        self.pin = self.endpoint = ""
