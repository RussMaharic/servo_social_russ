"""
Domain Schemas and Data Transfer Objects for Physical AI Integration.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time

@dataclass
class RobotState:
    """Raw joint telemetry directly from hardware bus."""
    timestamp: float = field(default_factory=time.time)
    positions_raw: Dict[str, int] = field(default_factory=dict)
    positions_deg: Dict[str, float] = field(default_factory=dict)
    voltages: Dict[str, float] = field(default_factory=dict)
    temperatures: Dict[str, float] = field(default_factory=dict)
    torque_enabled: bool = False
    bus_latency_ms: float = 0.0

@dataclass
class ObservationFrame:
    """Standardized Physical AI Observation Frame."""
    timestamp: float = field(default_factory=time.time)
    joint_positions: Dict[str, float] = field(default_factory=dict)
    gripper_aperture: float = 0.0  # 0.0 (closed) to 1.0 (open)
    latency_ms: float = 0.0

    def to_vector(self, joint_order: List[str]) -> List[float]:
        """Converts observation to flat vector for neural policy consumption."""
        vec = [self.joint_positions.get(j, 0.0) for j in joint_order]
        vec.append(self.gripper_aperture)
        return vec

@dataclass
class RobotAction:
    """Target Action emitted by Physical AI policy or Teleoperator."""
    timestamp: float = field(default_factory=time.time)
    target_positions: Dict[str, float] = field(default_factory=dict)
    target_gripper: Optional[float] = None
    duration_s: float = 0.02  # Default 50 Hz control step

    @classmethod
    def from_vector(cls, vector: List[float], joint_order: List[str]) -> "RobotAction":
        """Instantiates action from a flat policy output vector."""
        targets = {name: vector[i] for i, name in enumerate(joint_order) if i < len(vector) - 1}
        gripper = vector[-1] if len(vector) > len(joint_order) else None
        return cls(target_positions=targets, target_gripper=gripper)
