"""
Base Abstract Classes for t2-BOTS Hardware Abstraction Layer.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any
from t2_bots.core.schema import RobotState, RobotAction, ObservationFrame

class RobotRole(str, Enum):
    FOLLOWER = "follower"
    LEADER = "leader"
    STANDALONE = "standalone"

class BaseRobot(ABC):
    """Abstract base class for all physical robotic embodiments."""

    def __init__(self, name: str, role: RobotRole = RobotRole.FOLLOWER, port: Optional[str] = None):
        self.name = name
        self.role = role
        self.port = port
        self.is_connected = False

    @abstractmethod
    def connect(self) -> None:
        """Establishes hardware communication channel."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Safely closes connection and disables torque."""
        pass

    @abstractmethod
    def ping(self) -> Dict[str, bool]:
        """Pings all individual actuators/sensors on the robot."""
        pass

    @abstractmethod
    def get_state(self) -> RobotState:
        """Returns the current raw and engineering state."""
        pass

class RobotManipulator(BaseRobot, ABC):
    """Abstract base class for 6-DOF and serial arm manipulators."""

    @abstractmethod
    def get_observation(self) -> ObservationFrame:
        """
        Returns normalized state observation for Physical AI policy consumption.
        Joint angles in degrees [-180..180] or radians, and gripper [0..100%].
        """
        pass

    @abstractmethod
    def send_action(self, action: RobotAction) -> None:
        """Sends closed-loop position/torque targets to actuators."""
        pass

    @abstractmethod
    def set_torque(self, enabled: bool) -> None:
        """Enables or disables active holding torque across all joints."""
        pass

    @abstractmethod
    def run_commissioning(self) -> Dict[str, Any]:
        """Runs interactive 6-phase hardware isolation, homing, and range calibration."""
        pass

    @property
    def standard_poses(self) -> Dict[str, Dict[str, float]]:
        """Dictionary of standard preset named postures."""
        return {
            "zero": {
                "shoulder_pan": 0.0,
                "shoulder_lift": 0.0,
                "elbow_flex": 0.0,
                "wrist_flex": 0.0,
                "wrist_roll": 0.0,
                "gripper": 0.0,
            }
        }

    def _get_robot_id(self) -> str:
        name = getattr(self, "name", "robot")
        role = getattr(self, "role", None)
        role_val = role.value if hasattr(role, "value") else str(role or "arm")
        return f"{name}_{role_val}"

    def capture_pose(self, name: str, description: str = "") -> Dict[str, Any]:
        """
        Captures the robot's current physical joint angles and gripper aperture,
        and saves them under the given name in persistent storage.
        """
        from t2_bots.core.poses import PoseManager
        obs = self.get_observation()
        pm = PoseManager()
        robot_id = self._get_robot_id()
        saved = pm.save_pose(
            robot_id=robot_id,
            name=name,
            joints=obs.joint_positions,
            gripper=obs.gripper_aperture,
            description=description,
        )
        return saved

    def list_poses(self) -> Dict[str, Dict[str, Any]]:
        """
        Lists all available postures, merging custom user saved poses
        with built-in embodiment presets.
        """
        from t2_bots.core.poses import PoseManager
        combined = {}
        # 1. Presets
        for k, v in self.standard_poses.items():
            combined[k] = {"name": k, "joints": v, "gripper": v.get("gripper", 0.0), "type": "preset"}
        # 2. Custom user poses
        pm = PoseManager()
        robot_id = self._get_robot_id()
        custom = pm.load_poses(robot_id)
        for k, v in custom.items():
            v_copy = v.copy()
            v_copy["type"] = "custom"
            combined[k] = v_copy
        return combined

    def delete_pose(self, name: str) -> bool:
        """Deletes a custom saved pose from persistent storage."""
        from t2_bots.core.poses import PoseManager
        pm = PoseManager()
        robot_id = self._get_robot_id()
        return pm.delete_pose(robot_id, name)

    def goto_pose(self, name: str, duration_s: float = 2.5, fps: int = 50) -> None:
        """
        Smoothly interpolates the manipulator to any custom or preset named pose
        using a cosine S-curve trajectory.
        """
        import math
        import time

        available = self.list_poses()
        if name not in available:
            raise ValueError(f"Unknown pose '{name}'. Available: {list(available.keys())}")

        target_data = available[name]
        target_dict = target_data.get("joints", target_data)
        target_grip = target_data.get("gripper", 0.0)

        obs = self.get_observation()
        current_joints = obs.joint_positions
        start_grip = obs.gripper_aperture

        steps = max(1, int(duration_s * fps))
        dt = 1.0 / float(fps)

        self.set_torque(True)
        for i in range(1, steps + 1):
            t = float(i) / float(steps)
            smooth_s = (1.0 - math.cos(t * math.pi)) / 2.0  # Cosine S-curve

            interp_joints = {}
            for k in target_dict.keys():
                if k == "gripper":
                    continue
                q0 = current_joints.get(k, 0.0)
                q1 = target_dict[k]
                interp_joints[k] = q0 + smooth_s * (q1 - q0)

            interp_grip = start_grip + smooth_s * (target_grip - start_grip)
            action = RobotAction(target_positions=interp_joints, target_gripper=interp_grip)
            self.send_action(action)
            time.sleep(dt)

    def go_home(self, pose: str = "rest", duration_s: float = 2.5, fps: int = 50) -> None:
        """Convenience alias to navigate to home or rest posture."""
        self.goto_pose(name=pose, duration_s=duration_s, fps=fps)
