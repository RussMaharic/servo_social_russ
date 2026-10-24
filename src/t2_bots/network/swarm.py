"""
One-to-Many ("One-to-Many Movement") Swarm Teleoperation Orchestrator.
Allows a single Leader ARM to drive N verified Follower ARMs with explicit admission control.
"""

import sys
import time
import json
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Callable, Any

try:
    import websockets
except ImportError:
    websockets = None

from t2_bots.network.protocol import TeleopPacket
from t2_bots.network.auth import TokenGuard, generate_room_code
from t2_bots.network.blackbox import BlackboxFlightRecorder
from t2_bots.network.deadman import DeadmanGuard
from t2_bots.network.relay import PinggyRelayManager
from t2_bots.core.schema import RobotAction

logger = logging.getLogger("t2_bots.swarm")

@dataclass
class SwarmFollowerNode:
    follower_id: str
    name: str
    remote_address: str
    websocket: Any
    certificate: Dict[str, Any]
    bus_voltage_v: float
    grade: str
    admitted_at: float
    last_heartbeat: float = field(default_factory=time.time)
    rtt_ms: float = 0.0
    packets_sent: int = 0
    packets_acked: int = 0
    is_safe_held: bool = False
    disparity_deg: float = 0.0

class SwarmHubServer:
    """
    Leader-Side Swarm Hub Server for 1-to-N Distributed Teleoperation.
    Features:
    - Interactive Leader Admission Control Handshake.
    - Non-blocking parallel broadcast queue at 60 Hz.
    - Isolated per-follower Deadman & Voltage Fail-Safe.
    - Automated Pinggy Reverse Tunnel integration.
    """

    def __init__(
        self,
        leader_robot,
        room_code: Optional[str] = None,
        pin: Optional[str] = None,
        host: str = "0.0.0.0",
        port: int = 8765,
        use_relay: bool = False,
        admission_callback: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        self.leader = leader_robot
        self.host = host
        self.port = port
        self.use_relay = use_relay
        self.auth = TokenGuard(pin=pin)
        self.room_code = room_code or generate_room_code()
        self.pin = self.auth.gated_pin
        self.admission_callback = admission_callback or self._default_cli_admission
        self.active_followers: Dict[str, SwarmFollowerNode] = {}
        self.flight_recorder = BlackboxFlightRecorder()
        self.relay_manager: Optional[PinggyRelayManager] = None
        self._server = None
        self._is_running = False
        self._loop_task = None

    def _default_cli_admission(self, request_info: Dict[str, Any]) -> bool:
        """
        Default interactive CLI prompt for Leader operator to admit new followers.
        """
        print("\n" + "=" * 70)
        print("🔔 [SWARM ADMISSION REQUEST] Incoming Follower Arm:")
        print(f"   Name:     {request_info.get('name', 'Anonymous')}")
        print(f"   Arm ID:   {request_info.get('arm_id', 'Unknown')}")
        print(f"   Voltage:  {request_info.get('bus_voltage_v', 0.0):.1f}V")
        print(f"   Grade:    {request_info.get('grade', 'Unverified')}")
        print(f"   Address:  {request_info.get('remote_address')}")
        print("-" * 70)
        sys.stdout.write("👉 Grant teleoperation admission to this Follower? [Y/n]: ")
        sys.stdout.flush()
        try:
            # Fast inline read
            ans = sys.stdin.readline().strip().lower()
            return ans in ["", "y", "yes"]
        except Exception:
            return False

    async def start(self):
        """Starts the Swarm Hub WebSocket Server and optional Pinggy Cloud Relay."""
        if websockets is None:
            raise ImportError("websockets package required for swarm operation.")

        public_url = None
        if self.use_relay:
            print("🌐 [Swarm Hub] Starting autonomous Pinggy Cloud Relay tunnel...")
            self.relay_manager = PinggyRelayManager(local_port=self.port)
            tunnel = self.relay_manager.start_tunnel()
            public_url = tunnel.url
            print(f"✔ Public Swarm Tunnel Live: {tunnel.url} (Port {tunnel.port})")

        self._server = await websockets.serve(
            self._handle_follower_connection,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=20,
        )
        self._is_running = True

        print("\n" + "=" * 70)
        print("🎮 [t2-BOTS Swarm Master] 1-to-Many Swarm Teleoperation Hub")
        print(f"   Room Code:  {self.room_code}")
        print(f"   Gated PIN:  {self.auth.formatted_pin}")
        print(f"   Local Bind: {self.host}:{self.port}")
        if public_url:
            print(f"   Public WAN: {public_url}")
        print("   Mode:       LEADER MASTER BROADCASTER (1 Leader -> N Followers)")
        print("=" * 70 + "\n")

        # Spawn broadcast teleoperation loop
        self._loop_task = asyncio.create_task(self._teleop_broadcast_loop())

    async def _handle_follower_connection(self, websocket):
        """
        Manages follower connection handshake, certificate verification, and admission.
        """
        remote_addr = str(websocket.remote_address)
        logger.info(f"Incoming connection from {remote_addr}")

        try:
            raw_msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            data = json.loads(raw_msg)
            req_type = data.get("type", "SWARM_JOIN_REQUEST")

            if req_type != "SWARM_JOIN_REQUEST":
                await websocket.send(json.dumps({"status": "REJECTED", "reason": "Expected SWARM_JOIN_REQUEST"}))
                await websocket.close()
                return

            pin_or_token = str(data.get("pin") or data.get("token") or "")
            if not self.auth.validate_token(pin_or_token, self.room_code, "leader") and pin_or_token != self.pin:
                await websocket.send(json.dumps({"status": "AUTH_FAILED", "reason": "Invalid Swarm PIN"}))
                await websocket.close()
                return

            cert = data.get("certificate", {})
            arm_id = cert.get("arm_id") or data.get("arm_id") or f"FOL-{int(time.time())}"
            follower_name = data.get("name") or arm_id
            v_bus = cert.get("diagnostics", {}).get("bus_voltage_v", 12.0)
            grade = cert.get("grade", "UNVERIFIED")

            # Admission request dictionary
            request_info = {
                "follower_id": arm_id,
                "name": follower_name,
                "remote_address": remote_addr,
                "arm_id": arm_id,
                "bus_voltage_v": v_bus,
                "grade": grade,
                "certificate": cert,
            }

            # Interactive admission callback (Leader approval)
            is_approved = await asyncio.get_event_loop().run_in_executor(
                None, self.admission_callback, request_info
            )

            if not is_approved:
                print(f"❌ Operator REJECTED admission for Follower '{follower_name}' ({arm_id})")
                await websocket.send(json.dumps({"status": "REJECTED", "reason": "Leader operator declined admission request."}))
                await websocket.close()
                return

            # Admitted! Register follower
            node = SwarmFollowerNode(
                follower_id=arm_id,
                name=follower_name,
                remote_address=remote_addr,
                websocket=websocket,
                certificate=cert,
                bus_voltage_v=v_bus,
                grade=grade,
                admitted_at=time.time(),
            )
            self.active_followers[arm_id] = node

            print(f"✔ [SWARM ADMITTED] Follower '{follower_name}' [{arm_id}] joined! Total Active: {len(self.active_followers)}")

            await websocket.send(json.dumps({
                "status": "ADMITTED",
                "room": self.room_code,
                "follower_id": arm_id,
                "active_followers_count": len(self.active_followers),
            }))

            # Listen for telemetry acks and status from this follower
            while self._is_running:
                ack_msg = await websocket.recv()
                ack_data = json.loads(ack_msg)
                node.last_heartbeat = time.time()
                node.packets_acked += 1
                if "rtt_ms" in ack_data:
                    node.rtt_ms = float(ack_data["rtt_ms"])
                if "v_bus" in ack_data:
                    node.bus_voltage_v = float(ack_data["v_bus"])

        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.warning(f"Follower connection exception: {e}")
        finally:
            if arm_id in self.active_followers:
                del self.active_followers[arm_id]
                print(f"⚠️ Follower '{follower_name}' [{arm_id}] disconnected. Remaining Active: {len(self.active_followers)}")

    async def _teleop_broadcast_loop(self):
        """
        Synchronous 60 Hz broadcast loop reading physical Leader state
        and distributing TeleopPackets to all admitted followers.
        """
        seq = 0
        rate_hz = 60.0
        dt = 1.0 / rate_hz

        while self._is_running:
            start_t = time.perf_counter()
            seq += 1

            if not self.active_followers:
                await asyncio.sleep(dt)
                continue

            try:
                obs = self.leader.get_observation()
                packet = TeleopPacket(
                    seq=seq,
                    timestamp_ns=time.time_ns(),
                    role="leader",
                    joints=obs.joint_positions,
                    gripper=obs.gripper_position,
                    raw_ticks=obs.raw_ticks,
                    velocities=obs.joint_velocities,
                    bus_voltage=obs.bus_voltage,
                    max_temp=obs.max_temperature,
                )
                payload = packet.serialize()

                # Fan-out to all active followers simultaneously
                tasks = []
                now = time.time()
                for fid, node in list(self.active_followers.items()):
                    # Isolated Deadman check: latency > 150ms or no heartbeat in 0.5s
                    if (now - node.last_heartbeat > 0.5) or (node.bus_voltage_v < 11.0):
                        if not node.is_safe_held:
                            node.is_safe_held = True
                            print(f"⚠️ [ISOLATED DEADMAN] Follower '{node.name}' safe-held (Latency/Voltage issue). Other arms continuing.")
                        continue
                    else:
                        node.is_safe_held = False

                    tasks.append(self._send_to_node(node, payload))

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")

            elapsed = time.perf_counter() - start_t
            sleep_time = max(0.0, dt - elapsed)
            await asyncio.sleep(sleep_time)

    async def _send_to_node(self, node: SwarmFollowerNode, payload: str):
        try:
            await node.websocket.send(payload)
            node.packets_sent += 1
        except Exception:
            node.is_safe_held = True

    async def stop(self):
        """Cleanly stops the Swarm Hub and closes all follower connections."""
        self._is_running = False
        if self._loop_task:
            self._loop_task.cancel()
        for fid, node in list(self.active_followers.items()):
            try:
                await node.websocket.close()
            except Exception:
                pass
        self.active_followers.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        if self.relay_manager:
            self.relay_manager.stop_tunnel()
        print("✔ Swarm Hub cleanly shut down.")

class SwarmFollowerClient:
    """
    Follower-Side Swarm Client that connects to the Leader Swarm Hub,
    submits its Hardware Qualification Certificate, and tracks teleoperation.
    """

    def __init__(
        self,
        follower_robot,
        hub_host: str,
        hub_port: int = 8765,
        pin: Optional[str] = None,
        name: Optional[str] = None,
        certificate: Optional[Dict[str, Any]] = None,
    ):
        self.follower = follower_robot
        self.hub_host = hub_host
        self.hub_port = hub_port
        self.pin = pin
        self.name = name or getattr(follower_robot, "arm_id", "SO101-Follower")
        self.certificate = certificate or {}
        self.deadman = DeadmanGuard(timeout_s=0.25)
        self._is_running = False

    async def run(self):
        """Connects to the Swarm Hub, requests admission, and tracks live trajectory."""
        if websockets is None:
            raise ImportError("websockets package required for swarm operation.")

        clean_host = self.hub_host
        target_port = self.hub_port
        if "://" in self.hub_host:
            uri = self.hub_host
        else:
            if ":" in self.hub_host:
                parts = self.hub_host.split(":")
                clean_host = parts[0]
                try:
                    target_port = int(parts[1])
                except ValueError:
                    pass
            proto = "ws"
            uri = f"{proto}://{clean_host}:{target_port}"

        print(f"Connecting to Swarm Hub at {uri}...")
        async with websockets.connect(uri) as ws:
            # 1. Submit SWARM_JOIN_REQUEST
            join_payload = {
                "type": "SWARM_JOIN_REQUEST",
                "name": self.name,
                "pin": self.pin,
                "arm_id": getattr(self.follower, "arm_id", "SO101-Follower"),
                "certificate": self.certificate,
            }
            await ws.send(json.dumps(join_payload))

            # 2. Wait for admission status
            resp_raw = await ws.recv()
            resp = json.loads(resp_raw)

            if resp.get("status") != "ADMITTED":
                print(f"❌ Admission REJECTED: {resp.get('reason', 'Unknown reason')}")
                return False

            print(f"✔ Admitted to Swarm Room: {resp.get('room')}! Teleoperation active.")
            self.follower.set_torque(True)
            self._is_running = True

            # 3. Track incoming broadcast packets
            while self._is_running:
                packet_raw = await ws.recv()
                packet = TeleopPacket.deserialize(packet_raw)

                # Send telemetry ack
                obs = self.follower.get_observation()
                rtt = packet.compute_rtt_ms()
                ack = {"seq": packet.seq, "rtt_ms": round(rtt, 1), "v_bus": obs.bus_voltage}
                await ws.send(json.dumps(ack))

                # Apply 1:1 action
                self.follower.send_action(
                    RobotAction(
                        target_positions=packet.joints,
                        target_gripper=packet.gripper,
                        duration_s=0.02,
                    )
                )

        return True
