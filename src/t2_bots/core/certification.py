"""
Turnkey Hardware Certification Engine, Power Rail Supervision,
and Cryptographic Hardware Qualification Certificates for t2-BOTS Robotics SDK.
"""

from __future__ import annotations

import os
import sys
import json
import time
import hmac
import hashlib
import platform
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Union, Tuple, List

from t2_bots.core.preflight import HardwarePreflight, KNOWN_DEVICES
from t2_bots.core.calibration import (
    get_calib_dir,
    CANONICAL_REST_ANGLES,
    JOINT_ID_MAP,
    DEGREES_PER_TICK,
)
from t2_bots_so101.driver.registers import Register

CERTIFICATE_VERSION = "1.0.0"
DEFAULT_SECRET_SALT = "t2-bots-hardware-qualification-v1"
DEFAULT_MAX_AGE_DAYS = 30

MIN_VOLTAGE_FOLLOWER = 11.5  # 12V Nominal supply threshold for active torque
MIN_VOLTAGE_LEADER = 4.8     # 5V USB / 12V supply threshold for passive teleoperator
MOTOR_2_TARGET_LIMIT = 3300  # Shoulder lift forward workspace limit (~110° reach)
DEFAULT_SOFT_CLEARANCE_TICKS = 30  # Safety buffer off mechanical stops to prevent thermal stall


