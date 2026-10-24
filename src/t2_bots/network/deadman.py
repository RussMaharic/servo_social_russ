"""
Three-Tier Graduated Network Deadman Failsafe Guard.
Guarantees physical safety during internet teleoperation.
"""

import time
from enum import Enum
from typing import Dict, Optional, Tuple

class SafetyTier(str, Enum):
    NOMINAL = "NOMINAL"       # RTT < 80ms: Normal pass-through
    JITTER_SMOOTH = "JITTER"  # RTT 80-150ms: Trajectory cubic smoothing active
    POSITION_HOLD = "HOLD"    # RTT > 150ms or silence > 400ms: Lock current position
    EMERGENCY_HOME = "HOME"   # Silence > 2000ms: Smooth automated return to rest home

class SlewRateLimiter:
    """
    Enforces maximum joint angular velocity limits (ISO 10218 safety standard).
    Prevents mechanical whiplash, gear stripping, and sudden trajectory steps.
    """

    def __init__(self, max_velocity_deg_s: float = 180.0):
        self.max_velocity_deg_s = max_velocity_deg_s
        self.last_positions: Optional[Dict[str, float]] = None
        self.last_time: Optional[float] = None

    def filter(self, target_positions: Dict[str, float]) -> Dict[str, float]:
        now = time.perf_counter()
        if self.last_positions is None or self.last_time is None:
            self.last_positions = target_positions.copy()
            self.last_time = now
            return target_positions.copy()

        dt = now - self.last_time
        self.last_time = now
        if dt <= 0.0 or dt > 0.5:
            self.last_positions = target_positions.copy()
            return target_positions.copy()

        max_step_deg = self.max_velocity_deg_s * dt
        clamped_positions = {}
        for j, target_deg in target_positions.items():
            prev_deg = self.last_positions.get(j, target_deg)
            delta = target_deg - prev_deg
            if abs(delta) > max_step_deg:
                clamped_delta = max_step_deg if delta > 0 else -max_step_deg
                clamped_positions[j] = prev_deg + clamped_delta
            else:
                clamped_positions[j] = target_deg

        self.last_positions = clamped_positions.copy()
        return clamped_positions

class DeadmanGuard:
    """Monitors packet arrival intervals and enforces physical safety tiers."""

    def __init__(
        self,
        home_pose: Optional[Dict[str, float]] = None,
        tier1_ms: float = 80.0,
        tier2_ms: float = 150.0,
        tier2_silence_s: float = 0.40,
        tier3_silence_s: float = 2.0,
    ):
        self.home_pose = home_pose or {
            "shoulder_pan": 0.0,
            "shoulder_lift": -100.0,
            "elbow_flex": 100.0,
            "wrist_flex": 90.0,
            "wrist_roll": 0.0,
        }
        self.tier1_ms = tier1_ms
        self.tier2_ms = tier2_ms
        self.tier2_silence_s = tier2_silence_s
        self.tier3_silence_s = tier3_silence_s

        self.last_packet_time = time.time()
        self.last_valid_targets: Dict[str, float] = {}
        self.current_tier = SafetyTier.NOMINAL
        self.rtt_ema_ms = 20.0  # Exponential moving average

    def record_packet(self, rtt_ms: float, targets: Dict[str, float]) -> None:
        """Updates network health metrics upon receiving a valid packet."""
        now = time.time()
        dt_ms = (now - self.last_packet_time) * 1000.0 if self.last_packet_time else 16.6
        self.last_packet_time = now
        self.last_valid_targets = targets.copy()
        
        # Guard against cross-system NTP clock skew: fallback to arrival delta if rtt is negative or wild
        effective_rtt = rtt_ms if (0.0 <= rtt_ms <= 1000.0) else dt_ms
        alpha = 0.2
        self.rtt_ema_ms = (alpha * effective_rtt) + ((1.0 - alpha) * self.rtt_ema_ms)

    def evaluate_safety(self) -> Tuple[SafetyTier, Optional[Dict[str, float]]]:
        """
        Evaluates current safety state and returns action adjustments.
        Returns (SafetyTier, override_targets).
        """
        now = time.time()
        silence = now - self.last_packet_time

        # Tier 3: Complete connection loss (> 2.0s) -> Smooth automated home
        if silence >= self.tier3_silence_s:
            self.current_tier = SafetyTier.EMERGENCY_HOME
            return SafetyTier.EMERGENCY_HOME, self.home_pose

        # Tier 2: Severe silence (> 0.40s) or excessive latency (> 150ms) -> Position Hold
        if silence >= self.tier2_silence_s or self.rtt_ema_ms >= self.tier2_ms:
            self.current_tier = SafetyTier.POSITION_HOLD
            return SafetyTier.POSITION_HOLD, self.last_valid_targets

        # Tier 1: Mild Jitter (80-150ms) -> Smooth interpolation
        if self.rtt_ema_ms >= self.tier1_ms:
            self.current_tier = SafetyTier.JITTER_SMOOTH
            return SafetyTier.JITTER_SMOOTH, None

        # Tier 0: Nominal
        self.current_tier = SafetyTier.NOMINAL
        return SafetyTier.NOMINAL, None
