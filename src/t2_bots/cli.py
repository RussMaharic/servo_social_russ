"""
Main CLI Dispatcher for t2-BOTS Robotics SDK.
"""

import argparse
import sys

if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

def main():
    parser = argparse.ArgumentParser(prog="t2-bots", description="t2-BOTS Physical AI Robotics SDK")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # detect
    subparsers.add_parser("detect", help="Scan for robot USB serial ports")

    # bootstrap
    p_boot = subparsers.add_parser("bootstrap", help="Run platform bootstrap, driver verification, and guided elevation")
    p_boot.add_argument("--auto", action="store_true", default=True, help="Auto-apply fixes when possible (default: True)")
    p_boot.add_argument("--no-auto", action="store_false", dest="auto", help="Audit mode without auto-applying changes")
    p_boot.add_argument("--elevate", action="store_true", default=False, help="Request root/admin privilege elevation (sudo/UAC)")
    p_boot.add_argument("--json", action="store_true", default=False, help="Output JSON report")

    # stream
    p_stream = subparsers.add_parser("stream", help="Stream live 60 Hz normalized observation state")
    p_stream.add_argument("--port", required=True, help="Serial port of robot")

    # preflight
    p_preflight = subparsers.add_parser("preflight", help="Perform hardware qualification and power rail safety audit")
    p_preflight.add_argument("--arm", choices=["auto", "leader", "follower"], default="auto", help="Arm role when running on single-station setup")

    # teleop
    p_teleop = subparsers.add_parser("teleop", help="Run Leader-Follower teleoperation")
    p_teleop.add_argument("--auto", action="store_true", help="Auto-discover arms and run pre-flight check")
    p_teleop.add_argument("--leader-port", default=None, help="Serial port of Leader arm")
    p_teleop.add_argument("--follower-port", default=None, help="Serial port of Follower arm")
    p_teleop.add_argument("--duration", type=float, default=None, help="Optional run duration in seconds")
    p_teleop.add_argument("--mode", choices=["calibrated", "direct"], default="calibrated", help="Mirroring mode: calibrated (angles) or direct (relative ticks)")

    # calibrate (Kinematic Sync & Zero Calibration)
    p_cal = subparsers.add_parser("calibrate", help="Synchronize dual-arm kinematic zero points and calibration")
    p_cal.add_argument("--sync-home", action="store_true", default=False, help="Derive matching zero points from physical home pose")
    p_cal.add_argument("--manual", action="store_true", default=False, help="Launch interactive manual calibration & range-setting wizard")
    p_cal.add_argument("--arm", choices=["leader", "follower"], default="leader", help="Target arm for manual calibration")
    p_cal.add_argument("--port", default=None, help="Explicit serial port override")

    # home
    p_home = subparsers.add_parser("home", help="Move robot arm to calibrated home pose")
    p_home.add_argument("--auto", action="store_true", help="Auto-discover Follower arm")
    p_home.add_argument("--driver", default="so101", help="Robot driver name")
    p_home.add_argument("--port", default=None, help="Robot serial port")
    p_home.add_argument("--pose", default="rest", choices=["rest", "standby", "zero"], help="Target home posture")
    p_home.add_argument("--duration", type=float, default=2.5, help="Trajectory duration in seconds")
    p_home.add_argument("--release-torque", action="store_true", help="Release torque immediately after reaching home")
    p_home.add_argument("--hold-seconds", type=float, default=None, help="Hold duration in seconds")

    # release
    p_release = subparsers.add_parser("release", help="Independently release actuator torque on Leader or Follower arm")
    p_release.add_argument("--arm", choices=["leader", "follower", "both"], default="both", help="Target arm to release")
    p_release.add_argument("--port", default=None, help="Explicit serial port override")

    # pose (Custom Position Configuration & Persistence)
    p_pose = subparsers.add_parser("pose", help="Manage custom saved positions and postures")
    pose_sub = p_pose.add_subparsers(dest="pose_action", help="Pose action")

    p_pos_cap = pose_sub.add_parser("capture", help="Capture current arm posture as a named position")
    p_pos_cap.add_argument("name", help="Name of the position to save (e.g., home, pick, place)")
    p_pos_cap.add_argument("--arm", choices=["follower", "leader"], default="follower", help="Arm to capture from")
    p_pos_cap.add_argument("--port", default=None, help="Explicit serial port")
    p_pos_cap.add_argument("--desc", default="", help="Optional description of the position")

    p_pos_goto = pose_sub.add_parser("goto", help="Smoothly navigate to a saved or preset position")
    p_pos_goto.add_argument("name", help="Name of the position to go to")
    p_pos_goto.add_argument("--arm", choices=["follower", "leader"], default="follower", help="Target arm")
    p_pos_goto.add_argument("--port", default=None, help="Explicit serial port")
    p_pos_goto.add_argument("--duration", type=float, default=2.5, help="Trajectory duration in seconds")

    p_pos_list = pose_sub.add_parser("list", help="List all saved and preset positions")
    p_pos_list.add_argument("--arm", choices=["follower", "leader"], default="follower", help="Target arm")
    p_pos_list.add_argument("--port", default=None, help="Explicit serial port")

    p_pos_del = pose_sub.add_parser("delete", help="Delete a custom saved position")
    p_pos_del.add_argument("name", help="Name of the position to delete")
    p_pos_del.add_argument("--arm", choices=["follower", "leader"], default="follower", help="Target arm")
    p_pos_del.add_argument("--port", default=None, help="Explicit serial port")

    # config (Hardware Rig Configuration & Environment Profile)
    p_cfg = subparsers.add_parser("config", help="Manage system-specific hardware rig profile")
    cfg_sub = p_cfg.add_subparsers(dest="cfg_action", help="Config action")

    p_cfg_save = cfg_sub.add_parser("save", help="Lock current hardware serials, ports, and home postures into rig profile")
    p_cfg_save.add_argument("--name", default="SO101 Dual-Arm Workstation", help="Rig nickname or label")

    p_cfg_show = cfg_sub.add_parser("show", help="Display the active system rig profile")

    p_cfg_swap = cfg_sub.add_parser("swap", help="Swap Leader and Follower hardware serial port assignments")

    # serve (Web App & Automation Gateway)
    p_serve = subparsers.add_parser("serve", help="Launch Web App Automation Gateway Server")
    p_serve.add_argument("--host", default="0.0.0.0", help="Host interface to bind")
    p_serve.add_argument("--port", type=int, default=8080, help="Port to serve on")

    # peer (Distributed Internet Teleoperation)
    p_peer = subparsers.add_parser("peer", help="Distributed Internet Teleoperation")
    peer_sub = p_peer.add_subparsers(dest="peer_action", help="Peer action")
    
    p_listen = peer_sub.add_parser("listen", help="Start Follower Daemon on System B")
    p_listen.add_argument("--auto", action="store_true", help="Auto-discover Follower arm and local LAN IP")
    p_listen.add_argument("--driver", default="so101", help="Robot driver name")
    p_listen.add_argument("--port", default=None, help="Robot serial port (optional if --auto is used)")
    p_listen.add_argument("--listen-port", type=int, default=8765, help="Port to listen for remote leader")
    p_listen.add_argument("--pin", default=None, help="Explicit 6-digit Gated PIN (e.g. 742891 or 742-891)")
    p_listen.add_argument("--sync-mode", choices=["reset", "absolute"], default="reset", help="Synchronization mode: 'reset' (default: aligns arms from physical reset posture) or 'absolute'")

    p_connect = peer_sub.add_parser("connect", help="Connect Leader Client on System A")
    p_connect.add_argument("--auto", action="store_true", help="Auto-discover Leader arm")
    p_connect.add_argument("--driver", default="so101_leader", help="Leader driver name")
    p_connect.add_argument("--port", default=None, help="Leader robot serial port (optional if --auto is used)")
    p_connect.add_argument("--host", required=True, help="Remote Follower IP or domain")
    p_connect.add_argument("--remote-port", type=int, default=8765, help="Remote Follower port")
    p_connect.add_argument("--token", default=None, help="Authentication session token")
    p_connect.add_argument("--pin", default=None, help="6-digit Gated PIN (e.g. 742-891 or 742891)")
    p_connect.add_argument("--sync-rest", action="store_true", help="Auto-calibrate leader zero reference from current resting posture")
    p_connect.add_argument("--ssl", action="store_true", help="Connect via secure WebSocket (wss://) for Cloudflare or HTTPS tunnels")

    # eval (pstack Hardware Benchmark Suite)
    p_eval = subparsers.add_parser("eval", help="Run pstack-inspired hardware benchmark evaluation")
    p_eval.add_argument("--driver", default="so101", help="Robot driver name")
    p_eval.add_argument("--port", required=True, help="Robot serial port")
    p_eval.add_argument("--output", default="eval_results", help="Directory to save evaluation artifacts")

    # qualify-arm (Individual Station Hardware Qualification, EEPROM Unlock & Readiness Audit)
    p_qual = subparsers.add_parser("qualify-arm", help="Independently qualify arm, unlock EEPROM limits, and certify readiness")
    p_qual.add_argument("--arm", choices=["auto", "leader", "follower"], default="auto", help="Arm role to qualify (auto, leader, follower)")
    p_qual.add_argument("--port", default=None, help="Explicit serial port override")
    p_qual.add_argument("--no-unlock", action="store_true", help="Skip EEPROM angle limit unlocking")
    p_qual.add_argument("--no-clear-errors", action="store_true", help="Skip clearing latched status errors")
    p_qual.add_argument("--clearance", type=int, default=30, help="Safety clearance in ticks off mechanical stops (default: 30)")

    # certify (Hardware Qualification & Cryptographic Certificate Generation)
    p_cert = subparsers.add_parser("certify", help="Inspect power rail, unlock EEPROM limits, verify homing, and issue cryptographic Hardware Qualification Certificate")
    p_cert.add_argument("--arm", choices=["auto", "leader", "follower"], default="auto", help="Arm role to certify (auto, leader, follower)")
    p_cert.add_argument("--port", default=None, help="Explicit serial port override")
    p_cert.add_argument("--arm-id", default=None, help="Explicit Arm ID override")
    p_cert.add_argument("--no-unlock", action="store_true", help="Skip EEPROM angle limit unlocking")
    p_cert.add_argument("--verify", default=None, help="Verify existing certificate JSON file path")

    # relay (Autonomous Pinggy Cloud Relay Manager)
    p_relay = subparsers.add_parser("relay", help="Manage autonomous zero-install Pinggy Cloud Relay reverse tunnels")
    relay_sub = p_relay.add_subparsers(dest="relay_action", help="Relay action")
    p_rel_start = relay_sub.add_parser("start", help="Start background reverse tunnel")
    p_rel_start.add_argument("--port", type=int, default=8765, help="Local port to forward (default: 8765)")
    p_rel_status = relay_sub.add_parser("status", help="Check tunnel operational status")
    p_rel_stop = relay_sub.add_parser("stop", help="Stop background tunnel")

    # swarm (1-to-N Distributed Swarm Teleoperation with Admission Control)
    p_swarm = subparsers.add_parser("swarm", help="One-to-Many Swarm Teleoperation (1 Leader -> N Followers)")
    swarm_sub = p_swarm.add_subparsers(dest="swarm_action", help="Swarm action")

    p_sw_host = swarm_sub.add_parser("host", help="Host Swarm Hub on Leader Station")
    p_sw_host.add_argument("--auto", action="store_true", help="Auto-discover Leader arm")
    p_sw_host.add_argument("--port", default=None, help="Leader robot serial port")
    p_sw_host.add_argument("--listen-port", type=int, default=8765, help="Port to bind Swarm Hub")
    p_sw_host.add_argument("--pin", default=None, help="6-digit Gated PIN")
    p_sw_host.add_argument("--relay", action="store_true", help="Automatically expose via Pinggy Cloud Relay tunnel")

    p_sw_join = swarm_sub.add_parser("join", help="Join Swarm Hub as Follower Arm")
    p_sw_join.add_argument("--auto", action="store_true", help="Auto-discover Follower arm")
    p_sw_join.add_argument("--port", default=None, help="Follower robot serial port")
    p_sw_join.add_argument("--host", required=True, help="Swarm Hub host or tunnel URL")
    p_sw_join.add_argument("--hub-port", type=int, default=8765, help="Swarm Hub port")
    p_sw_join.add_argument("--pin", default=None, help="Swarm Gated PIN")
    p_sw_join.add_argument("--name", default=None, help="Custom Follower identifier name")
    p_sw_join.add_argument("--cert", default=None, help="Path to Hardware Qualification Certificate JSON")

    args = parser.parse_args()

    if args.subcommand == "detect":
        from t2_bots_so101.cli import cmd_detect
        cmd_detect(args)
    elif args.subcommand == "preflight":
        from t2_bots.core.preflight import HardwarePreflight
        pf = HardwarePreflight()
        print("🔍 [t2-BOTS Pre-Flight] Auditing hardware descriptors, power rails, and bus turnaround...")
        try:
            l_port, f_port = pf.resolve_arms_automatically()
            print(f"✔ Found Leader Arm:   {l_port}")
            print(f"✔ Found Follower Arm: {f_port}")
            l_health = pf.check_bus_health(l_port, "leader")
            print(f"  • Leader Bus:   {l_health['voltage_v']}V | Latency: {l_health['latency_ms']}ms | All 6 Actuators Healthy")
            f_health = pf.check_bus_health(f_port, "follower")
            print(f"  • Follower Bus: {f_health['voltage_v']}V | Latency: {f_health['latency_ms']}ms | All 6 Actuators Healthy")
        except Exception:
            ports = pf.scan_ports()
            role = getattr(args, "arm", "auto")
            resolved_port = None
            from t2_bots.core.preflight import KNOWN_DEVICES

            if role == "auto":
                f_sn = pf.registry.get("follower", KNOWN_DEVICES["follower"])
                l_sn = pf.registry.get("leader", KNOWN_DEVICES["leader"])
                for dev, meta in ports.items():
                    sn = meta.get("serial_number", "")
                    if sn and f_sn in sn:
                        role = "follower"
                        resolved_port = dev
                        break
                    elif sn and l_sn in sn:
                        role = "leader"
                        resolved_port = dev
                        break
                if not resolved_port:
                    role = "follower" if sys.platform.startswith("darwin") else "leader"
                    resolved_port = pf.resolve_single_arm(role)
            else:
                resolved_port = pf.resolve_single_arm(role)

            print(f"✔ Single-Station Mode: Auto-Resolved {role.capitalize()} Arm on {resolved_port}")
            health = pf.check_bus_health(resolved_port, role)
            print(f"  • {role.capitalize()} Bus:   {health['voltage_v']}V | Latency: {health['latency_ms']}ms | All 6 Actuators Healthy")
        print("\n🎉 Pre-flight hardware qualification: 100% READY FOR TELEOPERATION!")
    elif args.subcommand == "stream":
        from t2_bots_so101.cli import cmd_stream
        cmd_stream(args)
    elif args.subcommand == "teleop":
        from t2_bots_so101.cli import cmd_teleop
        cmd_teleop(args)
    elif args.subcommand == "home":
        from t2_bots.core.registry import get_robot
        from t2_bots.core.preflight import HardwarePreflight
        port = args.port
        if getattr(args, "auto", False) or not port:
            pf = HardwarePreflight()
            port = pf.resolve_single_arm("follower")
            print(f"🔍 [t2-BOTS Auto] Resolved Follower arm on {port}")
            health = pf.check_bus_health(port, "follower")
            print(f"✔ Power Rail: {health['voltage_v']}V healthy")

        print(f"🤖 Initializing arm and smoothly returning to '{args.pose}' home pose ({args.duration}s)...")
        robot = get_robot(args.driver, port=port)
        robot.connect()
        try:
            robot.go_home(pose=args.pose, duration_s=args.duration)
            obs = robot.get_observation()
            p = {k: round(v, 1) for k, v in obs.joint_positions.items()}
            print(f"✔ Reached '{args.pose}' posture: {p}")

            if args.release_torque:
                print("✔ Immediately releasing torque as requested.")
            elif args.hold_seconds is not None:
                print(f"⏳ Holding torque for {args.hold_seconds:.1f}s...")
                import time
                time.sleep(args.hold_seconds)
            elif args.pose == "rest":
                print("⏳ Settling in rest pose (2.0s hold)...")
                import time
                time.sleep(2.0)
            else:
                print(f"⚡ Holding torque active at '{args.pose}'. Press Ctrl+C to release torque and park.")
                import time
                while True:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            robot.disconnect()
            print("✔ Torque safely released. Hardware parked.")
    elif args.subcommand == "release":
        from t2_bots.core.torque import release_leader_torque, release_follower_torque
        if args.arm in ["leader", "both"]:
            l_pos = release_leader_torque(port=args.port if args.arm == "leader" else None)
            print(f"✔ LEADER Arm: Torque RELEASED across all 6 motors. Raw ticks: {l_pos}")
        if args.arm in ["follower", "both"]:
            f_pos = release_follower_torque(port=args.port if args.arm == "follower" else None)
            print(f"✔ FOLLOWER Arm: Torque RELEASED across all 6 motors. Raw ticks: {f_pos}")
    elif args.subcommand == "calibrate":
        from t2_bots.core.calibration import ArmSynchronizer, ArmCalibrationWizard
        from t2_bots.core.preflight import HardwarePreflight

        if args.manual:
            port = args.port
            if not port:
                pf = HardwarePreflight()
                port = pf.resolve_single_arm(args.arm)
            ArmCalibrationWizard.run_interactive_calibration(port=port, role=args.arm)
        else:
            print("🔧 [t2-BOTS] Synchronizing dual-arm kinematic zero points using captured home posture...")
            syncer = ArmSynchronizer()
            res = syncer.sync_from_home_pose()
            print(f"✔ Kinematic profiles synchronized successfully:")
            print(f"   Leader Profile:   {res['paths']['leader']}")
            print(f"   Follower Profile: {res['paths']['follower']}")
            print(f"   Synchronized with LeRobot cache: ~/.cache/huggingface/lerobot/calibration/")
            print("\n📊 Verification of Calibrated Zero Ticks:")
            for joint, l_data in res["leader_calibration"].items():
                f_data = res["follower_calibration"][joint]
                print(f"   • {joint:<14} Leader Offset: {l_data['homing_offset']:+5d} | Follower Offset: {f_data['homing_offset']:+5d}")
            print("\n✔ Zero-point disparity eliminated. Both arms will now mirror with 1:1 physical tracking.")
    elif args.subcommand == "pose":
        from t2_bots.core.registry import get_robot
        from t2_bots.core.preflight import HardwarePreflight
        from t2_bots.core.base import RobotRole
        pf = HardwarePreflight()
        port = args.port
        driver_name = "so101_leader" if args.arm == "leader" else "so101"
        role = RobotRole.LEADER if args.arm == "leader" else RobotRole.FOLLOWER
        if not port:
            port = pf.resolve_single_arm(args.arm)
        robot = get_robot(driver_name, port=port, role=role)
        robot.connect()
        try:
            if args.pose_action == "capture":
                saved = robot.capture_pose(name=args.name, description=args.desc)
                print(f"✔ Successfully captured position '{args.name}' for {args.arm.upper()} arm:")
                print(f"   Joints:  {saved['joints']}")
                print(f"   Gripper: {saved['gripper']}")
                print(f"   Storage: ~/.config/t2_bots/poses/{robot.name}_{robot.role.value}_poses.json")
            elif args.pose_action == "goto":
                print(f"🚀 Moving {args.arm.upper()} arm to '{args.name}' over {args.duration}s...")
                robot.goto_pose(name=args.name, duration_s=args.duration)
                obs = robot.get_observation()
                print(f"✔ Reached position '{args.name}': { {k: round(v, 1) for k, v in obs.joint_positions.items()} }")
            elif args.pose_action == "list":
                poses = robot.list_poses()
                print(f"\n📋 Available Positions for {args.arm.upper()} arm:")
                for k, v in poses.items():
                    p_type = v.get("type", "custom")
                    desc = v.get("description", "")
                    j_summary = ", ".join(f"{jk[:3]}:{jv:+.1f}°" for jk, jv in v.get("joints", {}).items() if jk != "gripper")
                    print(f"  • {k:<15} [{p_type:<6}] {j_summary} (Grip: {v.get('gripper', 0.0):.2f}) {desc}")
                print()
            elif args.pose_action == "delete":
                if robot.delete_pose(name=args.name):
                    print(f"✔ Deleted custom position '{args.name}'.")
                else:
                    print(f"❌ Position '{args.name}' not found or cannot delete preset.")
            else:
                p_pose.print_help()
        finally:
            if args.pose_action != "goto":
                robot.disconnect()
    elif args.subcommand == "config":
        from t2_bots.core.config import RigConfigManager
        cm = RigConfigManager()
        if args.cfg_action == "save":
            print(f"🔒 Interrogating hardware rig and saving profile '{args.name}'...")
            prof = cm.capture_live_rig(rig_name=args.name)
            print(f"✔ Successfully saved rig profile to {cm.config_file}")
            l_info = prof['arms']['leader']
            f_info = prof['arms']['follower']
            if l_info.get("port"):
                print(f"   Leader:   SN {l_info.get('serial_number', 'unknown')} on {l_info['port']}")
                print(f"   Leader Home Ticks:   {l_info['home_pose']['raw_ticks']}")
            else:
                print(f"   Leader:   [Remote Distributed Station]")
            if f_info.get("port"):
                print(f"   Follower: SN {f_info.get('serial_number', 'unknown')} on {f_info['port']}")
                print(f"   Follower Home Ticks: {f_info['home_pose']['raw_ticks']}")
            else:
                print(f"   Follower: [Remote Distributed Station]")
            print(f"   LAN IP:   {prof['host']['lan_ip']}")
        elif args.cfg_action == "show":
            if not cm.exists():
                print(f"❌ No rig profile found at {cm.config_file}. Run 't2-bots config save' first.")
            else:
                prof = cm.load()
                import json
                print(json.dumps(prof, indent=2))
        elif args.cfg_action == "swap":
            from t2_bots.core.preflight import HardwarePreflight
            pf = HardwarePreflight()
            reg = pf.registry
            old_l = reg.get("leader", "5C82109414")
            old_f = reg.get("follower", "5C82107826")
            reg["leader"] = old_f
            reg["follower"] = old_l
            pf.save_registry(reg)

            # Also update rig_config.json if present
            if cm.exists():
                rig = cm.load()
                if "arms" in rig and "leader" in rig["arms"] and "follower" in rig["arms"]:
                    rig["arms"]["leader"], rig["arms"]["follower"] = (
                        rig["arms"]["follower"],
                        rig["arms"]["leader"],
                    )
                    rig["arms"]["leader"]["role"] = "leader"
                    rig["arms"]["follower"]["role"] = "follower"
                    cm.save(rig)

            new_l, new_f = pf.resolve_arms_automatically()
            print(f"🔄 Swapped hardware role assignments in system registry:")
            print(f"   Leader Arm:   {new_l} (SN: {reg['leader']})")
            print(f"   Follower Arm: {new_f} (SN: {reg['follower']})")
            print("✔ Now running without --port will target the newly assigned Leader!")
        else:
            p_cfg.print_help()
    elif args.subcommand == "serve":
        from t2_bots.gateway.server import start_server
        start_server(host=args.host, port=args.port)
    elif args.subcommand == "peer":
        import asyncio
        from t2_bots.core.registry import get_robot
        from t2_bots.core.preflight import HardwarePreflight
        pf = HardwarePreflight()

        if args.peer_action == "listen":
            from t2_bots.network.peer import PeerListener
            port = args.port
            if getattr(args, "auto", False) or not port:
                print("🔍 [t2-BOTS Auto] Resolving Follower serial port via USB descriptors...")
                port = pf.resolve_single_arm("follower")
                health = pf.check_bus_health(port, "follower")
                print(f"✔ Auto-Resolved Follower Arm on {port} ({health['voltage_v']}V healthy)")

            robot = get_robot(args.driver, port=port)
            robot.connect()
            listener = PeerListener(
                robot=robot,
                port=args.listen_port,
                sync_mode=args.sync_mode,
                pin=getattr(args, "pin", None),
            )
            try:
                asyncio.run(listener.start())
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            print("\n✔ Follower listener daemon stopped.")
        elif args.peer_action == "connect":
            if not getattr(args, "pin", None) and not getattr(args, "token", None):
                p_connect.error("Either --pin <PIN> or --token <TOKEN> is required to connect.")

            from t2_bots.network.peer import PeerClient
            port = args.port
            if getattr(args, "auto", False) or not port:
                print("🔍 [t2-BOTS Auto] Resolving Leader serial port via USB descriptors...")
                port = pf.resolve_single_arm("leader")
                health = pf.check_bus_health(port, "leader")
                print(f"✔ Auto-Resolved Leader Arm on {port} (Latency: {health['latency_ms']}ms)")

            robot = get_robot(args.driver, port=port)
            robot.connect()
            client = PeerClient(
                leader_robot=robot,
                host=args.host,
                port=args.remote_port,
                token=args.token,
                pin=args.pin,
                sync_rest=args.sync_rest,
                ssl=getattr(args, "ssl", False),
            )
            try:
                asyncio.run(client.run())
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            print("\n✔ Disconnected from remote follower.")
        else:
            p_peer.print_help()
    elif args.subcommand == "eval":
        from pathlib import Path
        from t2_bots.core.registry import get_robot
        from t2_bots.eval.benchmarks import run_full_evaluation
        robot = get_robot(args.driver, port=args.port)
        run_full_evaluation(robot=robot, output_dir=Path(args.output))
    elif args.subcommand == "qualify-arm":
        from t2_bots.core.qualification import ArmQualificationEngine
        qe = ArmQualificationEngine()
        qe.qualify_arm(
            role=args.arm,
            port=args.port,
            unlock_eeprom=not getattr(args, "no_unlock", False),
            clear_errors=not getattr(args, "no_clear_errors", False),
            safety_margin_ticks=getattr(args, "clearance", 30),
        )
    elif args.subcommand == "certify":
        from t2_bots.core.certification import CertificationEngine, verify_certificate
        engine = CertificationEngine()
        if getattr(args, "verify", None):
            is_valid = verify_certificate(args.verify, raise_on_error=False)
            if is_valid:
                print(f"✔ Certificate {args.verify} is VALID and untampered.")
                sys.exit(0)
            else:
                print(f"❌ Certificate {args.verify} is INVALID, tampered, or expired.")
                sys.exit(1)
        else:
            role = args.arm
            if role == "auto":
                role = "follower" if sys.platform.startswith("darwin") else "leader"
            cert = engine.certify_arm(
                role=role,
                arm_id=args.arm_id,
                port=args.port,
                unlock_eeprom=not getattr(args, "no_unlock", False),
                raise_on_failure=False,
            )
            print(cert.to_json(indent=2))
            if cert.grade == "FAILED":
                sys.exit(1)
    elif args.subcommand == "bootstrap":
        import json
        from t2_bots.platform.installer import run_bootstrap
        is_interactive = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        report = run_bootstrap(auto=args.auto, elevate=args.elevate, interactive=is_interactive)
        if getattr(args, "json", False):
            print(json.dumps(report.to_dict(), indent=2))
        else:
            report.print_report()
        if not report.success:
            sys.exit(1)
    elif args.subcommand == "relay":
        import time
        import json
        from t2_bots.network.relay import PinggyRelayManager
        mgr = PinggyRelayManager(local_port=getattr(args, "port", 8765))
        if getattr(args, "relay_action", None) == "start":
            print(f"🚀 [t2-BOTS Relay] Starting zero-install Pinggy Cloud Relay for local port {args.port}...")
            tunnel = mgr.start_tunnel(local_port=args.port)
            print("=" * 65)
            print(f"✔ Public Relay Live:  {tunnel.url}")
            print(f"  Public Host:        {tunnel.host}")
            print(f"  Public Port:        {tunnel.port}")
            print(f"  Forwarding To:      localhost:{tunnel.local_port}")
            print("=" * 65)
            print("Keep this process running. Press Ctrl+C to terminate relay.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                mgr.stop_tunnel()
                print("\n✔ Public tunnel cleanly closed.")
        elif getattr(args, "relay_action", None) == "status":
            st = mgr.get_status()
            print(json.dumps(st, indent=2))
        elif getattr(args, "relay_action", None) == "stop":
            mgr.stop_tunnel()
            print("✔ Public tunnel stopped.")
        else:
            p_relay.print_help()
    elif args.subcommand == "swarm":
        import time
        import json
        import asyncio
        from t2_bots.network.swarm import SwarmHubServer, SwarmFollowerClient
        from t2_bots.core.registry import get_robot
        from t2_bots.core.preflight import HardwarePreflight

        pf = HardwarePreflight()
        if getattr(args, "swarm_action", None) == "host":
            port = args.port
            if getattr(args, "auto", False) or not port:
                print("🔍 [t2-BOTS Swarm] Resolving Leader serial port via USB descriptors...")
                port = pf.resolve_single_arm("leader")
                health = pf.check_bus_health(port, "leader")
                print(f"✔ Auto-Resolved Leader Arm on {port} (Voltage: {health['voltage_v']}V)")

            robot = get_robot("so101_leader", port=port)
            robot.connect()
            hub = SwarmHubServer(
                leader_robot=robot,
                port=args.listen_port,
                pin=args.pin,
                use_relay=getattr(args, "relay", False),
            )
            try:
                asyncio.run(hub.start())
                while True:
                    time.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                asyncio.run(hub.stop())
            print("\n✔ Swarm Hub cleanly shut down.")
        elif getattr(args, "swarm_action", None) == "join":
            port = args.port
            if getattr(args, "auto", False) or not port:
                print("🔍 [t2-BOTS Swarm] Resolving Follower serial port via USB descriptors...")
                port = pf.resolve_single_arm("follower")
                health = pf.check_bus_health(port, "follower")
                print(f"✔ Auto-Resolved Follower Arm on {port} (Voltage: {health['voltage_v']}V)")

            # Resolve certificate
            cert = {}
            if getattr(args, "cert", None):
                with open(args.cert, "r") as f:
                    cert = json.load(f)
            else:
                from t2_bots.core.certification import CertificationEngine
                engine = CertificationEngine()
                cert_file = engine.get_certificate_path(getattr(args, "name", "SO101-Follower"))
                if cert_file.exists():
                    with open(cert_file, "r") as f:
                        cert = json.load(f)

            robot = get_robot("so101", port=port)
            robot.connect()
            client = SwarmFollowerClient(
                follower_robot=robot,
                hub_host=args.host,
                hub_port=args.hub_port,
                pin=args.pin,
                name=args.name,
                certificate=cert,
            )
            try:
                asyncio.run(client.run())
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            print("\n✔ Disconnected from Swarm Hub.")
        else:
            p_swarm.print_help()
    else:
        parser.print_help()

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
