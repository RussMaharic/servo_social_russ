"""
CLI Commands for SO101 under t2-BOTS.
"""

import sys
import time
import argparse
from t2_bots.core.base import RobotRole
from t2_bots_so101.arm import SO101Manipulator, SO101Teleoperator
from t2_bots_so101.driver.port_resolver import list_candidate_ports, resolve_ports_via_tactile_wiggle

def cmd_detect(args):
    import serial.tools.list_ports
    print("🔍 [t2-BOTS] Scanning for Serial Adapters...")
    comports = list(serial.tools.list_ports.comports())
    if not comports:
        print("❌ No serial ports found!")
        return
    print(f"✔ Found {len(comports)} serial port(s):")
    for p in comports:
        desc = p.description or "Serial Port"
        sn = f" (SN: {p.serial_number})" if p.serial_number else ""
        hint = " ✨ [LEADER MATCH]" if p.serial_number == "5C82109414" or "ch343" in desc.lower() else ""
        print(f"  • {p.device:<6} : {desc}{sn}{hint}")

def cmd_stream(args):
    port = args.port
    print(f"📡 [t2-BOTS] Streaming SO101 Telemetry on {port} at 60 Hz...")
    arm = SO101Manipulator(port=port)
    arm.connect()
    try:
        while True:
            t0 = time.perf_counter()
            obs = arm.get_observation()
            dt = (time.perf_counter() - t0) * 1000.0
            pos = obs.joint_positions
            grip_pct = obs.gripper_aperture * 100.0
            sys.stdout.write(
                f"\r[{dt:3.1f}ms] Pan:{pos.get('shoulder_pan', 0.0):5.1f}° | "
                f"Lift:{pos.get('shoulder_lift', 0.0):5.1f}° | "
                f"Elb:{pos.get('elbow_flex', 0.0):5.1f}° | "
                f"W_P:{pos.get('wrist_flex', 0.0):5.1f}° | "
                f"W_R:{pos.get('wrist_roll', 0.0):5.1f}° | "
                f"Grip:{grip_pct:4.1f}%"
            )
            sys.stdout.flush()
            time.sleep(1.0 / 60.0)
    except KeyboardInterrupt:
        arm.disconnect()
        print("\n✔ Telemetry stream stopped.")

