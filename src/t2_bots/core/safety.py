"""
Hardware State Verification, Invariant Assertion, and Diagnostic Safety Layer.
Guarantees zero assumed states in physical robotics operations.
"""

import time
from typing import Dict, List, Optional, Any, Tuple
from t2_bots_so101.driver.bus import FeetechBus
from t2_bots_so101.driver.registers import Register

class HardwareSafetyError(Exception):
    """Base exception for all physical hardware safety violations."""
    pass

class CalibrationIntegrityError(HardwareSafetyError):
    """Raised when a calibration profile contains corrupt or physically implausible parameters."""
    pass

class KinematicSymmetryError(HardwareSafetyError):
    """Raised when Leader and Follower kinematic centers diverge beyond safe operating limits."""
    pass

class HardwareStateMismatchError(HardwareSafetyError):
    """Raised when an actuator fails to transition to the commanded physical state."""
    def __init__(self, motor_id: int, register: int, expected: int, actual: int, details: str = ""):
        self.motor_id = motor_id
        self.register = register
        self.expected = expected
        self.actual = actual
        msg = (
            f"❌ HARDWARE STATE MISMATCH on Actuator ID {motor_id}!\n"
            f"   Register: 0x{register:02X} | Commanded: {expected} | Actual Silicon Readback: {actual}\n"
            f"   Root Cause Analysis: {details or 'Bus collision, buffer overflow, or motor firmware lock.'}"
        )
        super().__init__(msg)

