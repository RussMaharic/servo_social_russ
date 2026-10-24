"""
Zero-Copy Monotonic Timestamp Synchronization Ring Buffer for RL / VLA Datasets.
"""

import time
from collections import deque
from typing import Dict, Any, Optional, List, Tuple

class VisionActionSyncBuffer:
    """
    Synchronizes asynchronous camera frames with high-frequency joint states.
    Emits canonical Physical AI demonstration frames (s_t, I_t, a_t).
    """

    def __init__(self, max_tolerance_ms: float = 8.0, buffer_len: int = 120):
        self.max_tolerance_ns = int(max_tolerance_ms * 1e6)
        self.motor_buffer = deque(maxlen=buffer_len)
        self.camera_buffers: Dict[str, deque] = {}

    def push_state(self, timestamp_ns: int, joints: Dict[str, float], gripper: float) -> None:
        """Pushes a motor state sample into the ring buffer."""
        self.motor_buffer.append((timestamp_ns, joints, gripper))

    def push_image(self, cam_name: str, timestamp_ns: int, frame: Any) -> None:
        """Pushes an image frame from a specific camera."""
        if cam_name not in self.camera_buffers:
            self.camera_buffers[cam_name] = deque(maxlen=60)
        self.camera_buffers[cam_name].append((timestamp_ns, frame))

    def get_synced_episode_frame(self) -> Optional[Dict[str, Any]]:
        """
        Finds the latest motor sample and pairs with closest image frames within tolerance.
        Returns canonical Physical AI observation dictionary.
        """
        if not self.motor_buffer:
            return None

        m_ts, joints, grip = self.motor_buffer[-1]
        synced_cams = {}

        for cam_name, cam_buf in self.camera_buffers.items():
            if not cam_buf:
                continue
            # Find closest frame in time
            best_frame = None
            min_diff = float("inf")
            for c_ts, img in cam_buf:
                diff = abs(c_ts - m_ts)
                if diff < min_diff and diff <= self.max_tolerance_ns:
                    min_diff = diff
                    best_frame = img
            if best_frame is not None:
                synced_cams[cam_name] = best_frame

        return {
            "timestamp": m_ts / 1e9,
            "observation.state": joints,
            "observation.gripper": grip,
            "observation.images": synced_cams,
        }
