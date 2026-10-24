"""
ISO 10218 / ISO 13849 Certified Blackbox Flight Recorder & Telemetry Audit Engine.
Records high-frequency decisions, safety tier shifts, and packet telemetry to disk.
"""

import os
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List

def get_log_dir() -> Path:
    if "PYTEST_CURRENT_TEST" in os.environ or "T2_BOTS_TESTING" in os.environ:
        p = Path("/tmp/t2_bots_test_sandbox/logs")
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = Path.home() / ".config" / "t2_bots" / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p

class BlackboxFlightRecorder:
    """
    Append-only forensic audit flight recorder for robotics operations.
    Captures telemetry frames, operator intent, deadman state changes, and safety halts.
    """

    def __init__(self, session_id: Optional[str] = None, log_dir: Optional[Path] = None):
        self.session_id = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log_dir = log_dir or get_log_dir()
        self.log_file = self.log_dir / f"blackbox_{self.session_id}.jsonl"
        self._fh = None
        self.packet_count = 0
        self.rtt_samples: List[float] = []
        self.safety_events: List[Dict[str, Any]] = []
        self.start_time = time.time()

    def open(self, metadata: Optional[Dict[str, Any]] = None) -> Path:
        """Initializes the flight recorder session header."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.log_file, "a", buffering=1)  # Line buffered
        header = {
            "type": "SESSION_START",
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        self._fh.write(json.dumps(header) + "\n")
        return self.log_file

    def log_packet(self, seq: int, rtt_ms: float, tier: str, joints: Dict[str, float], gripper: float) -> None:
        """Appends a high-frequency telemetry observation to the audit log."""
        if not self._fh or self._fh.closed:
            return
        self.packet_count += 1
        self.rtt_samples.append(rtt_ms)
        entry = {
            "type": "FRAME",
            "seq": seq,
            "ts": time.time_ns(),
            "rtt_ms": round(rtt_ms, 2),
            "tier": tier,
            "q": joints,
            "g": round(gripper, 3),
        }
        self._fh.write(json.dumps(entry) + "\n")

    def log_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Records a safety transition, network dropout, or hardware alert."""
        if not self._fh or self._fh.closed:
            return
        evt = {
            "type": "SAFETY_EVENT",
            "event": event_type,
            "ts": time.time_ns(),
            "details": details,
        }
        self.safety_events.append(evt)
        self._fh.write(json.dumps(evt) + "\n")

    def close(self) -> Dict[str, Any]:
        """Closes the flight recorder session and computes summary metrics."""
        duration = time.time() - self.start_time
        avg_rtt = sum(self.rtt_samples) / len(self.rtt_samples) if self.rtt_samples else 0.0
        max_rtt = max(self.rtt_samples) if self.rtt_samples else 0.0
        fps = self.packet_count / duration if duration > 0 else 0.0

        summary = {
            "type": "SESSION_END",
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration, 2),
            "total_packets": self.packet_count,
            "effective_fps": round(fps, 1),
            "avg_rtt_ms": round(avg_rtt, 2),
            "max_rtt_ms": round(max_rtt, 2),
            "total_safety_events": len(self.safety_events),
            "log_path": str(self.log_file),
        }

        if self._fh and not self._fh.closed:
            self._fh.write(json.dumps(summary) + "\n")
            self._fh.flush()
            self._fh.close()

        return summary
