"""
t2-BOTS: Universal Physical AI Hardware Abstraction Layer & Robotics SDK.
"""

from t2_bots.core.base import BaseRobot, RobotManipulator, RobotRole
from t2_bots.core.schema import RobotState, RobotAction, ObservationFrame
from t2_bots.core.registry import get_robot, list_available_drivers
from t2_bots.core.certification import (
    HardwareCertificate,
    CertificationEngine,
    CertificationError,
    verify_certificate,
)

__version__ = "0.3.1"
__all__ = [
    "BaseRobot",
    "RobotManipulator",
    "RobotRole",
    "RobotState",
    "RobotAction",
    "ObservationFrame",
    "get_robot",
    "list_available_drivers",
    "HardwareCertificate",
    "CertificationEngine",
    "CertificationError",
    "verify_certificate",
]
