"""
SDK-Native Dual-Arm Calibration & Kinematic Synchronization Engine.

Eliminates zero-point disparity by establishing a shared physical reference frame
derived from the hardware rig's verified home ticks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

def get_config_dir() -> Path:
    import os
    if "PYTEST_CURRENT_TEST" in os.environ or "T2_BOTS_TESTING" in os.environ:
        p = Path("/tmp/t2_bots_test_sandbox/config")
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.home() / ".config" / "t2_bots"

def get_calib_dir() -> Path:
    import os
    if "PYTEST_CURRENT_TEST" in os.environ or "T2_BOTS_TESTING" in os.environ:
        p = Path("/tmp/t2_bots_test_sandbox/calibration")
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.home() / ".config" / "t2_bots" / "calibration"

def get_lerobot_calib_dir() -> Path:
    import os
    if "PYTEST_CURRENT_TEST" in os.environ or "T2_BOTS_TESTING" in os.environ:
        p = Path("/tmp/t2_bots_test_sandbox/lerobot_calibration")
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path.home() / ".cache" / "huggingface" / "lerobot" / "calibration"

CONFIG_DIR = get_config_dir()
CALIB_DIR = get_calib_dir()
LEROBOT_CALIB_DIR = get_lerobot_calib_dir()

# Standard joint order and canonical angles for the resting reference posture
CANONICAL_REST_ANGLES = {
    "shoulder_pan": 0.0,
    "shoulder_lift": -90.0,
    "elbow_flex": 90.0,
    "wrist_flex": 90.0,
    "wrist_roll": 0.0,
    "gripper": 0.0,
}

JOINT_ID_MAP = {
    1: "shoulder_pan",
    2: "shoulder_lift",
    3: "elbow_flex",
    4: "wrist_flex",
    5: "wrist_roll",
    6: "gripper",
}

TICKS_PER_REV = 4096.0
DEGREES_PER_TICK = 360.0 / TICKS_PER_REV  # ~0.08789° per tick


class ArmSynchronizer:
    """Computes and synchronizes kinematic calibration tables across dual arms."""

    def __init__(self, rig_config_file: Optional[Path] = None, calib_dir: Optional[Path] = None):
        from t2_bots.core.config import RigConfigManager
        self.cm = RigConfigManager(config_file=rig_config_file)
        self.calib_dir = calib_dir or CALIB_DIR

    def sync_from_home_pose(
        self,
        reference_angles: Optional[Dict[str, float]] = None,
        update_lerobot_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Derives identical zero-angle kinematic centers for both Leader and Follower
        using their verified physical home posture encoder ticks.
        """
        if not self.cm.exists():
            raise FileNotFoundError("Rig configuration not found. Run 't2-bots config save' first.")

        rig = self.cm.load()
        l_ticks = rig["arms"]["leader"]["home_pose"].get("raw_ticks", {})
        f_ticks = rig["arms"]["follower"]["home_pose"].get("raw_ticks", {})

        if not l_ticks or not f_ticks:
            raise ValueError("Home raw ticks missing from rig profile. Re-capture home poses.")

        ref_angles = reference_angles or CANONICAL_REST_ANGLES

        def build_calibration(raw_ticks_dict: Dict[str, int], arm_role: str) -> Dict[str, Any]:
            calib = {}
            for m_id, j_name in JOINT_ID_MAP.items():
                m_str = str(m_id)
                tick = int(raw_ticks_dict.get(m_str, raw_ticks_dict.get(m_id, 2047)))
                target_deg = ref_angles.get(j_name, 0.0)

                if j_name == "gripper":
                    # Gripper normalized stroke
                    calib[j_name] = {
                        "id": m_id,
                        "drive_mode": 0,
                        "homing_offset": 0,
                        "range_min": min(tick, 1600),
                        "range_max": max(tick + 1400, 3200),
                    }
                else:
                    # zero_tick is the tick where joint degree is 0.0°
                    # deg = (tick - zero_tick) * DEGREES_PER_TICK
                    # zero_tick = tick - (deg / DEGREES_PER_TICK)
                    zero_tick = int(round(tick - (target_deg / DEGREES_PER_TICK)))
                    # homing_offset relative to raw center (2047)
                    homing_offset = zero_tick - 2047
                    calib[j_name] = {
                        "id": m_id,
                        "drive_mode": 0,
                        "homing_offset": homing_offset,
                        "range_min": max(0, zero_tick - 1800),
                        "range_max": min(4095, zero_tick + 1800),
                    }
            return calib

        l_calib = build_calibration(l_ticks, "leader")
        f_calib = build_calibration(f_ticks, "follower")

        # Save to SDK native config directory
        self.calib_dir.mkdir(parents=True, exist_ok=True)
        l_path = self.calib_dir / "so101_leader.json"
        f_path = self.calib_dir / "so101_follower.json"

        with open(l_path, "w") as f:
            json.dump(l_calib, f, indent=2)
        with open(f_path, "w") as f:
            json.dump(f_calib, f, indent=2)

        # Synchronize with LeRobot cache if requested
        if update_lerobot_cache:
            l_lr_path = LEROBOT_CALIB_DIR / "teleoperators" / "so_leader" / "None.json"
            f_lr_path = LEROBOT_CALIB_DIR / "robots" / "so_follower" / "None.json"
            l_lr_path.parent.mkdir(parents=True, exist_ok=True)
            f_lr_path.parent.mkdir(parents=True, exist_ok=True)
            with open(l_lr_path, "w") as f:
                json.dump(l_calib, f, indent=2)
            with open(f_lr_path, "w") as f:
                json.dump(f_calib, f, indent=2)

        return {
            "leader_calibration": l_calib,
            "follower_calibration": f_calib,
            "paths": {
                "leader": str(l_path),
                "follower": str(f_path),
            },
        }


