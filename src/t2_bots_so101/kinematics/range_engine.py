"""
ArmRangeNormalizingEngine: Standardized Kinematic Range-to-Range Mapping.
Converts heterogeneous arm physical workspaces into standardized dimensionless space:
- Revolute Joints (1..5): Bipolar Zero-Centered Normalization [-1.0 .. +1.0]
- Gripper (6): Feathered Non-Linear Unipolar Normalization [0.0 .. 1.0]
"""

from typing import Dict, Any, Optional

JOINT_ORDER = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
]

JOINT_ID_MAP = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

TICKS_PER_REV = 4096.0
DEGREES_PER_TICK = 360.0 / TICKS_PER_REV  # ~0.08789° per tick


class ArmRangeNormalizingEngine:
    """
    Standardizes input motions from any Leader arm into normalized workspace coordinates,
    and maps them seamlessly into any Follower arm's specific physical envelope.
    """

    def __init__(
        self,
        leader_calib: Optional[Dict[str, Dict[str, Any]]] = None,
        follower_calib: Optional[Dict[str, Dict[str, Any]]] = None,
        gripper_gamma: float = 1.4,
        gripper_deadband: float = 0.02,
    ):
        self.leader_calib = leader_calib or {}
        self.follower_calib = follower_calib or {}
        self.gripper_gamma = gripper_gamma
        self.gripper_deadband = gripper_deadband

    def bind_calibrations(
        self,
        leader_calib: Dict[str, Dict[str, Any]],
        follower_calib: Dict[str, Dict[str, Any]],
    ) -> None:
        """Dynamically binds calibration envelopes received across the network handshake."""
        self.leader_calib = leader_calib
        self.follower_calib = follower_calib

    def normalize_joint(self, joint_name: str, raw_tick: int, calib: Optional[Dict[str, Dict[str, Any]]] = None) -> float:
        """
        Bipolar Zero-Centered Normalization:
        - raw == zero_tick -> 0.0
        - raw == range_max -> +1.0
        - raw == range_min -> -1.0
        """
        c = (calib or self.leader_calib).get(joint_name, {})
        offset = c.get("homing_offset", 0)
        zero_tick = 2047 + offset

        r_min = c.get("range_min", 200)
        r_max = c.get("range_max", 3895)

        if raw_tick >= zero_tick:
            span_pos = r_max - zero_tick
            if span_pos <= 0:
                return 0.0
            norm = (raw_tick - zero_tick) / float(span_pos)
            return max(0.0, min(1.0, norm))
        else:
            span_neg = zero_tick - r_min
            if span_neg <= 0:
                return 0.0
            norm = (raw_tick - zero_tick) / float(span_neg)
            return max(-1.0, min(0.0, norm))

    def denormalize_joint(self, joint_name: str, norm_val: float, calib: Optional[Dict[str, Dict[str, Any]]] = None) -> int:
        """
        Converts normalized [-1.0 .. +1.0] joint coordinate to target servo ticks
        within the target arm's physical range.
        """
        c = (calib or self.follower_calib).get(joint_name, {})
        offset = c.get("homing_offset", 0)
        zero_tick = 2047 + offset

        r_min = c.get("range_min", 200)
        r_max = c.get("range_max", 3895)

        norm_clamped = max(-1.0, min(1.0, norm_val))
        if norm_clamped >= 0.0:
            span_pos = r_max - zero_tick
            tick = int(round(zero_tick + norm_clamped * span_pos))
        else:
            span_neg = zero_tick - r_min
            tick = int(round(zero_tick + norm_clamped * span_neg))

        return max(r_min, min(r_max, tick))

    def normalize_degrees(self, joint_name: str, degrees: float, calib: Optional[Dict[str, Dict[str, Any]]] = None) -> float:
        """Converts joint angle in degrees to normalized [-1.0 .. +1.0] coordinate."""
        delta_ticks = degrees / DEGREES_PER_TICK
        c = (calib or self.leader_calib).get(joint_name, {})
        offset = c.get("homing_offset", 0)
        zero_tick = 2047 + offset
        raw_tick = zero_tick + delta_ticks
        return self.normalize_joint(joint_name, int(round(raw_tick)), calib)

    def denormalize_to_degrees(self, joint_name: str, norm_val: float, calib: Optional[Dict[str, Dict[str, Any]]] = None) -> float:
        """Converts normalized [-1.0 .. +1.0] coordinate to target joint degrees relative to zero."""
        target_tick = self.denormalize_joint(joint_name, norm_val, calib)
        c = (calib or self.follower_calib).get(joint_name, {})
        offset = c.get("homing_offset", 0)
        zero_tick = 2047 + offset
        delta_ticks = target_tick - zero_tick
        return delta_ticks * DEGREES_PER_TICK

    def normalize_gripper(
        self,
        raw_tick: int,
        calib: Optional[Dict[str, Dict[str, Any]]] = None,
        gamma: Optional[float] = None,
        deadband: Optional[float] = None,
    ) -> float:
        """
        Unipolar Feathered Normalization for Gripper:
        Maps raw trigger stroke [min .. max] -> [0.0 .. 1.0] with deadband and exponential shaping.
        """
        c = (calib or self.leader_calib).get("gripper", {})
        r_min = c.get("range_min", 1680)
        r_max = c.get("range_max", 3190)
        span = max(1, r_max - r_min)

        raw_norm = (raw_tick - r_min) / float(span)
        clamped = max(0.0, min(1.0, raw_norm))

        db = self.gripper_deadband if deadband is None else deadband
        g = self.gripper_gamma if gamma is None else gamma

        if clamped <= db:
            return 0.0

        shaped = ((clamped - db) / (1.0 - db)) ** g
        return max(0.0, min(1.0, shaped))

    def denormalize_gripper(
        self,
        norm_val: float,
        calib: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> int:
        """Converts normalized [0.0 .. 1.0] aperture to Follower claw servo ticks."""
        c = (calib or self.follower_calib).get("gripper", {})
        r_min = c.get("range_min", 1680)
        r_max = c.get("range_max", 3190)
        span = max(1, r_max - r_min)

        norm_clamped = max(0.0, min(1.0, norm_val))
        target_tick = int(round(r_min + norm_clamped * span))
        return max(r_min, min(r_max, target_tick))

    def map_leader_to_follower(
        self,
        leader_joints: Dict[str, float],
        leader_gripper: float,
    ) -> Dict[str, Any]:
        """
        Seamlessly translates leader observations into follower actions.
        Guarantees 100% of leader physical motion maps inside follower limits.
        """
        target_positions = {}
        for j, deg in leader_joints.items():
            norm_q = self.normalize_degrees(j, deg, self.leader_calib)
            target_deg = self.denormalize_to_degrees(j, norm_q, self.follower_calib)
            target_positions[j] = round(target_deg, 2)

        # Gripper non-linear feathering
        norm_g = max(0.0, min(1.0, leader_gripper))
        if norm_g <= self.gripper_deadband:
            shaped_g = 0.0
        else:
            shaped_g = ((norm_g - self.gripper_deadband) / (1.0 - self.gripper_deadband)) ** self.gripper_gamma
        target_gripper = max(0.0, min(1.0, shaped_g))

        return {
            "target_positions": target_positions,
            "target_gripper": round(target_gripper, 3),
        }
