"""
Dynamic Named Pose and Coordinate Persistence Engine for t2-BOTS Robotics SDK.
Allows operators to capture, persist, manage, and recall custom robot postures.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

DEFAULT_POSE_DIR = Path.home() / ".config" / "t2_bots" / "poses"

@dataclass
class NamedPose:
    name: str
    joints: Dict[str, float]
    gripper: float
    description: str = ""
    timestamp: float = 0.0

class PoseManager:
    """Manages persistent custom postures keyed to specific robot hardware instances."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or DEFAULT_POSE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_file(self, robot_id: str) -> Path:
        sanitized = robot_id.replace("/", "_").replace("\\", "_")
        return self.storage_dir / f"{sanitized}_poses.json"

    def load_poses(self, robot_id: str) -> Dict[str, Dict[str, Any]]:
        """Loads all custom poses for a specific robot identifier."""
        filepath = self._get_file(robot_id)
        if not filepath.exists():
            return {}
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_pose(
        self,
        robot_id: str,
        name: str,
        joints: Dict[str, float],
        gripper: float,
        description: str = "",
    ) -> Dict[str, Any]:
        """Saves or updates a named pose atomically on disk."""
        import time
        poses = self.load_poses(robot_id)
        pose_data = {
            "name": name,
            "joints": {k: round(v, 2) for k, v in joints.items()},
            "gripper": round(gripper, 3),
            "description": description,
            "updated_at": time.time(),
        }
        poses[name] = pose_data
        filepath = self._get_file(robot_id)
        with open(filepath, "w") as f:
            json.dump(poses, f, indent=2)
        return pose_data

    def get_pose(self, robot_id: str, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific named pose."""
        poses = self.load_poses(robot_id)
        return poses.get(name)

    def delete_pose(self, robot_id: str, name: str) -> bool:
        """Deletes a custom pose by name."""
        poses = self.load_poses(robot_id)
        if name in poses:
            del poses[name]
            filepath = self._get_file(robot_id)
            with open(filepath, "w") as f:
                json.dump(poses, f, indent=2)
            return True
        return False