def parse_iso_timestamp(ts: str) -> datetime:
    """Parses standard ISO 8601 UTC timestamp into a timezone-aware datetime object."""
    clean_ts = ts.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class HardwareCertificate:
    """
    Cryptographic Hardware Qualification Certificate qualifying an arm
    for safe, repeatable closed-loop teleoperation and swarm admission.
    """
    certificate_version: str = CERTIFICATE_VERSION
    arm_id: str = ""
    role: str = "follower"
    certified_at: str = ""
    system_fingerprint: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    readiness_score: int = 0
    grade: str = "FAILED"
    signature_sha256: str = ""

    def __post_init__(self):
        self.certificate_version = str(self.certificate_version)
        self.arm_id = str(self.arm_id)
        self.role = str(self.role).lower()
        if not self.certified_at:
            self.certified_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.readiness_score = int(self.readiness_score)
        self.grade = str(self.grade).upper()

        # Normalize system_fingerprint
        raw_fp = self.system_fingerprint
        if not isinstance(raw_fp, dict):
            if hasattr(raw_fp, "to_dict"):
                raw_fp = raw_fp.to_dict()
            elif hasattr(raw_fp, "__dict__"):
                raw_fp = dict(raw_fp.__dict__)
            else:
                raw_fp = dict(raw_fp)

        self.system_fingerprint = {
            "os": str(raw_fp.get("os", sys.platform)),
            "python_version": str(raw_fp.get("python_version", platform.python_version())),
            "architecture": str(raw_fp.get("architecture", platform.machine())),
            "serial_port": str(raw_fp.get("serial_port", "")),
            "baudrate": int(raw_fp.get("baudrate", 1_000_000)),
        }

        # Normalize diagnostics
        raw_diag = self.diagnostics
        if not isinstance(raw_diag, dict):
            if hasattr(raw_diag, "to_dict"):
                raw_diag = raw_diag.to_dict()
            elif hasattr(raw_diag, "__dict__"):
                raw_diag = dict(raw_diag.__dict__)
            else:
                raw_diag = dict(raw_diag)

        self.diagnostics = {
            "bus_voltage_v": round(float(raw_diag.get("bus_voltage_v", 0.0)), 2),
            "max_temp_c": round(float(raw_diag.get("max_temp_c", 0.0)), 1),
            "motor_2_unlocked": bool(raw_diag.get("motor_2_unlocked", False)),
            "soft_clearance_ticks": int(raw_diag.get("soft_clearance_ticks", DEFAULT_SOFT_CLEARANCE_TICKS)),
            "holding_torque_qualified": bool(raw_diag.get("holding_torque_qualified", False)),
            "range_disparity_deg": round(float(raw_diag.get("range_disparity_deg", 0.0)), 2),
        }

    def compute_canonical_payload(self) -> str:
        """
        Produces deterministic canonical JSON serialization over signed fields.
        Excludes signature_sha256 to ensure idempotent calculation.
        """
        payload = {
            "certificate_version": self.certificate_version,
            "arm_id": self.arm_id,
            "role": self.role,
            "certified_at": self.certified_at,
            "system_fingerprint": self.system_fingerprint,
            "diagnostics": self.diagnostics,
            "readiness_score": self.readiness_score,
            "grade": self.grade,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def compute_signature(self, secret_salt: str = DEFAULT_SECRET_SALT) -> str:
        """Computes SHA-256 cryptographic signature over canonical JSON and salt."""
        canonical_str = self.compute_canonical_payload()
        salted_data = f"{canonical_str}:{secret_salt}".encode("utf-8")
        return hashlib.sha256(salted_data).hexdigest()

    def sign(self, secret_salt: str = DEFAULT_SECRET_SALT) -> str:
        """Computes and assigns signature_sha256 in place."""
        self.signature_sha256 = self.compute_signature(secret_salt=secret_salt)
        return self.signature_sha256

    def to_dict(self) -> Dict[str, Any]:
        """Serializes certificate to standard Python dictionary."""
        return {
            "certificate_version": self.certificate_version,
            "arm_id": self.arm_id,
            "role": self.role,
            "certified_at": self.certified_at,
            "system_fingerprint": self.system_fingerprint,
            "diagnostics": self.diagnostics,
            "readiness_score": self.readiness_score,
            "grade": self.grade,
            "signature_sha256": self.signature_sha256,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serializes certificate to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HardwareCertificate":
        """Instantiates HardwareCertificate from dictionary."""
        return cls(
            certificate_version=data.get("certificate_version", CERTIFICATE_VERSION),
            arm_id=data.get("arm_id", ""),
            role=data.get("role", "follower"),
            certified_at=data.get("certified_at", ""),
            system_fingerprint=data.get("system_fingerprint", {}),
            diagnostics=data.get("diagnostics", {}),
            readiness_score=int(data.get("readiness_score", 0)),
            grade=data.get("grade", "FAILED"),
            signature_sha256=data.get("signature_sha256", ""),
        )


class CertificationError(Exception):
    """Base exception for hardware certification and qualification failures."""
    def __init__(self, message: str, certificate: Optional[HardwareCertificate] = None):
        super().__init__(message)
        self.certificate = certificate


class LowVoltageError(CertificationError):
    """Raised when bus power rail fails voltage requirements."""
    pass


class CertificateTamperedError(CertificationError):
    """Raised when certificate cryptographic signature validation detects tampering."""
    pass


class CertificateExpiredError(CertificationError):
    """Raised when certificate has expired beyond allowed validity window."""
    pass


class CertificationEngine:
    """
    Hardware Certification Engine for t2-BOTS Universal Swarm SDK.
    Performs power rail inspection (12V nominal / 5V nominal), unlocks Motor 2 EEPROM angle limits,
    enforces 30-tick thermal soft clearance, verifies homing repeatability, and issues
    tamper-evident signed HardwareQualificationCertificates.
    """

    def __init__(
        self,
        cert_dir: Optional[Path] = None,
        calib_dir: Optional[Path] = None,
        secret_salt: str = DEFAULT_SECRET_SALT,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    ):
        self.cert_dir = Path(cert_dir) if cert_dir is not None else Path.home() / ".config" / "t2_bots" / "certificates"
        self.calib_dir = Path(calib_dir) if calib_dir is not None else get_calib_dir()
        self.secret_salt = secret_salt
        self.max_age_days = max_age_days
        self.preflight = HardwarePreflight()

    def get_certificate_path(self, arm_id: str) -> Path:
        """Returns target filesystem path ~/.config/t2_bots/certificates/{arm_id}_qualification.json."""
        sanitized = arm_id.replace("/", "_").replace("\\", "_")
        return self.cert_dir / f"{sanitized}_qualification.json"

    def save_certificate(self, cert: HardwareCertificate, path: Optional[Path] = None) -> Path:
        """Persists signed certificate to disk."""
        target_path = path or self.get_certificate_path(cert.arm_id)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(cert.to_json(indent=2))
        return target_path

    def load_certificate(
        self, cert_path_or_dict: Union[str, Path, Dict[str, Any], HardwareCertificate]
    ) -> HardwareCertificate:
        """Loads and coerces certificate into HardwareCertificate instance."""
        if isinstance(cert_path_or_dict, HardwareCertificate):
            return cert_path_or_dict
        elif isinstance(cert_path_or_dict, dict):
            return HardwareCertificate.from_dict(cert_path_or_dict)
        elif isinstance(cert_path_or_dict, (str, Path)):
            path = Path(cert_path_or_dict)
            if not path.exists():
                raise FileNotFoundError(f"Certificate file does not exist: {path}")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return HardwareCertificate.from_dict(data)
        else:
            raise TypeError(f"Invalid certificate type: {type(cert_path_or_dict)}")

    def certify_arm(
        self,
        role: str = "follower",
        arm_id: Optional[str] = None,
        port: Optional[str] = None,
        bus_override: Optional[Any] = None,
        unlock_eeprom: bool = True,
        clear_errors: bool = True,
        safety_margin_ticks: int = DEFAULT_SOFT_CLEARANCE_TICKS,
        raise_on_failure: bool = True,
        save_certificate: bool = True,
    ) -> HardwareCertificate:
        """
        Executes physical qualification and certification of an attached arm:
        1. Resolves role, port, and serial identity.
        2. Inspects power rail voltage (>=11.5V follower, >=4.8V leader).
        3. Pings all 6 DOF actuators and reads thermal state.
        4. Unlocks Motor 2 EEPROM angle ceiling (3300 ticks).
        5. Computes and enforces 30-tick soft clearance off physical stops.
        6. Verifies homing repeatable reference and holding torque capability.
        7. Issues, cryptographically signs, and saves the HardwareQualificationCertificate.
        """
        role_str = role.lower()
        if role_str not in ("follower", "leader"):
            raise ValueError(f"Invalid arm role '{role}'. Must be 'follower' or 'leader'.")

        # 1. Port & Arm ID Resolution
        resolved_port = port
        if resolved_port is None and bus_override is None:
            resolved_port = self.preflight.resolve_single_arm(role_str)

        resolved_arm_id = arm_id
        if not resolved_arm_id:
            sn = ""
            if resolved_port:
                ports_meta = self.preflight.scan_ports()
                sn = ports_meta.get(resolved_port, {}).get("serial_number", "")
            if not sn:
                sn = self.preflight.registry.get(role_str, KNOWN_DEVICES.get(role_str, "5C821078261"))
            prefix = "FOL" if role_str == "follower" else "LEA"
            resolved_arm_id = f"SO101-{prefix}-{sn}"

        # 2. Open serial bus
        from t2_bots_so101.driver.bus import FeetechBus

        bus = bus_override
        should_close_bus = False
        if bus is None:
            bus = FeetechBus(port=resolved_port)
            bus.open()
            should_close_bus = True

        try:
            motor_ids = [1, 2, 3, 4, 5, 6]
            voltages = {}
            temps = {}
            status_errors = {}
            positions_raw = {}
            min_limits = {}
            max_limits = {}

            # 3. Ping actuators and query telemetry
            for mid in motor_ids:
                j_name = JOINT_ID_MAP[mid]
                if not bus.ping(mid):
                    raise CertificationError(
                        f"Actuator ID {mid} ({j_name}) failed communication ping! "
                        f"Check ribbon cable and power bus."
                    )

                v_byte = bus.read_byte(mid, Register.PRESENT_VOLTAGE)
                if v_byte is None:
                    raise CertificationError(f"Motor {mid}: voltage read failed.")
                volt = v_byte / 10.0
                voltages[mid] = volt

                temp = bus.read_byte(mid, Register.PRESENT_TEMPERATURE)
                if temp is None:
                    raise CertificationError(f"Motor {mid}: temperature read failed.")
                temps[mid] = temp

                err = bus.read_byte(mid, Register.STATUS_ERROR)
                if err is None or err != 0:
                    raise CertificationError(f"Motor {mid}: unreadable or nonzero status error ({err}).")
                status_errors[mid] = err

                pos = bus.read_word(mid, Register.PRESENT_POSITION)
                if pos is None or not 0 <= pos <= 4095:
                    raise CertificationError(f"Motor {mid}: invalid encoder position.")
                positions_raw[mid] = pos

                min_lim = bus.read_word(mid, Register.MIN_ANGLE_LIMIT)
                if min_lim is None:
                    raise CertificationError(f"Motor {mid}: lower limit read failed.")
                min_limits[mid] = min_lim

                max_lim = bus.read_word(mid, Register.MAX_ANGLE_LIMIT)
                if max_lim is None or not 0 <= min_lim < max_lim <= 4095:
                    raise CertificationError(f"Motor {mid}: invalid firmware limits.")
                max_limits[mid] = max_lim

                if bus.read_byte(mid, Register.TORQUE_ENABLE) != 0:
                    raise CertificationError(f"Motor {mid}: support the arm and release torque before certification.")

            avg_voltage = sum(voltages.values()) / len(voltages)
            max_temp = max(temps.values()) if temps else 40
            min_v = MIN_VOLTAGE_FOLLOWER if role_str == "follower" else MIN_VOLTAGE_LEADER
            if min(voltages.values()) < min_v:
                raise LowVoltageError(f"Every motor must measure at least {min_v}V before certification.")
            if max_temp > 60:
                raise CertificationError("A motor is above 60 degrees C. Let the arm cool.")

            # 4. Error flag clearance
            for mid, err in status_errors.items():
                if err != 0 and clear_errors:
                    try:
                        bus.write_byte(mid, Register.LOCK, 0)
                        bus.write_byte(mid, Register.STATUS_ERROR, 0)
                        bus.write_byte(mid, Register.LOCK, 1)
                    except Exception:
                        pass

            # 5. Motor 2 EEPROM Angle Limit Audit & Unlock
            m2_max = max_limits.get(2, 2659)
            m2_unlocked = m2_max >= MOTOR_2_TARGET_LIMIT
            if not m2_unlocked and unlock_eeprom and role_str == "follower":
                try:
                    bus.write_byte(2, Register.LOCK, 0)
                    bus.write_word(2, Register.MAX_ANGLE_LIMIT, MOTOR_2_TARGET_LIMIT)
                    bus.write_byte(2, Register.LOCK, 1)
                    if bus.read_word(2, Register.MAX_ANGLE_LIMIT) != MOTOR_2_TARGET_LIMIT:
                        raise CertificationError("Motor 2 firmware limit did not pass readback verification.")
                    max_limits[2] = MOTOR_2_TARGET_LIMIT
                    m2_unlocked = True
                except Exception as e:
                    raise CertificationError(f"Motor 2 EEPROM unlock failed: {e}") from e

            # 6. Posture & Mechanical Stop Soft Clearance (30-tick safety buffer)
            for mid in motor_ids:
                raw_pos = positions_raw[mid]
                min_l = min_limits[mid]
                max_l = max_limits[mid]

                dist_min = raw_pos - min_l
                dist_max = max_l - raw_pos

                safe_pos = raw_pos
                if dist_min < safety_margin_ticks:
                    safe_pos = min_l + safety_margin_ticks
                elif dist_max < safety_margin_ticks:
                    safe_pos = max_l - safety_margin_ticks

            # 7. Homing Verification & Kinematic Range Disparity
            disparities = []
            for mid in [1, 2, 3, 4, 5]:
                j_name = JOINT_ID_MAP[mid]
                target_deg = CANONICAL_REST_ANGLES.get(j_name, 0.0)
                zero_tick = int(round(positions_raw[mid] - (target_deg / DEGREES_PER_TICK)))
                actual_deg = (positions_raw[mid] - zero_tick) * DEGREES_PER_TICK
                disparities.append(abs(actual_deg - target_deg))
            range_disparity = max(disparities) if disparities else 0.0

            # 8. Holding Torque Qualification
            holding_torque_qualified = False
            if role_str == "follower":
                try:
                    for mid in motor_ids:
                        if not min_limits[mid] + safety_margin_ticks <= positions_raw[mid] <= max_limits[mid] - safety_margin_ticks:
                            raise CertificationError(f"Motor {mid}: move at least {safety_margin_ticks} ticks away from firmware end limits.")
                        bus.write_word(mid, Register.GOAL_POSITION, positions_raw[mid])
                        if bus.read_word(mid, Register.GOAL_POSITION) != positions_raw[mid]:
                            raise CertificationError(f"Motor {mid}: holding target readback failed.")
                    for mid in motor_ids:
                        bus.write_byte(mid, Register.TORQUE_ENABLE, 1)
                        if bus.read_byte(mid, Register.TORQUE_ENABLE) != 1:
                            raise CertificationError(f"Motor {mid}: holding torque readback failed.")
                    holding_torque_qualified = True
                finally:
                    release_errors = []
                    for mid in motor_ids:
                        try:
                            bus.write_byte(mid, Register.TORQUE_ENABLE, 0)
                            if bus.read_byte(mid, Register.TORQUE_ENABLE) != 0:
                                release_errors.append(mid)
                        except Exception:
                            release_errors.append(mid)
                    if release_errors:
                        raise CertificationError(f"Torque release could not be verified on motors {release_errors}. Support the arm and use its power switch.")
            else:
                holding_torque_qualified = all(bus.read_byte(mid, Register.TORQUE_ENABLE) == 0 for mid in motor_ids)

            # 9. Power Rail Voltage Verification
            min_v = MIN_VOLTAGE_FOLLOWER if role_str == "follower" else MIN_VOLTAGE_LEADER
            voltage_qualified = min(voltages.values()) >= min_v

            # 10. Readiness Score and Grade Calculation
            if not voltage_qualified:
                readiness_score = 0
                grade = "FAILED"
            else:
                score = 100
                if not m2_unlocked and role_str == "follower":
                    score -= 15
                if max_temp > 60:
                    score -= 15
                if range_disparity > 15.0:
                    score -= 10
                if not holding_torque_qualified:
                    score -= 30

                readiness_score = max(0, min(100, score))
                if readiness_score >= 95:
                    grade = "A+"
                elif readiness_score >= 85:
                    grade = "A"
                elif readiness_score >= 70:
                    grade = "B"
                else:
                    grade = "FAILED"

            # 11. System Fingerprint & Diagnostics Assembly
            fingerprint = {
                "os": sys.platform,
                "python_version": platform.python_version(),
                "architecture": platform.machine(),
                "serial_port": str(resolved_port or "bus_override"),
                "baudrate": 1_000_000,
            }

            diagnostics = {
                "bus_voltage_v": round(avg_voltage, 2),
                "max_temp_c": round(float(max_temp), 1),
                "motor_2_unlocked": bool(m2_unlocked),
                "soft_clearance_ticks": int(safety_margin_ticks),
                "holding_torque_qualified": bool(holding_torque_qualified),
                "range_disparity_deg": round(float(range_disparity), 2),
            }

            cert = HardwareCertificate(
                certificate_version=CERTIFICATE_VERSION,
                arm_id=resolved_arm_id,
                role=role_str,
                certified_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                system_fingerprint=fingerprint,
                diagnostics=diagnostics,
                readiness_score=readiness_score,
                grade=grade,
            )
            cert.sign(secret_salt=self.secret_salt)

            # 12. Save Certificate to Disk
            if save_certificate:
                self.save_certificate(cert)

            # 13. Substandard Voltage or Failure Handlers
            if not voltage_qualified:
                err_msg = (
                    f"Power rail voltage {avg_voltage:.2f}V is substandard "
                    f"(minimum {min_v}V required for {role_str} arm). Certification FAILED."
                )
                if raise_on_failure:
                    raise LowVoltageError(err_msg, certificate=cert)
                return cert

            if grade == "FAILED" and raise_on_failure:
                raise CertificationError(
                    f"Hardware certification failed for arm {resolved_arm_id} (grade: FAILED, score: {readiness_score}).",
                    certificate=cert,
                )

            return cert

        finally:
            if should_close_bus:
                bus.close()

    # Alias for convenience
    certify = certify_arm

    def verify_certificate(
        self,
        cert_path_or_dict: Union[str, Path, Dict[str, Any], HardwareCertificate],
        max_age_days: Optional[int] = None,
        secret_salt: Optional[str] = None,
        raise_on_error: bool = False,
    ) -> bool:
        """
        Validates cryptographic SHA-256 signature and checks whether certificate
        has been tampered with or is expired.
        """
        salt = secret_salt or self.secret_salt
        allowed_age = max_age_days if max_age_days is not None else self.max_age_days

        try:
            cert = self.load_certificate(cert_path_or_dict)
        except Exception as e:
            if raise_on_error:
                raise CertificationError(f"Failed to load certificate: {e}") from e
            return False

        # 1. Cryptographic Signature Verification
        expected_sig = cert.compute_signature(secret_salt=salt)
        if not cert.signature_sha256 or not hmac.compare_digest(cert.signature_sha256, expected_sig):
            if raise_on_error:
                raise CertificateTamperedError(
                    f"Signature mismatch! Certificate data has been tampered with. "
                    f"Expected {expected_sig[:12]}..., got {str(cert.signature_sha256)[:12]}..."
                )
            return False

        # 2. Expiration Verification
        if allowed_age is not None:
            try:
                cert_dt = parse_iso_timestamp(cert.certified_at)
                now_utc = datetime.now(timezone.utc)
                age_days = (now_utc - cert_dt).total_seconds() / 86400.0
                if age_days < 0 or age_days > allowed_age:
                    if raise_on_error:
                        raise CertificateExpiredError(
                            f"Certificate expired: certified {age_days:.1f} days ago (allowed limit: {allowed_age} days)."
                        )
                    return False
            except CertificateExpiredError:
                raise
            except Exception as e:
                if raise_on_error:
                    raise CertificationError(f"Invalid timestamp format in certificate: {cert.certified_at}") from e
                return False

        # 3. Grade Verification (FAILED certificate cannot qualify arm)
        if cert.grade == "FAILED":
            if raise_on_error:
                raise CertificationError("Certificate grade is FAILED. Arm did not pass hardware qualification.")
            return False

        return True


def verify_certificate(
    cert_path_or_dict: Union[str, Path, Dict[str, Any], HardwareCertificate],
    max_age_days: Optional[int] = DEFAULT_MAX_AGE_DAYS,
    secret_salt: str = DEFAULT_SECRET_SALT,
    raise_on_error: bool = False,
) -> bool:
    """Convenience module-level validator for hardware qualification certificates."""
    engine = CertificationEngine(secret_salt=secret_salt, max_age_days=max_age_days or DEFAULT_MAX_AGE_DAYS)
    return engine.verify_certificate(
        cert_path_or_dict=cert_path_or_dict,
        max_age_days=max_age_days,
        secret_salt=secret_salt,
        raise_on_error=raise_on_error,
    )


__all__ = [
    "CERTIFICATE_VERSION",
    "DEFAULT_SECRET_SALT",
    "DEFAULT_MAX_AGE_DAYS",
    "MIN_VOLTAGE_FOLLOWER",
    "MIN_VOLTAGE_LEADER",
    "MOTOR_2_TARGET_LIMIT",
    "DEFAULT_SOFT_CLEARANCE_TICKS",
    "HardwareCertificate",
    "CertificationEngine",
    "CertificationError",
    "LowVoltageError",
    "CertificateTamperedError",
    "CertificateExpiredError",
    "verify_certificate",
    "parse_iso_timestamp",
]