def cmd_teleop(args):
    l_port = getattr(args, "leader_port", None)
    f_port = getattr(args, "follower_port", None)
    duration = getattr(args, "duration", None)
    use_auto = getattr(args, "auto", False)

    from t2_bots.core.preflight import HardwarePreflight
    pf = HardwarePreflight()

    if use_auto or not l_port or not f_port:
        print("🔍 [t2-BOTS Pre-Flight] Auto-discovering robotic hardware via USB descriptors...")
        l_port, f_port = pf.resolve_arms_automatically()
        print(f"✔ Auto-Resolved Leader:   {l_port}")
        print(f"✔ Auto-Resolved Follower: {f_port}")

    # 1. Bus Health & Power Rail Audit
    print("⚡ [t2-BOTS Pre-Flight] Auditing actuator power rails & bus turnaround...")
    f_health = pf.check_bus_health(f_port, expected_role="follower")
    print(f"  • Follower Power: {f_health['voltage_v']}V (12V Rail Healthy) | Latency: {f_health['latency_ms']}ms")
    l_health = pf.check_bus_health(l_port, expected_role="leader")
    print(f"  • Leader Power:   {l_health['voltage_v']}V | Latency: {l_health['latency_ms']}ms")

    print(f"\n🤖 [t2-BOTS] Initializing Teleoperation Pipeline...")
    print(f"   Leader:   {l_port}")
    print(f"   Follower: {f_port}")
    if duration:
        print(f"   Duration: {duration} seconds")

    mode = getattr(args, "mode", "calibrated")
    print(f"   Mode:     {mode.upper()} mirroring")

    leader = SO101Teleoperator(port=l_port)
    follower = SO101Manipulator(port=f_port)

    # 1b. Calibration Integrity & Dual-Arm Kinematic Symmetry Assertion
    if mode == "calibrated":
        from t2_bots.core.safety import CalibrationIntegrityGuard, CalibrationIntegrityError, KinematicSymmetryError
        try:
            disparities = CalibrationIntegrityGuard.assert_dual_arm_symmetry(
                leader.calib_data, follower.calib_data, max_allowed_deg=30.0
            )
            max_disp = max(disparities.values()) if disparities else 0.0
            print(f"✔ Kinematic Symmetry Asserted (Worst joint disparity: {max_disp:.1f}° < 30.0° safe limit)")
        except (CalibrationIntegrityError, KinematicSymmetryError) as e:
            print(f"\n🚨 [SAFETY INTERLOCK TRIPPED] Teleoperation blocked to protect physical hardware:\n{e}\n")
            return

    leader.connect()
    follower.connect()

    # Load rig config home ticks if direct mode is active
    f_home_ticks = {}
    l_home_ticks = {}
    if mode == "direct":
        from t2_bots.core.config import RigConfigManager
        cm = RigConfigManager()
        if cm.exists():
            rig = cm.load()
            l_home_ticks = {int(k): v for k, v in rig.get("arms", {}).get("leader", {}).get("home_pose", {}).get("raw_ticks", {}).items()}
            f_home_ticks = {int(k): v for k, v in rig.get("arms", {}).get("follower", {}).get("home_pose", {}).get("raw_ticks", {}).items()}

    # 2. Soft-Start Trajectory Alignment
    pf.execute_soft_start_alignment(leader, follower, duration_s=1.2)

    print("\n⚡ Closed-loop mirroring active! Move the Leader arm... (Ctrl+C to stop)")
    count = 0
    t_start = time.perf_counter()
    try:
        while True:
            t0 = time.perf_counter()
            if duration and (t0 - t_start) >= duration:
                break

            if mode == "direct" and l_home_ticks and f_home_ticks:
                from t2_bots_so101.driver.registers import Register
                # Read Leader raw ticks directly
                target_ticks = {}
                for m in [1, 2, 3, 4, 5, 6]:
                    l_val = leader.bus.read_word(m, Register.PRESENT_POSITION)
                    l_h = l_home_ticks.get(m, 2047)
                    f_h = f_home_ticks.get(m, 2047)
                    if m == 6:  # Gripper proportional mapping
                        target_ticks[m] = max(1600, min(3200, f_h + (l_val - l_h)))
                    else:
                        target_ticks[m] = max(0, min(4095, f_h + (l_val - l_h)))
                # Command Follower directly
                for m, t_val in target_ticks.items():
                    follower.bus.write_word(m, Register.GOAL_POSITION, t_val)
                p = {f"M{k}": v for k, v in target_ticks.items()}
                grip_val = target_ticks.get(6, 0)
            else:
                obs = leader.get_observation()
                from t2_bots.core.schema import RobotAction
                action = RobotAction(
                    target_positions=obs.joint_positions,
                    target_gripper=obs.gripper_aperture,
                )
                follower.send_action(action)
                p = obs.joint_positions
                grip_val = obs.gripper_aperture * 100.0

            dt = (time.perf_counter() - t0) * 1000.0
            count += 1
            
            # Print live 10 Hz telemetry stats
            if count % 6 == 0:
                elapsed = time.perf_counter() - t_start
                hz = count / elapsed if elapsed > 0 else 60.0
                if mode == "direct":
                    sys.stdout.write(
                        f"\r[{hz:4.1f} Hz | dt:{dt:3.1f}ms] M1:{p.get('M1', 0)} M2:{p.get('M2', 0)} M3:{p.get('M3', 0)} M4:{p.get('M4', 0)} Grip:{grip_val}"
                    )
                else:
                    sys.stdout.write(
                        f"\r[{hz:4.1f} Hz | dt:{dt:3.1f}ms] Pan:{p.get('shoulder_pan', 0.0):+5.1f}° "
                        f"Lift:{p.get('shoulder_lift', 0.0):+5.1f}° "
                        f"Elb:{p.get('elbow_flex', 0.0):+5.1f}° "
                        f"Grip:{grip_val:4.1f}%"
                    )
                sys.stdout.flush()

            time.sleep(max(0.0, (1.0 / 60.0) - (dt / 1000.0)))
    except KeyboardInterrupt:
        pass
    finally:
        time.sleep(0.05)
        follower.disconnect()
        leader.disconnect()
        print("\n✔ Teleoperation stopped. Torque disabled.")
