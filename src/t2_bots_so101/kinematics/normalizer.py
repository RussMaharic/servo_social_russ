"""
Kinematic Normalizer: Encoder Ticks [0..4095] to Physical Engineering Units.
"""

from typing import Dict, Tuple

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

class JointNormalizer:
    """Translates between raw STS3215 encoder ticks and normalized Physical AI spaces."""

    def __init__(self, calibration_profile: Dict[str, Dict]):
        self.calib = calibration_profile

    def ticks_to_degrees(self, joint_name: str, raw_tick: int) -> float:
        """Translates raw encoder tick to degrees relative to calibrated zero."""
        offset = 0
        if joint_name in self.calib:
            offset = self.calib[joint_name].get("homing_offset", 0)
        zero_tick = 2047 + offset
        delta_ticks = raw_tick - zero_tick
        return delta_ticks * DEGREES_PER_TICK

    def degrees_to_ticks(self, joint_name: str, degrees: float) -> int:
        """Translates target angle in degrees to raw servo encoder ticks."""
        offset = 0
        if joint_name in self.calib:
            offset = self.calib[joint_name].get("homing_offset", 0)
        zero_tick = 2047 + offset
        delta_ticks = degrees / DEGREES_PER_TICK
        tick = int(round(zero_tick + delta_ticks))
        
        # Clamp to calibrated safety range if available
        if joint_name in self.calib:
            r_min = self.calib[joint_name].get("range_min", 0)
            r_max = self.calib[joint_name].get("range_max", 4095)
            tick = max(r_min, min(r_max, tick))
        return tick

    def gripper_ticks_to_aperture(self, raw_tick: int, gamma: float = 1.0, deadband: float = 0.0) -> float:
        """Normalizes gripper claw stroke to 0.0 (closed) to 1.0 (fully open)."""
        if "gripper" not in self.calib:
            return float(raw_tick) / 4095.0
        
        r_min = self.calib["gripper"].get("range_min", 1680)
        r_max = self.calib["gripper"].get("range_max", 3190)
        span = r_max - r_min
        if span <= 0:
            return 0.5
        
        norm = (raw_tick - r_min) / float(span)
        clamped = max(0.0, min(1.0, norm))
        if deadband > 0.0:
            if clamped <= deadband:
                return 0.0
            clamped = (clamped - deadband) / (1.0 - deadband)
        if gamma != 1.0:
            clamped = clamped ** gamma
        return max(0.0, min(1.0, clamped))

    def gripper_aperture_to_ticks(self, aperture: float, gamma: float = 1.0, deadband: float = 0.0) -> int:
        """Converts normalized aperture [0.0..1.0] to target servo ticks."""
        if "gripper" not in self.calib:
            return int(round(aperture * 4095))
        
        r_min = self.calib["gripper"].get("range_min", 1680)
        r_max = self.calib["gripper"].get("range_max", 3190)
        span = r_max - r_min
        if span <= 0:
            return r_min
        
        clamped_aperture = max(0.0, min(1.0, aperture))
        if deadband > 0.0:
            if clamped_aperture <= deadband:
                clamped_aperture = 0.0
            else:
                clamped_aperture = (clamped_aperture - deadband) / (1.0 - deadband)
        if gamma != 1.0:
            clamped_aperture = clamped_aperture ** gamma

        tick = int(round(r_min + (clamped_aperture * span)))
        return max(r_min, min(r_max, tick))
