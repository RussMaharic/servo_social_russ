"""
System-Specific Hardware Rig Configuration & Profile Persistence.

Locks in physical USB serial descriptors, dynamic TTY ports, calibrated home
joint angles and raw encoder ticks, network IPs, and safety bounds into an
authoritative rig profile at `~/.config/t2_bots/rig_config.json`.
"""

from __future__ import annotations

import json
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path.home() / ".config" / "t2_bots"
RIG_CONFIG_FILE = CONFIG_DIR / "rig_config.json"
HARDWARE_REGISTRY_FILE = CONFIG_DIR / "hardware_registry.json"


def get_local_lan_ip() -> str:
    """Discovers the local primary LAN IP interface."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually transmit packets, queries OS routing table
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class RigConfigManager:
    """Manages system-specific hardware rig profiles and environment persistence."""

    def __init__(self, config_file: Optional[Path] = None):
        self.config_file = Path(config_file) if config_file else RIG_CONFIG_FILE

    def exists(self) -> bool:
        return self.config_file.exists()

    def load(self) -> Dict[str, Any]:
        """Loads the persistent rig configuration."""
        if not self.config_file.exists():
            raise FileNotFoundError(f"Rig configuration not found at {self.config_file}")
        with open(self.config_file, "r") as f:
            return json.load(f)

    def save(self, data: Dict[str, Any]) -> Path:
        """Atomically saves the rig configuration to disk."""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.config_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_file, self.config_file)

        # Also synchronize hardware_registry.json for preflight compatibility
        if "arms" in data:
            registry = {}
            for role in ["leader", "follower"]:
                if role in data["arms"] and "serial_number" in data["arms"][role]:
                    registry[role] = data["arms"][role]["serial_number"]
            if registry:
                reg_file = self.config_file.parent / "hardware_registry.json"
                with open(reg_file, "w") as f:
                    json.dump(registry, f, indent=2)

        return self.config_file

    def capture_live_rig(self, rig_name: str = "SO101 Dual-Arm Workstation") -> Dict[str, Any]:
        """
        Interrogates connected physical hardware, USB serial descriptors,
        saved custom poses, and operating environment to generate an
        authoritative configuration profile for this exact machine.
        """
        from t2_bots.core.poses import PoseManager
        from t2_bots.core.preflight import HardwarePreflight
        from t2_bots_so101.driver.bus import FeetechBus
        from t2_bots_so101.driver.registers import Register

        pf = HardwarePreflight()
        scan = pf.scan_ports()

        l_port = None
        f_port = None
        try:
            l_port, f_port = pf.resolve_arms_automatically()
        except Exception:
            # Single-station distributed rig resolution
            f_sn = pf.registry.get("follower", "5C82107826")
            l_sn = pf.registry.get("leader", "5C82109414")
            for dev, meta in scan.items():
                sn = meta.get("serial_number", "")
                if sn and f_sn in sn:
                    f_port = dev
                elif sn and l_sn in sn:
                    l_port = dev
            if not l_port and not f_port:
                if sys.platform.startswith("darwin"):
                    try:
                        f_port = pf.resolve_single_arm("follower")
                    except Exception:
                        pass
                else:
                    try:
                        l_port = pf.resolve_single_arm("leader")
                    except Exception:
                        pass

        pm = PoseManager()
        follower_poses = pm.load_poses("so101_follower")
        leader_poses = pm.load_poses("so101_leader_leader")
        if not leader_poses:
            leader_poses = pm.load_poses("so101_leader")

        f_home = follower_poses.get("home", {})
        l_home = leader_poses.get("home", {})

        # Live encoder tick readback with manifest fallback for active daemons & single stations
        def get_arm_live_info(port: Optional[str], role: str) -> Dict[str, Any]:
            if not port:
                manifest_file = Path.home() / ".config" / "t2_bots" / "calibration" / f"so101_{role}_manifest.json"
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r") as mf:
                            m_data = json.load(mf)
                            ticks = {str(j_meta["id"]): j_meta["safe_rest_tick"] for j_meta in m_data.get("joints", {}).values()}
                            return {
                                "online": True,
                                "status": "manifest_cached",
                                "bus_voltage": m_data.get("bus_voltage_v", 12.0),
                                "encoder_ticks": ticks,
                            }
                    except Exception:
                        pass
                return {"online": False, "status": "remote_distributed_station"}
            try:
                bus = FeetechBus(port=port)
                bus.open()
                ticks = {}
                torques = {}
                for m in [1, 2, 3, 4, 5, 6]:
                    t = bus.read_byte(m, Register.TORQUE_ENABLE)
                    p = bus.read_word(m, Register.PRESENT_POSITION)
                    torques[m] = t
                    ticks[m] = p
                voltage = bus.read_byte(1, Register.PRESENT_VOLTAGE) / 10.0
                bus.close()
                return {
                    "online": True,
                    "bus_voltage": voltage,
                    "torque_states": torques,
                    "encoder_ticks": ticks,
                }
            except Exception as e:
                # If serial bus is held by an active peer daemon, read from verified manifest
                manifest_file = Path.home() / ".config" / "t2_bots" / "calibration" / f"so101_{role}_manifest.json"
                if manifest_file.exists():
                    try:
                        with open(manifest_file, "r") as mf:
                            m_data = json.load(mf)
                            ticks = {str(j_meta["id"]): j_meta["safe_rest_tick"] for j_meta in m_data.get("joints", {}).values()}
                            return {
                                "online": True,
                                "status": "active_daemon_cached",
                                "bus_voltage": m_data.get("bus_voltage_v", 12.0),
                                "encoder_ticks": ticks,
                            }
                    except Exception:
                        pass
                return {"online": False, "error": str(e)}

        leader_live = get_arm_live_info(l_port, "leader")
        follower_live = get_arm_live_info(f_port, "follower")

        profile = {
            "rig_name": rig_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "host": {
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "architecture": platform.machine(),
                "python": sys.executable,
                "lan_ip": get_local_lan_ip(),
            },
            "network": {
                "default_listen_port": 8765,
                "gateway_api_port": 8000,
                "preferred_ip": get_local_lan_ip(),
            },
            "safety": {
                "min_bus_voltage": 10.5,
                "max_bus_voltage": 14.0,
                "deadman_timeout_s": 0.2,
                "soft_start_duration_s": 1.2,
                "loop_rate_hz": 50,
            },
            "arms": {
                "leader": {
                    "role": "leader",
                    "driver": "so101_leader",
                    "serial_number": scan.get("leader", {}).get("serial_number", "5C82109414"),
                    "port": l_port,
                    "baudrate": 1_000_000,
                    "motor_ids": [1, 2, 3, 4, 5, 6],
                    "home_pose": {
                        "joints": l_home.get("joints", {}),
                        "gripper": l_home.get("gripper", 0.0),
                        "raw_ticks": leader_live.get("encoder_ticks", {}),
                    },
                    "live_status": leader_live,
                },
                "follower": {
                    "role": "follower",
                    "driver": "so101",
                    "serial_number": scan.get("follower", {}).get("serial_number", "5C82107826"),
                    "port": f_port,
                    "baudrate": 1_000_000,
                    "motor_ids": [1, 2, 3, 4, 5, 6],
                    "home_pose": {
                        "joints": f_home.get("joints", {}),
                        "gripper": f_home.get("gripper", 0.0),
                        "raw_ticks": follower_live.get("encoder_ticks", {}),
                    },
                    "live_status": follower_live,
                },
            },
        }

        self.save(profile)
        return profile
