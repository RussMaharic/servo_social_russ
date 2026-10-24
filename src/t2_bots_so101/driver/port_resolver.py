"""
Cross-Platform USB Serial Port Discovery and Tactile Disambiguator.
"""

import sys
import glob
import time
from typing import List, Dict, Optional
import serial.tools.list_ports

def list_candidate_ports() -> List[str]:
    """Finds all candidate USB-serial adapters on the host machine."""
    ports = []
    if sys.platform.startswith("darwin"):
        ports = glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/tty.usbserial*")
    elif sys.platform.startswith("linux"):
        ports = glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*")
    elif sys.platform.startswith("win"):
        ports = [p.device for p in serial.tools.list_ports.comports()]
    else:
        ports = [p.device for p in serial.tools.list_ports.comports()]
    return sorted(list(set(ports)))

def resolve_ports_via_tactile_wiggle(timeout: float = 20.0) -> Dict[str, str]:
    """
    Listens across all candidate USB ports simultaneously.
    When the user physically wiggles an arm, assigns that port node.
    """
    from t2_bots_so101.driver.bus import FeetechBus
    candidates = list_candidate_ports()
    if len(candidates) < 2:
        return {
            "leader": candidates[0] if len(candidates) > 0 else "",
            "follower": candidates[1] if len(candidates) > 1 else "",
        }

    buses = {}
    baselines = {}
    for p in candidates:
        try:
            b = FeetechBus(port=p)
            b.open()
            buses[p] = b
            # Read Joint 1 (Base Pan)
            baselines[p] = b.read_word(1, 0x38, retries=1)
        except Exception:
            pass

    print("👉 Tactile Disambiguation Active: Gently wiggle the LEADER arm now...")
    leader_port = None
    start = time.time()
    while time.time() - start < timeout and leader_port is None:
        for p, b in buses.items():
            try:
                curr = b.read_word(1, 0x38, retries=1)
                if abs(curr - baselines[p]) > 30:  # ~2.6 degrees motion
                    leader_port = p
                    break
            except Exception:
                pass
        time.sleep(0.05)

    for b in buses.values():
        b.close()

    if leader_port is None:
        # Fallback to order
        return {"leader": candidates[0], "follower": candidates[1]}

    remaining = [p for p in candidates if p != leader_port]
    follower_port = remaining[0] if remaining else candidates[0]
    return {"leader": leader_port, "follower": follower_port}