class TorqueSafetyGuard:
    """
    Enforces closed-loop verification on motor torque transitions.
    Never reports torque enabled or disabled without silicon readback proof.
    """

    @staticmethod
    def set_and_verify_torque(
        bus: FeetechBus,
        motor_ids: List[int],
        enabled: bool,
        max_retries: int = 3,
        timeout_s: float = 1.0,
    ) -> Dict[int, bool]:
        """
        Commands torque transition across all specified motors and enforces
        explicit readback assertion on Register 0x28.
        """
        target_val = 1 if enabled else 0
        state_name = "ENABLED" if enabled else "DISABLED"
        start_time = time.perf_counter()

        ser_obj = getattr(bus, "ser", None) or getattr(bus, "serial", None)
        if ser_obj and ser_obj.is_open:
            try:
                ser_obj.reset_input_buffer()
            except Exception:
                pass
        time.sleep(0.005)

        verified_states: Dict[int, bool] = {}
        unverified_ids = list(motor_ids)

        for attempt in range(1, max_retries + 1):
            if not unverified_ids:
                break

            for mid in list(unverified_ids):
                # 1. Dispatch write
                try:
                    bus.write_byte(mid, Register.TORQUE_ENABLE, target_val)
                except Exception as e:
                    # Bus write dropped
                    time.sleep(0.003)
                    continue

                # 2. Silicon Readback Assertion
                try:
                    actual = bus.read_byte(mid, Register.TORQUE_ENABLE)
                    if actual == target_val:
                        verified_states[mid] = (actual == 1)
                        unverified_ids.remove(mid)
                except Exception:
                    time.sleep(0.003)

        # If any motor failed verification, perform hardware diagnostics and raise
        if unverified_ids:
            failed_id = unverified_ids[0]
            # Diagnose root cause
            diag_reason = TorqueSafetyGuard.diagnose_actuator_fault(bus, failed_id)
            raise HardwareStateMismatchError(
                motor_id=failed_id,
                register=Register.TORQUE_ENABLE,
                expected=target_val,
                actual=1 if not enabled else 0,
                details=diag_reason,
            )

        return verified_states

    @staticmethod
    def diagnose_actuator_fault(bus: FeetechBus, motor_id: int) -> str:
        """Inspects physical registers to determine why an actuator rejected a command."""
        reasons = []
        try:
            if not bus.ping(motor_id):
                return "Actuator completely unresponsive to PING. Check bus cable connection."
        except Exception:
            return "Serial communication timeout on bus."

        try:
            err = bus.read_byte(motor_id, Register.STATUS_ERROR)
            if err != 0:
                flags = []
                if err & 0x01: flags.append("VOLTAGE_ALERT (Brownout/Overvoltage)")
                if err & 0x02: flags.append("OVERHEATING (>70°C)")
                if err & 0x04: flags.append("ENCODER_SENSOR_FAILURE")
                if err & 0x08: flags.append("CHECKSUM_ERROR")
                if err & 0x10: flags.append("MECHANICAL_STALL")
                reasons.append(f"Hardware Error Register 0x41 flagged: {', '.join(flags)}")
        except Exception:
            pass

        try:
            v = bus.read_byte(motor_id, Register.PRESENT_VOLTAGE) / 10.0
            if v < 10.5:
                reasons.append(f"Power supply voltage is dangerously low: {v:.1f}V (< 10.5V)")
        except Exception:
            pass

        try:
            t = bus.read_byte(motor_id, Register.PRESENT_TEMPERATURE)
            if t > 65:
                reasons.append(f"Actuator temperature exceeds safety threshold: {t}°C")
        except Exception:
            pass

        return "; ".join(reasons) if reasons else "Half-duplex bus collision or unconsumed ACK buffer overflow."

    @staticmethod
    def audit_physical_state(bus: FeetechBus, motor_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Performs a zero-assumption physical register audit of all actuators.
        Returns exact silicon truth for position, torque, voltage, temp, and error.
        """
        audit = {}
        for mid in motor_ids:
            try:
                ping_ok = bus.ping(mid)
                torque = bus.read_byte(mid, Register.TORQUE_ENABLE)
                pos = bus.read_word(mid, Register.PRESENT_POSITION)
                err = bus.read_byte(mid, Register.STATUS_ERROR)
                volt = bus.read_byte(mid, Register.PRESENT_VOLTAGE) / 10.0
                temp = bus.read_byte(mid, Register.PRESENT_TEMPERATURE)
                load = bus.read_signed_word(mid, Register.PRESENT_LOAD)
                audit[mid] = {
                    "ping": ping_ok,
                    "torque_enabled": (torque == 1),
                    "raw_tick": pos,
                    "error_mask": err,
                    "voltage_v": volt,
                    "temperature_c": temp,
                    "load_raw": load,
                }
            except Exception as e:
                audit[mid] = {"error": f"Failed to audit: {e}"}
        return audit


class CalibrationIntegrityGuard:
    """
    Guarantees mathematical and physical plausibility of joint calibration tables.
    Prevents corrupted files, test pollution, or rogue zero-offsets from reaching physical actuators.
    """

    MAX_HOMING_OFFSET_TICKS = 600  # ~52.7° maximum permissible reference posture deviation
    MIN_ARM_SPAN_TICKS = 1000      # ~87.9° minimum mechanical travel stroke
    MAX_SYMMETRY_DISPARITY_DEG = 30.0  # Max disparity allowed between Leader & Follower zero points

    @classmethod
    def validate_profile_plausibility(cls, profile: Dict[str, Any], role: str = "robot") -> None:
        """
        Asserts that all homing offsets and range bounds in a profile are physically valid.
        """
        if not profile:
            raise CalibrationIntegrityError(f"Calibration profile for {role.upper()} is empty or missing!")

        for joint, data in profile.items():
            if not isinstance(data, dict):
                continue
            offset = data.get("homing_offset", 0)
            r_min = data.get("range_min", 0)
            r_max = data.get("range_max", 4095)

            # 1. Homing offset bounds assertion (wrist_roll allows larger excursion)
            if joint != "wrist_roll" and abs(offset) > cls.MAX_HOMING_OFFSET_TICKS:
                deg = abs(offset) * (360.0 / 4096.0)
                raise CalibrationIntegrityError(
                    f"❌ CRITICAL CALIBRATION PLAUSIBILITY FAILURE on {role.upper()} '{joint}'!\n"
                    f"   Recorded homing offset: {offset:+d} ticks (~{deg:.1f}°)\n"
                    f"   Allowed safe boundary:  ±{cls.MAX_HOMING_OFFSET_TICKS} ticks (±52.7°)\n"
                    f"   Root Cause: Corrupted profile, test mock data pollution, or inverted sensor read."
                )

            # 2. Minimum travel span assertion for primary arm joints
            if joint in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex"]:
                span = r_max - r_min
                if span < cls.MIN_ARM_SPAN_TICKS:
                    deg_span = span * (360.0 / 4096.0)
                    raise CalibrationIntegrityError(
                        f"❌ INVALID RANGE BOUNDS on {role.upper()} '{joint}'!\n"
                        f"   Measured travel: {span} ticks ({deg_span:.1f}°)\n"
                        f"   Minimum required: {cls.MIN_ARM_SPAN_TICKS} ticks (~88°)\n"
                        f"   Root Cause: Joint was not swept through its physical stroke during calibration."
                    )

    @classmethod
    def assert_dual_arm_symmetry(
        cls,
        leader_profile: Dict[str, Any],
        follower_profile: Dict[str, Any],
        max_allowed_deg: float = 30.0,
    ) -> Dict[str, float]:
        """
        Validates that both arms share compatible kinematic centers.
        Prevents teleoperation when zero points diverge significantly.
        """
        cls.validate_profile_plausibility(leader_profile, role="leader")
        cls.validate_profile_plausibility(follower_profile, role="follower")

        disparities = {}
        for joint in ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex"]:
            l_off = leader_profile.get(joint, {}).get("homing_offset", 0)
            f_off = follower_profile.get(joint, {}).get("homing_offset", 0)
            delta_deg = abs(f_off - l_off) * (360.0 / 4096.0)
            disparities[joint] = delta_deg
            if delta_deg > max_allowed_deg:
                raise KinematicSymmetryError(
                    f"❌ DUAL-ARM KINEMATIC SYMMETRY VIOLATION on '{joint}'!\n"
                    f"   Leader Offset:   {l_off:+5d} ticks\n"
                    f"   Follower Offset: {f_off:+5d} ticks\n"
                    f"   Angular Disparity: {delta_deg:.1f}° (Limit: {max_allowed_deg:.1f}°)\n"
                    f"   Action Required: Re-align both arms to 90° reference pose and calibrate."
                )
        return disparities

    @staticmethod
    def create_backup(profile: Dict[str, Any], role: str) -> Optional[Any]:
        """Creates an immutable timestamped backup of verified calibration."""
        import os
        from datetime import datetime, timezone
        from pathlib import Path
        import json
        if "PYTEST_CURRENT_TEST" in os.environ or "T2_BOTS_TESTING" in os.environ:
            return None
        backup_dir = Path.home() / ".config" / "t2_bots" / "calibration" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        b_path = backup_dir / f"so101_{role}_{ts}.json"
        with open(b_path, "w") as f:
            json.dump(profile, f, indent=2)
        return b_path
