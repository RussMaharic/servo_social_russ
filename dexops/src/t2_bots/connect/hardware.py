"""Measured, single-owner calibration. No hardware is simulated in the app."""
import logging
import time

from t2_bots.core.calibration import JOINT_ID_MAP, CANONICAL_REST_ANGLES, DEGREES_PER_TICK
from t2_bots_so101.driver.bus import FeetechBus
from t2_bots_so101.driver.registers import Register


def discover():
    from serial.tools.list_ports import comports
    result = []
    for item in comports():
        if item.vid is None or "bluetooth" in (item.description or "").lower():
            continue
        serial = item.serial_number or ""
        identity = f"{item.vid:04x}:{item.pid or 0:04x}:{serial or item.device}"
        result.append({"port": item.device, "label": item.description or "USB serial adapter",
                       "serial": serial, "identity": identity, "stable_identity": bool(serial)})
    return sorted(result, key=lambda p: p["port"])


def required(value, name, minimum=0, maximum=4095):
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"Missing or invalid {name}. Check power, cables and serial access.")
    return value


class Hardware:
    def __init__(self, bus_factory=FeetechBus):
        self.bus_factory = bus_factory
        self.capture = None

    def inspect_bus(self, bus, role):
        motors = []
        for mid, name in JOINT_ID_MAP.items():
            if not bus.ping(mid):
                raise ValueError(f"Motor {mid} ({name.replace('_', ' ')}) did not reply.")
            voltage = required(bus.read_byte(mid, Register.PRESENT_VOLTAGE), "voltage", 1, 255) / 10
            temp = required(bus.read_byte(mid, Register.PRESENT_TEMPERATURE), "temperature", 0, 125)
            error = required(bus.read_byte(mid, Register.STATUS_ERROR), "motor status", 0, 255)
            position = required(bus.read_word(mid, Register.PRESENT_POSITION), "encoder position")
            torque = required(bus.read_byte(mid, Register.TORQUE_ENABLE), "torque state", 0, 1)
            low = required(bus.read_word(mid, Register.MIN_ANGLE_LIMIT), "lower limit")
            high = required(bus.read_word(mid, Register.MAX_ANGLE_LIMIT), "upper limit")
            if low >= high:
                raise ValueError(f"Motor {mid} has invalid firmware limits.")
            motors.append({"id": mid, "name": name, "voltage": voltage, "temperature": temp,
                           "error": error, "position": position, "torque": torque,
                           "low": low, "high": high})
        minimum = 11.5 if role == "follower" else 4.8
        issues = []
        if min(m["voltage"] for m in motors) < minimum:
            issues.append(f"Every motor needs at least {minimum} V. Check the power supply.")
        if max(m["temperature"] for m in motors) > 60:
            issues.append("A motor is above 60 °C. Let the arm cool before continuing.")
        if any(m["error"] for m in motors):
            issues.append("A motor reports an error. Resolve it before continuing.")
        return {"motors": motors, "issues": issues, "passed": not issues, "at": time.time()}

    def inspect(self, port, role):
        bus = self.bus_factory(port=port)
        bus.open()
        try:
            return self.inspect_bus(bus, role)
        finally:
            bus.close()

    def torque(self, bus, enabled):
        failures = []
        for mid in JOINT_ID_MAP:
            try:
                bus.write_byte_verified(mid, Register.TORQUE_ENABLE, int(enabled))
            except Exception:
                if enabled:
                    raise
                failures.append(mid)
        if failures:
            raise ValueError(f"Torque release is unverified on motors {failures}. Support the arm and use its power switch.")

    def begin(self, port, role):
        if self.capture:
            raise ValueError("Calibration is already running.")
        bus = self.bus_factory(port=port)
        bus.open()
        try:
            report = self.inspect_bus(bus, role)
            if not report["passed"]:
                raise ValueError(" ".join(report["issues"]))
            self.torque(bus, False)
            values = {m["id"]: m["position"] for m in report["motors"]}
            self.capture = {"bus": bus, "started": time.monotonic(), "last": values,
                            "minimum": values.copy(), "maximum": values.copy(), "reference": None,
                            "samples": 0, "role": role, "paused_error": ""}
        except Exception:
            bus.close()
            raise
        return self.sample()

    def sample(self):
        cap = self.capture
        if not cap:
            return None
        try:
            if time.monotonic() - cap["started"] > 900:
                raise ValueError("Calibration timed out. Start again when you are ready.")
            if cap["paused_error"]:
                for mid in JOINT_ID_MAP:
                    if cap["bus"].read_byte(mid, Register.TORQUE_ENABLE) != 0:
                        raise ValueError(f"Motor {mid} torque was enabled externally. Calibration cancelled. Support the arm.")
                return self.snapshot()
            values = {}
            for mid, name in JOINT_ID_MAP.items():
                value = required(cap["bus"].read_word(mid, Register.PRESENT_POSITION), "encoder position")
                # Positioning the rest pose is not a range measurement. During
                # the sweep, reject wraparound: profiles require one continuous
                # interval in 0..4095, not an interval spanning the encoder seam.
                if cap["reference"] is not None and abs(value - cap["last"][mid]) > 2048:
                    raise ValueError(f"Motor {mid} ({name.replace('_', ' ')}) crossed its encoder boundary or had a discontinuous reading "
                                     f"({cap['last'][mid]} → {value}). Support the arm and restart calibration with a range that stays away from 0/4095. Do not force a joint.")
                error = required(cap["bus"].read_byte(mid, Register.STATUS_ERROR), f"motor {mid} status", 0, 255)
                if cap["bus"].read_byte(mid, Register.TORQUE_ENABLE) != 0:
                    raise ValueError(f"Motor {mid} ({name.replace('_', ' ')}) torque was enabled externally. Calibration cancelled.")
                if error:
                    voltage = required(cap["bus"].read_byte(mid, Register.PRESENT_VOLTAGE), f"motor {mid} voltage", 1, 255) / 10
                    temperature = required(cap["bus"].read_byte(mid, Register.PRESENT_TEMPERATURE), f"motor {mid} temperature", 0, 125)
                    cap["paused_error"] = (f"Motor {mid} ({name.replace('_', ' ')}) reports status 0x{error:02X} "
                                           f"at {value} ticks, {voltage:.1f} V, {temperature} °C. "
                                           "Measurement paused; your reference and ranges are kept. Support the arm, check power and cables, then recheck. No fault flag is cleared automatically.")
                    logging.getLogger(__name__).warning("Calibration paused: %s", cap["paused_error"])
                    return self.snapshot()
                values[mid] = value
            # Commit only a complete healthy six-motor sample.
            for mid, value in values.items():
                cap["last"][mid] = value
                cap["minimum"][mid] = min(cap["minimum"][mid], value) if cap["reference"] is not None else value
                cap["maximum"][mid] = max(cap["maximum"][mid], value) if cap["reference"] is not None else value
            cap["samples"] += 1
            return self.snapshot()
        except Exception:
            self.cancel()
            raise

    def snapshot(self):
        cap = self.capture
        if not cap:
            return None
        ranges = [{"id": mid, "name": name, "position": cap["last"][mid],
                       "min": cap["minimum"][mid], "max": cap["maximum"][mid],
                       "travel": cap["maximum"][mid] - cap["minimum"][mid]}
                      for mid, name in JOINT_ID_MAP.items()]
        return {"ranges": ranges, "reference_set": cap["reference"] is not None,
                "samples": cap["samples"], "paused_error": cap["paused_error"]}

    def resume(self):
        cap = self.capture
        if not cap or not cap["paused_error"]:
            raise ValueError("There is no paused calibration to recheck.")
        report = self.inspect_bus(cap["bus"], cap["role"])
        if not report["passed"]:
            raise ValueError("Recheck failed: " + " ".join(report["issues"]) + " Measurement remains paused; your ranges are kept.")
        if any(m["torque"] for m in report["motors"]):
            self.cancel()
            raise ValueError("Torque was enabled externally. Calibration cancelled. Support the arm.")
        cap["paused_error"] = ""
        return self.sample()

    def reference(self):
        if not self.capture:
            raise ValueError("Start calibration before recording a reference.")
        if self.capture["paused_error"]:
            raise ValueError("Recheck the paused calibration before recording a reference.")
        # Re-recording explicitly starts a fresh sweep at the new rest pose.
        previous_reference = self.capture["reference"]
        self.capture["reference"] = None
        self.sample()
        if self.capture["paused_error"]:
            self.capture["reference"] = previous_reference
            raise ValueError("A motor reports a fault. Recheck before recording the reference.")
        self.capture["reference"] = self.capture["last"].copy()
        return self.snapshot()

    def finish(self):
        if not self.capture:
            raise ValueError("Start calibration before saving.")
        if self.capture["paused_error"]:
            raise ValueError("Recheck the paused calibration before saving. Your ranges are kept.")
        self.sample()
        cap = self.capture
        if cap["paused_error"]:
            raise ValueError("A motor reports a fault. Recheck before saving; your ranges are kept.")
        if cap["reference"] is None:
            raise ValueError("Record the illustrated rest reference before saving.")
        profile = {}
        for mid, name in JOINT_ID_MAP.items():
            low, high = cap["minimum"][mid], cap["maximum"][mid]
            if high - low < 120:
                raise ValueError(f"Move {name.replace('_', ' ')} through a comfortable range first (at least 120 ticks). Do not force a joint.")
            zero = round(cap["reference"][mid] - CANONICAL_REST_ANGLES[name] / DEGREES_PER_TICK)
            profile[name] = {"id": mid, "drive_mode": 0, "homing_offset": zero - 2047,
                             "range_min": low + 60, "range_max": high - 60}
        return profile

    def cancel(self):
        if self.capture:
            self.capture["bus"].close()
            self.capture = None
