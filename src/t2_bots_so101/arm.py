"""
SO101 6-DOF Robotic Manipulator & Teleoperator Implementation for t2-BOTS.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from t2_bots.core.base import RobotManipulator, RobotRole
from t2_bots.core.schema import RobotState, RobotAction, ObservationFrame
from t2_bots_so101.driver.bus import FeetechBus
from t2_bots_so101.driver.registers import Register, OperatingMode
from t2_bots_so101.kinematics.normalizer import (
    JointNormalizer,
    JOINT_ORDER,
    JOINT_ID_MAP,
)

DEFAULT_CALIB_DIR = Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"

# Calibrated Standard Postures for SO101 6-DOF Embodiment
SO101_STANDARD_POSES: Dict[str, Dict[str, float]] = {
    "rest": {
        "shoulder_pan": 0.0,
        "shoulder_lift": -100.0,
        "elbow_flex": 100.0,
        "wrist_flex": 90.0,
        "wrist_roll": 0.0,
        "gripper": 0.0,
    },
    "standby": {
        "shoulder_pan": 0.0,
        "shoulder_lift": -30.0,
        "elbow_flex": 60.0,
        "wrist_flex": 30.0,
        "wrist_roll": 0.0,
        "gripper": 0.5,
    },
    "zero": {
        "shoulder_pan": 0.0,
        "shoulder_lift": 0.0,
        "elbow_flex": 0.0,
        "wrist_flex": 0.0,
        "wrist_roll": 0.0,
        "gripper": 0.0,
    },
}

class SO101Manipulator(RobotManipulator):
    """Production driver for SO101 Follower Arm (Robotic End-Effector)."""

    def __init__(
        self,
        name: str = "so101",
        role: RobotRole = RobotRole.FOLLOWER,
        port: Optional[str] = None,
        calib_file: Optional[Path] = None,
    ):
        super().__init__(name=name, role=role, port=port)
        self.motor_ids = [1, 2, 3, 4, 5, 6]
        self.bus = FeetechBus(port=self.port) if self.port else None
        
        # Load or locate calibration
        if calib_file is None:
            native_sub = "so101_follower" if role == RobotRole.FOLLOWER else "so101_leader"
            native_calib = Path.home() / ".config" / "t2_bots" / "calibration" / f"{native_sub}.json"
            if native_calib.exists():
                calib_file = native_calib
            else:
                sub = "robots/so_follower" if role == RobotRole.FOLLOWER else "teleoperators/so_leader"
                calib_file = DEFAULT_CALIB_DIR / sub / "None.json"
        self.calib_file = Path(calib_file)
        self.calib_data = self._load_calibration()
        self.normalizer = JointNormalizer(self.calib_data)

    def _load_calibration(self) -> Dict[str, Dict]:
        if self.calib_file.exists():
            try:
                with open(self.calib_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def reload_calibration(self, calib_data: Optional[Dict[str, Dict]] = None) -> None:
        """Reloads calibration profile and updates kinematics normalizer in-flight."""
        if calib_data is not None:
            self.calib_data = calib_data
        else:
            self.calib_data = self._load_calibration()
        self.normalizer = JointNormalizer(self.calib_data)

    def connect(self) -> None:
        if not self.port:
            raise ValueError(f"Port not configured for {self.name}")
        if self.bus is None:
            self.bus = FeetechBus(port=self.port)
        self.bus.open()
        self.is_connected = True

    def disconnect(self) -> None:
        if self.bus is not None:
            try:
                self.set_torque(False)
            finally:
                self.bus.close()
        self.is_connected = False

    def ping(self) -> Dict[str, bool]:
        if not self.is_connected:
            self.connect()
        status = {}
        for mid in self.motor_ids:
            name = JOINT_ID_MAP[mid]
            status[name] = self.bus.ping(mid)
        return status

    def set_torque(self, enabled: bool) -> None:
        """
        Enforces verified torque state transition on all actuators.
        Raises HardwareStateMismatchError if any motor fails to latch state.
        """
        if not self.is_connected:
            return
        from t2_bots.core.safety import TorqueSafetyGuard
        TorqueSafetyGuard.set_and_verify_torque(self.bus, self.motor_ids, enabled=enabled)

    def get_state(self) -> RobotState:
        """Returns raw ticks, engineering degrees, and bus diagnostics."""
        t0 = time.perf_counter()
        raw_dict = self.bus.sync_read_positions(self.motor_ids)
        dt = (time.perf_counter() - t0) * 1000.0

        deg_dict = {}
        for mid, raw in raw_dict.items():
            name = JOINT_ID_MAP[mid]
            deg_dict[name] = self.normalizer.ticks_to_degrees(name, raw)

        return RobotState(
            positions_raw={JOINT_ID_MAP[k]: v for k, v in raw_dict.items()},
            positions_deg=deg_dict,
            bus_latency_ms=dt,
            torque_enabled=True,
        )

    def get_observation(self) -> ObservationFrame:
        """Fast 60 Hz normalized telemetry frame for Physical AI inference."""
        t0 = time.perf_counter()
        raw_dict = self.bus.sync_read_positions(self.motor_ids)
        dt = (time.perf_counter() - t0) * 1000.0

        joint_pos = {}
        for mid in self.motor_ids[:-1]:  # Joints 1 to 5
            name = JOINT_ID_MAP[mid]
            raw = raw_dict.get(mid, 2047)
            joint_pos[name] = self.normalizer.ticks_to_degrees(name, raw)

        raw_grip = raw_dict.get(6, 2047)
        aperture = self.normalizer.gripper_ticks_to_aperture(raw_grip)

        return ObservationFrame(
            joint_positions=joint_pos,
            gripper_aperture=aperture,
            latency_ms=dt,
        )

    def send_action(self, action: RobotAction) -> None:
        """Converts normalized physical targets to raw ticks and executes via SYNC_WRITE."""
        target_ticks = {}
        for name, deg in action.target_positions.items():
            mid = next((k for k, v in JOINT_ID_MAP.items() if v == name), None)
            if mid:
                target_ticks[mid] = self.normalizer.degrees_to_ticks(name, deg)

        if action.target_gripper is not None:
            target_ticks[6] = self.normalizer.gripper_aperture_to_ticks(action.target_gripper)

        if target_ticks:
            self.bus.sync_write_positions(target_ticks)

    @property
    def standard_poses(self) -> Dict[str, Dict[str, float]]:
        """Calibrated standard poses for SO101 embodiment."""
        return SO101_STANDARD_POSES

    def run_commissioning(self) -> Dict[str, Any]:
        """Runs the turnkey commissioning state machine."""
        from t2_bots_so101.commissioning.engine import run_so101_commissioning
        return run_so101_commissioning(self.port, self.role)

class SO101Teleoperator(SO101Manipulator):
    """SO101 Leader Arm (Manual Input Handle). Runs in passive zero-torque mode."""

    def __init__(self, name: str = "so101_leader", role: RobotRole = RobotRole.LEADER, port: Optional[str] = None, **kwargs):
        super().__init__(name=name, role=RobotRole.LEADER, port=port, **kwargs)

    def connect(self) -> None:
        super().connect()
        # Teleoperator arms always disable motor holding torque
        self.set_torque(False)
