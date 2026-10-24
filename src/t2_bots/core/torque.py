"""
Independent Torque Control and Safe Release Primitives for t2-BOTS Robotics SDK.
Provides dedicated, decoupled functions for Leader and Follower arms.
"""

from typing import Dict, Optional
from t2_bots.core.preflight import HardwarePreflight
from t2_bots_so101.driver.bus import FeetechBus
from t2_bots_so101.driver.registers import Register

def release_arm_torque(port: str, motor_ids: Optional[list] = None) -> Dict[int, int]:
    """
    Explicitly disables holding torque on all actuators on the specified serial port,
    enforces silicon readback verification on every motor, and returns live raw ticks.
    Raises HardwareStateMismatchError if any motor fails to release.
    """
    if motor_ids is None:
        motor_ids = [1, 2, 3, 4, 5, 6]

    bus = FeetechBus(port=port)
    bus.open()
    try:
        from t2_bots.core.safety import TorqueSafetyGuard
        TorqueSafetyGuard.set_and_verify_torque(bus, motor_ids, enabled=False)
        positions = bus.sync_read_positions(motor_ids)
        return positions
    finally:
        bus.close()

def release_leader_torque(port: Optional[str] = None) -> Dict[int, int]:
    """
    Dedicated function: Disables holding torque across all motors on the LEADER arm.
    Guarantees silicon readback verification.
    """
    if port is None:
        pf = HardwarePreflight()
        port, _ = pf.resolve_arms_automatically()

    positions = release_arm_torque(port=port)
    return positions

def release_follower_torque(port: Optional[str] = None) -> Dict[int, int]:
    """
    Dedicated function: Disables holding torque across all motors on the FOLLOWER arm.
    Guarantees silicon readback verification.
    """
    if port is None:
        pf = HardwarePreflight()
        _, port = pf.resolve_arms_automatically()

    positions = release_arm_torque(port=port)
    return positions

def engage_arm_torque(port: str, motor_ids: Optional[list] = None) -> None:
    """Explicitly enables active holding torque with silicon readback verification."""
    if motor_ids is None:
        motor_ids = [1, 2, 3, 4, 5, 6]

    bus = FeetechBus(port=port)
    bus.open()
    try:
        from t2_bots.core.safety import TorqueSafetyGuard
        TorqueSafetyGuard.set_and_verify_torque(bus, motor_ids, enabled=True)
    finally:
        bus.close()