SO101_HOMING_DIAGRAM = r"""
       ╭─────┬────────────────────┬──────╮ ◉╲═════╗   ← moveable claw
       │     │      forearm       │  ▤▤  │╤══╲════╝   ← fixed claw
       ╰┬───┬┴────────────────────┴──────┴┴═══════╝
        │   │                                  ███
        │   │                                  ███  ← handle
        │   │                                  ███
        │   │   upper arm
        │   │
        │   │
        │   │
   ╭────┴───┴────╮
   │   base ◉    │
   ╰──┬───────┬──╯
  ╭───┴───────┴───╮
  │▓▓▓ C-clamp ▓▓▓│
  ╰───────────────╯
 ═══════════════════════════════════════════════════
                table edge
"""


class ArmCalibrationWizard:
    """Step-by-step interactive manual calibration and range-of-motion mapper."""

    @staticmethod
    def run_interactive_calibration(
        port: str,
        role: str = "leader",
        non_interactive: bool = False,
        calib_dir: Optional[Path] = None,
        lerobot_calib_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Executes a 2-phase interactive calibration:
        1. Homing / Zero Position recording
        2. Live Range-of-Motion (ROM) limit exploration
        """
        import select
        import sys
        import time
        from t2_bots_so101.driver.bus import FeetechBus
        from t2_bots_so101.driver.registers import Register
        from t2_bots.core.config import RigConfigManager

        role_str = role.lower()
        sub_dir = "teleoperators/so_leader" if role_str == "leader" else "robots/so_follower"
        native_file = f"so101_{role_str}.json"

        print(f"\n=======================================================")
        print(f"🔧 [t2-BOTS] Interactive Calibration Wizard: {role.upper()} ARM")
        print(f"   Port: {port}")
        print(f"=======================================================\n")

        bus = FeetechBus(port=port)
        bus.open()

        try:
            # 1. Ensure torque is released on all motors
            print("⚡ Releasing torque across all 6 motors for manual movement...")
            for mid in [1, 2, 3, 4, 5, 6]:
                try:
                    bus.write_byte(mid, Register.TORQUE_ENABLE, 0)
                    bus.write_byte(mid, Register.LOCK, 0)
                except Exception:
                    pass
            time.sleep(0.05)

            # --- PHASE 1: HOMING REFERENCE ---
            print("\n-------------------------------------------------------")
            print("📍 PHASE 1: Zero / Homing Reference Pose")
            print("-------------------------------------------------------")
            print(SO101_HOMING_DIAGRAM)
            print("Position the arm in the 90° reference pose shown above:")
            print("  • Shoulder Pan:  Centered forward (0°)")
            print("  • Shoulder Lift: Straight UP (90° vertical)")
            print("  • Elbow Flex:    Horizontal forward (90° relative to upper arm)")
            print("  • Wrist Flex:    Straight aligned with forearm")
            print("  • Wrist Roll:    Aligned centered")
            print("  • Gripper:       Halfway open (~50%)\n")

            if not non_interactive:
                input("👉 Move the arm into the 90° pose above and press ENTER to lock zero...")

            # Read homing ticks
            homing_ticks = {}
            for mid in [1, 2, 3, 4, 5, 6]:
                homing_ticks[mid] = bus.read_word(mid, Register.PRESENT_POSITION)

            print(f"✔ Recorded Homing Ticks: {homing_ticks}")

            # --- PHASE 2: RANGE OF MOTION SWEEP ---
            print("\n-------------------------------------------------------")
            print("🔄 PHASE 2: Range-of-Motion (ROM) Sweeping")
            print("-------------------------------------------------------")
            print("Move each joint sequentially through its full physical range:")
            print("  • Pan:   Sweep left-to-right stops")
            print("  • Lift:  Tilt backward-to-forward stops")
            print("  • Elbow: Fold fully closed to fully open")
            print("  • Wrist: Flex fully up to fully down")
            print("  • Grip:  Squeeze trigger fully closed to fully open")
            print("Press ENTER in this terminal when finished sweeping.\n")

            mins = homing_ticks.copy()
            maxes = homing_ticks.copy()

            # Optional listener on secondary port to alert user if moving the wrong physical arm
            other_bus = None
            other_port = None
            other_initial = {}
            try:
                from t2_bots_so101.driver.port_resolver import list_candidate_ports
                candidates = [p for p in list_candidate_ports() if p != port]
                if candidates:
                    other_port = candidates[0]
                    other_bus = FeetechBus(port=other_port)
                    other_bus.open()
                    for mid in [1, 2, 3, 4, 6]:
                        try:
                            other_initial[mid] = other_bus.read_word(mid, Register.PRESENT_POSITION, retries=1)
                        except Exception:
                            pass
            except Exception:
                other_bus = None

            SHORT_NAMES = {1: "PAN", 2: "LFT", 3: "ELB", 4: "WRI", 5: "ROL", 6: "GRP"}
            mismatch_alerted = False

            if not non_interactive:
                # Flush any leftover newline or characters from stdin
                time.sleep(0.4)
                if sys.platform.startswith('win'):
                    try:
                        import msvcrt
                        while msvcrt.kbhit():
                            msvcrt.getch()
                    except Exception:
                        pass
                else:
                    try:
                        import termios
                        termios.tcflush(sys.stdin, termios.TCIFLUSH)
                    except Exception:
                        try:
                            while select.select([sys.stdin], [], [], 0)[0]:
                                sys.stdin.readline()
                        except Exception:
                            pass

                sweep_start = time.perf_counter()
                count = 0
                while True:
                    # Update live ticks
                    cur_ticks = {}
                    for mid in [1, 2, 3, 4, 5, 6]:
                        t = bus.read_word(mid, Register.PRESENT_POSITION)
                        cur_ticks[mid] = t
                        mins[mid] = min(mins[mid], t)
                        maxes[mid] = max(maxes[mid], t)

                    count += 1
                    if count % 4 == 0:
                        lines = []
                        for mid in [1, 2, 3, 4, 6]:  # Exclude wrist_roll from compact line
                            span_deg = (maxes[mid] - mins[mid]) * DEGREES_PER_TICK
                            lines.append(f"{SHORT_NAMES[mid]}:{cur_ticks[mid]:4d}({span_deg:3.0f}°)")
                        sys.stdout.write("\r\033[K 🔎 " + " | ".join(lines))
                        sys.stdout.flush()

                    elapsed = time.perf_counter() - sweep_start

                    # Check for wrong-arm movement watchdog
                    if not mismatch_alerted and elapsed > 3.0 and other_bus and other_initial:
                        active_movement = sum(
                            (maxes[m] - mins[m]) * DEGREES_PER_TICK for m in [1, 2, 3, 4, 6]
                        )
                        if active_movement < 3.0:
                            # Active port has not moved at all; check secondary port
                            other_delta = 0
                            for mid, orig_tick in other_initial.items():
                                try:
                                    cur_o = other_bus.read_word(mid, Register.PRESENT_POSITION, retries=1)
                                    other_delta += abs(cur_o - orig_tick)
                                except Exception:
                                    pass
                            if other_delta > 50:  # > 4.4 degrees total motion on secondary arm
                                mismatch_alerted = True
                                print(f"\n\n🚨 [PORT MISMATCH DETECTED]")
                                print(f"   Motion detected on port: {other_port} (NOT {port})!")
                                print(f"   You are physically moving the other arm on your desk.")
                                print(f"   • To calibrate the arm you are holding, run:")
                                print(f"     python -m t2_bots.cli calibrate --manual --arm leader --port {other_port}")
                                print(f"   • Or swap permanent role mappings with:")
                                print(f"     python -m t2_bots.cli config swap\n")

                    # Require at least 1.5s elapsed to avoid accidental double-ENTER
                    if elapsed > 1.5:
                        user_pressed_enter = False
                        if sys.platform.startswith('win'):
                            try:
                                import msvcrt
                                if msvcrt.kbhit():
                                    ch = msvcrt.getch()
                                    if ch in (b'\r', b'\n'):
                                        user_pressed_enter = True
                            except Exception:
                                pass
                        else:
                            try:
                                if sys.stdin in select.select([sys.stdin], [], [], 0.03)[0]:
                                    _ = sys.stdin.readline()
                                    user_pressed_enter = True
                            except Exception:
                                pass

                        if user_pressed_enter:
                            # Check if at least 2 primary joints moved (span > 5 deg)
                            moved_count = sum(1 for m in [1, 2, 3, 4, 6] if (maxes[m] - mins[m]) * DEGREES_PER_TICK >= 5.0)
                            if moved_count < 2:
                                unmoved = [JOINT_ID_MAP[m] for m in [1, 2, 3, 4, 6] if (maxes[m] - mins[m]) * DEGREES_PER_TICK < 5.0]
                                print(f"\n⚠️ Movement not detected on: {unmoved}. Please physically move each joint through its stroke.")
                                time.sleep(0.5)
                                continue
                            break
                    else:
                        time.sleep(0.03)

            if other_bus:
                try:
                    other_bus.close()
                except Exception:
                    pass

            if non_interactive:
                # Provide valid default stroke limits for automated testing/non-interactive mode
                for mid in [1, 2, 3, 4]:
                    mins[mid] = max(0, homing_ticks[mid] - 1200)
                    maxes[mid] = min(4095, homing_ticks[mid] + 1200)
                mins[6] = 1600
                maxes[6] = 3200

            # Wrist roll default full range if not swept
            mins[5] = 0
            maxes[5] = 4095

            # --- PHASE 3: PERSISTENCE ---
            print("\n\n✔ Range sweeping completed. Compiling calibration profile...")

            calib_profile = {}
            for mid, j_name in JOINT_ID_MAP.items():
                h_tick = homing_ticks[mid]
                h_offset = h_tick - 2047
                r_min = mins[mid]
                r_max = maxes[mid]

                calib_profile[j_name] = {
                    "id": mid,
                    "drive_mode": 0,
                    "homing_offset": h_offset,
                    "range_min": r_min,
                    "range_max": r_max,
                }

            from t2_bots.core.safety import CalibrationIntegrityGuard
            # Failsafe: Assert mathematical plausibility before persistence
            CalibrationIntegrityGuard.validate_profile_plausibility(calib_profile, role=role)
            # Create timestamped immutable backup
            backup_path = CalibrationIntegrityGuard.create_backup(calib_profile, role=role)

            # 1. Native SDK calibration directory
            c_dir = calib_dir or CALIB_DIR
            c_dir.mkdir(parents=True, exist_ok=True)
            native_path = c_dir / native_file
            with open(native_path, "w") as f:
                json.dump(calib_profile, f, indent=2)

            # 2. LeRobot cache directory
            lr_dir = lerobot_calib_dir or LEROBOT_CALIB_DIR
            lr_path = lr_dir / sub_dir / "None.json"
            lr_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lr_path, "w") as f:
                json.dump(calib_profile, f, indent=2)

            # 3. Synchronize with rig_config.json if present
            cm = RigConfigManager()
            if cm.exists():
                rig = cm.load()
                if "arms" in rig and role_str in rig["arms"]:
                    rig["arms"][role_str]["calibrated_limits"] = {
                        j: {"min": v["range_min"], "max": v["range_max"], "offset": v["homing_offset"]}
                        for j, v in calib_profile.items()
                    }
                    cm.save(rig)

            print(f"\n🎉 Successfully calibrated and saved {role.upper()} profile:")
            print(f"   Native SDK File:   {native_path}")
            print(f"   LeRobot Sync File: {lr_path}\n")

            print(f"{'Joint':<15} | {'Homing Tick':<11} | {'Offset':<7} | {'Range Min':<10} | {'Range Max':<10} | {'Span (Deg)':<10}")
            print("-" * 75)
            for j_name, data in calib_profile.items():
                m_id = data["id"]
                span = (data["range_max"] - data["range_min"]) * DEGREES_PER_TICK
                print(
                    f"{j_name:<15} | {homing_ticks[m_id]:<11} | {data['homing_offset']:+7d} | "
                    f"{data['range_min']:<10} | {data['range_max']:<10} | {span:8.1f}°"
                )

            return calib_profile

        finally:
            bus.close()

def sync_arm_from_rest_pose(
    robot: Any,
    role: str = "leader",
    calib_dir: Optional[Path] = None,
    lerobot_calib_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Derives and saves a zero-reference calibration profile directly from the arm's
    current resting posture on the table, aligning with CANONICAL_REST_ANGLES.
    Eliminates joint servo desync on fresh machine setups without requiring manual ROM sweeping.
    """
    state = robot.get_state()
    raw_ticks = state.positions_raw

    calib_profile = {}
    for m_id, j_name in JOINT_ID_MAP.items():
        tick = int(raw_ticks.get(j_name, 2047))
        target_deg = CANONICAL_REST_ANGLES.get(j_name, 0.0)

        if j_name == "gripper":
            calib_profile[j_name] = {
                "id": m_id,
                "drive_mode": 0,
                "homing_offset": 0,
                "range_min": min(tick, 1600),
                "range_max": max(tick + 1400, 3200),
            }
        else:
            zero_tick = int(round(tick - (target_deg / DEGREES_PER_TICK)))
            homing_offset = zero_tick - 2047
            calib_profile[j_name] = {
                "id": m_id,
                "drive_mode": 0,
                "homing_offset": homing_offset,
                "range_min": max(0, zero_tick - 1800),
                "range_max": min(4095, zero_tick + 1800),
            }

    c_dir = calib_dir or get_calib_dir()
    c_dir.mkdir(parents=True, exist_ok=True)
    role_str = role.lower()
    native_path = c_dir / f"so101_{role_str}.json"
    with open(native_path, "w") as f:
        json.dump(calib_profile, f, indent=2)

    lr_dir = lerobot_calib_dir or get_lerobot_calib_dir()
    sub_dir = "teleoperators/so_leader" if role_str == "leader" else "robots/so_follower"
    lr_path = lr_dir / sub_dir / "None.json"
    lr_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lr_path, "w") as f:
        json.dump(calib_profile, f, indent=2)

    if hasattr(robot, "reload_calibration"):
        robot.reload_calibration(calib_profile)

    return calib_profile
