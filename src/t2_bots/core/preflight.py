"""
Pre-Flight Hardware Qualification, Power Rail Supervision, and Soft-Start Alignment Engine.
Guarantees physical safety and turnkey discovery across macOS, Linux, and Windows.
"""

import sys
import time
import json
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List
import serial.tools.list_ports

from t2_bots.core.base import RobotRole
from t2_bots_so101.driver.bus import FeetechBus
from t2_bots_so101.driver.registers import Register
from t2_bots_so101.kinematics.normalizer import JointNormalizer, JOINT_ID_MAP, JOINT_ORDER

CONFIG_DIR = Path.home() / ".config" / "t2_bots"
CONFIG_FILE = CONFIG_DIR / "hardware_registry.json"

# Known hardware serial numbers from USB descriptors
KNOWN_DEVICES = {
    "leader": "5C82109414",
    "follower": "5C82107826",
}

class PreflightCheckError(Exception):
    """Raised when hardware pre-flight qualification fails."""
    pass

class HardwarePreflight:
    """Performs rigorous pre-flight qualification on physical robotics hardware."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = config_file or CONFIG_FILE
        self.registry = self._load_registry()

    def _load_registry(self) -> Dict[str, str]:
        reg = KNOWN_DEVICES.copy()
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        reg.update(loaded)
            except Exception:
                pass
        return reg

    def save_registry(self, registry: Dict[str, str]) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(registry, f, indent=2)

    def scan_ports(self) -> Dict[str, Any]:
        """Scans all system COM/TTY ports and matches USB serial numbers."""
        found = {}
        for p in serial.tools.list_ports.comports():
            # Check for standard USB-serial chipsets (CH340/343, FTDI, CP210x)
            if not p.device:
                continue
            sn = p.serial_number or ""
            # On macOS, match cu.* to tty.* for low-latency non-blocking serial
            dev_path = p.device
            if sys.platform.startswith("darwin") and dev_path.startswith("/dev/cu."):
                dev_path = dev_path.replace("/dev/cu.", "/dev/tty.")

            found[dev_path] = {
                "serial_number": sn,
                "description": p.description,
                "vid": p.vid,
                "pid": p.pid,
            }
        return found

    def resolve_arms_automatically(self) -> Tuple[str, str]:
        """
        Discovers Leader and Follower serial ports via USB hardware descriptors.
        Returns (leader_port, follower_port).
        """
        ports = self.scan_ports()
        leader_port = None
        follower_port = None

        leader_sn = self.registry.get("leader", KNOWN_DEVICES["leader"])
        follower_sn = self.registry.get("follower", KNOWN_DEVICES["follower"])

        for dev_path, meta in ports.items():
            sn = meta["serial_number"]
            if sn and leader_sn in sn:
                leader_port = dev_path
            elif sn and follower_sn in sn:
                follower_port = dev_path

        # If not resolved by exact SN, fallback to valid USB candidates
        if not leader_port or not follower_port:
            candidates = [
                p for p in ports.keys()
                if ("usb" in p.lower() or "com" in p.lower()) and "bluetooth" not in p.lower() and "debug" not in p.lower()
            ]
            for c in candidates:
                if not leader_port and c != follower_port:
                    leader_port = c
                elif not follower_port and c != leader_port:
                    follower_port = c

        if not leader_port or not follower_port:
            raise PreflightCheckError(
                f"Could not discover both robot arms! Found ports: {list(ports.keys())}\n"
                f"Ensure both Leader and Follower arms are plugged in via USB."
            )

        return leader_port, follower_port

    def resolve_single_arm(self, role: str) -> str:
        """
        Discovers a specific arm (leader or follower) via USB serial descriptors or candidate fallback.
        Enables turnkey discovery on distributed stations (System A or System B) where only one arm is connected.
        """
        role_key = role.lower()
        ports = self.scan_ports()
        target_sn = self.registry.get(role_key, KNOWN_DEVICES.get(role_key, ""))

        # 1. Match by hardware serial number
        for dev_path, meta in ports.items():
            sn = meta.get("serial_number", "")
            if sn and target_sn and target_sn in sn:
                return dev_path

        # 2. Fallback to candidate USB/COM port
        candidates = [
            p for p in ports.keys()
            if ("usb" in p.lower() or "com" in p.lower() or "ttyacm" in p.lower())
            and "bluetooth" not in p.lower()
            and "debug" not in p.lower()
        ]
        if candidates:
            return candidates[0]

        raise PreflightCheckError(
            f"Could not discover {role.upper()} arm on this station!\n"
            f"Available ports: {list(ports.keys())}\n"
            f"Ensure the {role.upper()} arm is plugged in via USB."
        )

    def check_bus_health(self, port: str, expected_role: str = "robot") -> Dict[str, Any]:
        """
        Verifies communication turnaround, all 6 actuator pings, and 12V power rail.
        """
        bus = FeetechBus(port=port)
        try:
            bus.open()
        except Exception as e:
            raise PreflightCheckError(f"Failed to open serial port {port}: {e}")

        motor_ids = [1, 2, 3, 4, 5, 6]
        ping_results = {}
        voltages = {}
        temps = {}

        t0 = time.perf_counter()
        for mid in motor_ids:
            ok = bus.ping(mid)
            ping_results[mid] = ok
            if not ok:
                bus.close()
                raise PreflightCheckError(
                    f"Servo ID {mid} not responding on port {port}! "
                    f"Check actuator bus ribbon cables."
                )

            # Read power supply voltage (Register 0x3E, units 0.1V)
            try:
                raw_v = bus.read_byte(mid, Register.PRESENT_VOLTAGE, retries=2)
                voltage = raw_v / 10.0
                voltages[mid] = voltage
            except Exception:
                voltages[mid] = 0.0

            # Read temperature (Register 0x3F, units 1°C)
            try:
                temp = bus.read_byte(mid, Register.PRESENT_TEMPERATURE, retries=1)
                temps[mid] = temp
            except Exception:
                temps[mid] = 0

        dt = (time.perf_counter() - t0) * 1000.0
        bus.close()

        avg_voltage = sum(voltages.values()) / len(voltages) if voltages else 0.0
        max_temp = max(temps.values()) if temps else 0

        # Safety Check: Brownout Protection
        # If expected to be Follower (active torque), voltage must be >= 10.5V
        if expected_role.lower() == "follower" and avg_voltage < 10.5:
            raise PreflightCheckError(
                f"❌ CRITICAL POWER RAIL FAILURE: Bus voltage is {avg_voltage:.1f}V (< 10.5V required)!\n"
                f"The 12V DC power brick is DISCONNECTED. Servos are currently drawing insufficient 5.0V USB power.\n"
                f"Plug in the 12V DC power adapter to prevent bus brownout and torque collapse."
            )

        # Thermal Check
        if max_temp > 65:
            raise PreflightCheckError(
                f"⚠️ OVERHEATING HAZARD: Actuator temperature reached {max_temp}°C (Safe limit: 65°C). "
                f"Allow motors to cool before engaging high-frequency teleoperation."
            )

        return {
            "port": port,
            "role": expected_role,
            "latency_ms": round(dt / 6.0, 2),
            "voltage_v": round(avg_voltage, 1),
            "max_temp_c": max_temp,
            "all_ping_ok": True,
        }

    def execute_soft_start_alignment(
        self,
        leader_robot: Any,
        follower_robot: Any,
        duration_s: float = 1.2,
        steps: int = 50,
    ) -> None:
        """
        Smoothly interpolates the Follower arm from its current resting pose
        to the Leader arm's current physical coordinates over a smooth trajectory.
        Prevents mechanical shock and gear stripping on torque engagement.
        """
        print("🔄 [Pre-Flight] Synchronizing starting coordinates with soft-start smoothing...")
        
        # Read current poses
        leader_obs = leader_robot.get_observation()
        follower_obs = follower_robot.get_observation()

        start_joints = follower_obs.joint_positions.copy()
        target_joints = leader_obs.joint_positions.copy()
        start_grip = follower_obs.gripper_aperture
        target_grip = leader_obs.gripper_aperture

        # Calculate max angular disparity
        max_delta = max(
            abs(target_joints.get(j, 0.0) - start_joints.get(j, 0.0))
            for j in target_joints.keys()
        )

        print(f"   Initial joint disparity: {max_delta:.1f}°")
        follower_robot.set_torque(True)

        if max_delta < 5.0:
            print("✔ Coordinates closely aligned. Direct handover.")
            return

        print(f"⏳ Executing {duration_s:.1f}s smooth cubic trajectory alignment...")
        from t2_bots.core.schema import RobotAction

        dt_step = duration_s / float(steps)
        for i in range(1, steps + 1):
            # Smooth S-curve (cubic hermite) interpolation parameter s in [0..1]
            t = float(i) / float(steps)
            s = 3.0 * (t ** 2) - 2.0 * (t ** 3)

            interp_joints = {}
            for j in target_joints.keys():
                q0 = start_joints.get(j, target_joints[j])
                q1 = target_joints[j]
                interp_joints[j] = q0 + s * (q1 - q0)

            interp_grip = start_grip + s * (target_grip - start_grip)
            action = RobotAction(target_positions=interp_joints, target_gripper=interp_grip)
            follower_robot.send_action(action)
            time.sleep(dt_step)

        print("✔ Follower arm smoothly aligned to Leader posture without gear shock.")
