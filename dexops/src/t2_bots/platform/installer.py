"""Read-only USB and Python probes used by the Dexops onboarding screen.

Extracted from the upstream installer. No driver installation, elevation or
system permission changes are performed by this module.
"""
import getpass
import glob
import os
import platform as _sys_platform_mod
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LINUX_UDEV_RULES_PATH = Path("/etc/udev/rules.d/99-t2-so101.rules")

SUPPORTED_CHIPSETS_LINUX = [
    {
        "name": "CH340 / CH341 USB-to-Serial",
        "vid": "1a86",
        "pid": "7523",
    },
    {
        "name": "FTDI FT232R USB-to-Serial Bridge",
        "vid": "0403",
        "pid": "6001",
    },
    {
        "name": "Silicon Labs CP210x USB-to-UART Bridge",
        "vid": "10c4",
        "pid": "ea60",
    },
]

def get_linux_target_user() -> str:
    """Determines target non-root username for group assignment."""
    return os.environ.get("SUDO_USER") or os.environ.get("USER") or getpass.getuser()

def check_linux_udev_rules(rules_path: Path = LINUX_UDEV_RULES_PATH) -> Tuple[bool, List[str]]:
    """
    Verifies if /etc/udev/rules.d/99-t2-so101.rules exists and contains rules
    for CH340 (1a86:7523), FTDI (0403:6001), and CP210x (10c4:ea60).
    """
    if not rules_path.exists():
        return False, ["File does not exist"]

    try:
        content = rules_path.read_text(encoding="utf-8")
    except Exception as e:
        return False, [f"Failed to read {rules_path}: {e}"]

    missing = []
    for chip in SUPPORTED_CHIPSETS_LINUX:
        vid_match = f'ATTRS{{idVendor}}=="{chip["vid"]}"'
        pid_match = f'ATTRS{{idProduct}}=="{chip["pid"]}"'
        if vid_match not in content or pid_match not in content:
            missing.append(f"{chip['name']} ({chip['vid']}:{chip['pid']})")

    return len(missing) == 0, missing

def check_linux_user_groups(user: Optional[str] = None) -> Tuple[bool, List[str], List[str]]:
    """
    Checks if target user belongs to 'dialout' and 'plugdev' groups.
    Returns (all_present, present_groups, missing_groups).
    """
    target_user = user or get_linux_target_user()
    required = ["dialout", "plugdev"]

    try:
        res = subprocess.run(["id", "-Gn", target_user], capture_output=True, text=True, check=True)
        user_groups = res.stdout.strip().split()
    except Exception:
        # Fallback inspection if id command fails
        import grp
        user_groups = []
        for g in grp.getgrall():
            if target_user in g.gr_mem:
                user_groups.append(g.gr_name)

    present = [g for g in required if g in user_groups]
    missing = [g for g in required if g not in user_groups]
    return len(missing) == 0, present, missing

def audit_macos_serial_nodes() -> Dict[str, Any]:
    """
    Audits /dev/cu.* and /dev/tty.* nodes on macOS.
    Verifies user rw permissions and clarifies the architectural distinction:
    - /dev/cu.* (Calling Unit) is non-blocking (does not wait for DCD modem carrier).
    - /dev/tty.* (Teletype) may block on open awaiting DCD assert.
    """
    cu_nodes = glob.glob("/dev/cu.*")
    tty_nodes = glob.glob("/dev/tty.*")

    # Filter for candidate robot serial nodes (usbserial, usbmodem, wch, slab, uart, etc.)
    robot_filter = lambda p: any(
        k in p.lower() for k in ["usb", "wch", "slab", "uart", "modem", "serial"]
    )
    relevant_cu = sorted([p for p in cu_nodes if robot_filter(p)])
    relevant_tty = sorted([p for p in tty_nodes if robot_filter(p)])

    all_nodes = relevant_cu + relevant_tty
    node_audit = []
    permission_issues = []

    for node in all_nodes:
        readable = os.access(node, os.R_OK)
        writable = os.access(node, os.W_OK)
        node_type = "Calling Unit (/dev/cu.*, Non-blocking)" if node.startswith("/dev/cu.") else "Teletype (/dev/tty.*, DCD-sensitive)"
        node_info = {
            "path": node,
            "readable": readable,
            "writable": writable,
            "type": node_type,
        }
        node_audit.append(node_info)
        if not (readable and writable):
            permission_issues.append(node)

    return {
        "cu_nodes": relevant_cu,
        "tty_nodes": relevant_tty,
        "total_robot_nodes": len(all_nodes),
        "node_audit": node_audit,
        "permission_issues": permission_issues,
        "note": "SO-101 driver automatically favors /dev/cu.* calling unit nodes to prevent DCD carrier hangs.",
    }

def audit_macos_python_arch() -> Dict[str, Any]:
    """
    Audits Python architecture on macOS.
    Detects native Apple Silicon arm64 vs Rosetta x86_64 emulation.
    """
    machine = _sys_platform_mod.machine()
    processor = _sys_platform_mod.processor()

    # Check for Rosetta translation
    is_rosetta = False
    try:
        res = subprocess.run(["sysctl", "-in", "sysctl.proc_translated"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip() == "1":
            is_rosetta = True
    except Exception:
        pass

    # Alternative check: x86_64 machine with arm64 hardware capability
    if not is_rosetta and machine == "x86_64":
        try:
            res = subprocess.run(["sysctl", "-in", "hw.optional.arm64"], capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip() == "1":
                is_rosetta = True
        except Exception:
            pass

    return {
        "machine": machine,
        "processor": processor,
        "is_arm64": machine == "arm64",
        "is_rosetta": is_rosetta,
    }
