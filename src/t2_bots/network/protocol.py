"""
Microsecond-Synchronized Binary / JSON Protocol Framing for Internet Teleoperation.
"""

import time
import json
import zlib
from dataclasses import dataclass, asdict
from typing import Dict, Optional

@dataclass
class TeleopPacket:
    seq: int
    timestamp_ns: int
    role: str
    joints: Dict[str, float]
    gripper: float
    raw_ticks: Optional[Dict[str, int]] = None
    velocities: Optional[Dict[str, float]] = None
    bus_voltage: Optional[float] = None
    max_temp: Optional[int] = None
    status_error: Optional[int] = None
    norm_joints: Optional[Dict[str, float]] = None
    norm_gripper: Optional[float] = None
    operator_state: str = "active"
    crc: int = 0

    def serialize(self) -> str:
        data = {
            "seq": self.seq,
            "ts": self.timestamp_ns,
            "role": self.role,
            "q": {k: round(v, 2) for k, v in self.joints.items()},
            "g": round(self.gripper, 3),
        }
        if self.norm_joints:
            data["nq"] = {k: round(v, 4) for k, v in self.norm_joints.items()}
        if self.norm_gripper is not None:
            data["ng"] = round(self.norm_gripper, 4)
        if self.raw_ticks:
            data["raw"] = self.raw_ticks
        if self.velocities:
            data["v"] = {k: round(v, 1) for k, v in self.velocities.items()}
        if self.bus_voltage is not None:
            data["v_bus"] = round(self.bus_voltage, 1)
        if self.max_temp is not None:
            data["temp"] = self.max_temp
        if self.status_error is not None:
            data["err"] = self.status_error
        if self.operator_state != "active":
            data["op_state"] = self.operator_state

        raw_bytes = json.dumps(data, sort_keys=True).encode("utf-8")
        self.crc = zlib.crc32(raw_bytes)
        data["crc"] = self.crc
        return json.dumps(data)

    @classmethod
    def deserialize(cls, payload: str) -> "TeleopPacket":
        data = json.loads(payload)
        chk = data.pop("crc", 0)
        calc = zlib.crc32(json.dumps(data, sort_keys=True).encode("utf-8"))
        if chk != calc and chk != 0:
            raise ValueError(f"Packet CRC mismatch: {chk} != {calc}")
        return cls(
            seq=data["seq"],
            timestamp_ns=data["ts"],
            role=data["role"],
            joints=data["q"],
            gripper=data["g"],
            raw_ticks=data.get("raw"),
            velocities=data.get("v"),
            bus_voltage=data.get("v_bus"),
            max_temp=data.get("temp"),
            status_error=data.get("err"),
            norm_joints=data.get("nq"),
            norm_gripper=data.get("ng"),
            operator_state=data.get("op_state", "active"),
            crc=chk,
        )

    def compute_rtt_ms(self) -> float:
        """Calculates one-way transmission latency in milliseconds."""
        now_ns = time.time_ns()
        return (now_ns - self.timestamp_ns) / 1e6
