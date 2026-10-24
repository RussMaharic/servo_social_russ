"""
Platform Bootstrap and Automated Driver Installer for t2-BOTS Universal Swarm SDK.
Supports zero-install bootstrapping across Linux, macOS, and Windows for SO-101 robotics.
"""

from __future__ import annotations

import getpass
import glob
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import importlib.util
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _get_stdlib_platform():
    """Safely loads standard library platform module without shadowing."""
    mod = sys.modules.get("platform")
    if mod and hasattr(mod, "machine") and hasattr(mod, "processor"):
        return mod
    stdlib_path = sysconfig.get_path("stdlib")
    spec = importlib.util.spec_from_file_location("_stdlib_platform", f"{stdlib_path}/platform.py")
    if spec and spec.loader:
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    import platform as fallback
    return fallback


_sys_platform_mod = _get_stdlib_platform()


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    ELEVATION_REQUIRED = "ELEVATION_REQUIRED"


@dataclass
class PlatformDiagnostic:
    """Represents a diagnostic result for a platform component."""
    name: str
    status: CheckStatus
    message: str
    remediation: Optional[str] = None
    elevation_required: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "remediation": self.remediation,
            "elevation_required": self.elevation_required,
            "details": self.details,
        }


@dataclass
class BootstrapReport:
    """Complete summary of platform diagnostics and bootstrap operations."""
    platform: str
    success: bool
    diagnostics: List[PlatformDiagnostic] = field(default_factory=list)
    elevation_commands: List[str] = field(default_factory=list)
    summary: str = ""

    def add(self, diag: PlatformDiagnostic) -> None:
        self.diagnostics.append(diag)
        if diag.elevation_required and diag.remediation:
            if diag.remediation not in self.elevation_commands:
                self.elevation_commands.append(diag.remediation)
        if diag.status in (CheckStatus.FAIL, CheckStatus.ELEVATION_REQUIRED):
            self.success = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "success": self.success,
            "summary": self.summary,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "elevation_commands": self.elevation_commands,
        }

    def print_report(self) -> None:
        symbols = {
            CheckStatus.PASS: "✔ [PASS]",
            CheckStatus.WARN: "⚠ [WARN]",
            CheckStatus.FAIL: "✖ [FAIL]",
            CheckStatus.ELEVATION_REQUIRED: "🔒 [ELEVATION REQUIRED]",
        }
        print("\n" + "=" * 64)
        print(f"🚀 t2-BOTS Platform Bootstrap Report ({self.platform})")
        print("=" * 64)
        for d in self.diagnostics:
            sym = symbols.get(d.status, f"[{d.status.value}]")
            print(f"\n{sym} {d.name}")
            print(f"    {d.message}")
            if d.remediation:
                print(f"    👉 Remediation: {d.remediation}")

        print("\n" + "-" * 64)
        if self.success:
            print("🎉 Platform Status: READY for SO-101 Robotics & Swarm Operations!")
        else:
            print("⚠️ Platform Status: ACTION REQUIRED before robotics hardware can be fully utilized.")
            if self.elevation_commands:
                print("\nTo apply necessary permissions/drivers with elevation, run:")
                for cmd in self.elevation_commands:
                    print(f"  {cmd}")
        print("=" * 64 + "\n")


# ============================================================================
# Linux Implementation: udev Rules & User Groups
# ============================================================================

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


def generate_udev_rules() -> str:
    """
    Generates the complete /etc/udev/rules.d/99-t2-so101.rules content
    covering CH340 (1a86:7523), FTDI (0403:6001), and CP210x (10c4:ea60).
    """
    lines = [
        "# t2-BOTS Universal Swarm SDK - SO-101 Robotic Arm & Teleoperation udev rules",
        "# Automatically grants non-root rw access to dialout and plugdev groups with systemd uaccess",
        "",
    ]
    for chip in SUPPORTED_CHIPSETS_LINUX:
        lines.append(f"# {chip['name']} ({chip['vid']}:{chip['pid']})")
        lines.append(
            f'SUBSYSTEM=="tty", ATTRS{{idVendor}}=="{chip["vid"]}", ATTRS{{idProduct}}=="{chip["pid"]}", '
            f'MODE="0666", GROUP="dialout", TAG+="uaccess"'
        )
        lines.append(
            f'SUBSYSTEMS=="usb", ATTRS{{idVendor}}=="{chip["vid"]}", ATTRS{{idProduct}}=="{chip["pid"]}", '
            f'MODE="0666", GROUP="plugdev", TAG+="uaccess"'
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def apply_linux_udev_and_groups(
    user: Optional[str] = None,
    elevate: bool = False,
    rules_path: Path = LINUX_UDEV_RULES_PATH,
) -> Dict[str, Any]:
    """
    Installs udev rules, reloads udev daemon, and adds user to dialout,plugdev.
    If not running as root and elevate is False, returns needed commands.
    """
    target_user = user or get_linux_target_user()
    is_root = os.geteuid() == 0 if hasattr(os, "geteuid") else False
    rules_content = generate_udev_rules()

    udev_reload_cmd = "udevadm control --reload-rules && udevadm trigger"
    usermod_cmd = f"usermod -a -G dialout,plugdev {target_user}"

    combined_cmd = (
        f"bash -c 'cat << \"EOF\" > {rules_path}\n{rules_content}EOF\n"
        f"{udev_reload_cmd} && {usermod_cmd}'"
    )

    if not is_root and not elevate:
        return {
            "success": False,
            "elevation_required": True,
            "remediation_cmd": f"sudo {combined_cmd}",
            "individual_cmds": [
                f"echo '<udev_rules>' | sudo tee {rules_path}",
                f"sudo {udev_reload_cmd}",
                f"sudo {usermod_cmd}",
            ],
            "message": "Root elevation required to write udev rules and configure group access.",
        }

    try:
        if is_root:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(rules_content, encoding="utf-8")
            subprocess.run(["udevadm", "control", "--reload-rules"], check=True, capture_output=True)
            subprocess.run(["udevadm", "trigger"], check=True, capture_output=True)
            subprocess.run(["usermod", "-a", "-G", "dialout,plugdev", target_user], check=True, capture_output=True)
        else:
            # Elevated execution via sudo
            subprocess.run(["sudo", "bash", "-c", f"cat << 'EOF' > {rules_path}\n{rules_content}EOF"], check=True)
            subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], check=True)
            subprocess.run(["sudo", "udevadm", "trigger"], check=True)
            subprocess.run(["sudo", "usermod", "-a", "-G", "dialout,plugdev", target_user], check=True)

        return {
            "success": True,
            "elevation_required": False,
            "message": f"Successfully installed {rules_path}, reloaded udev rules, and assigned {target_user} to dialout,plugdev.",
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "elevation_required": True,
            "remediation_cmd": f"sudo {combined_cmd}",
            "message": f"Failed executing configuration command: {e}",
        }


# ============================================================================
# macOS Implementation: Serial Audit & Python Architecture
# ============================================================================

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


# ============================================================================
# Windows Implementation: COM Ports & OpenSSH Client Capability
# ============================================================================

WINDOWS_HARDWARE_TARGETS = [
    {
        "name": "CH340 / CH341 USB to Serial",
        "hwid_pattern": "VID_1A86&PID_7523",
        "driver_inf": "CH341SER.INF",
    },
    {
        "name": "FTDI FT232R USB to Serial Bridge",
        "hwid_pattern": "VID_0403&PID_6001",
        "driver_inf": "FTDIPORT.INF",
    },
    {
        "name": "Silicon Labs CP210x USB to UART Bridge",
        "hwid_pattern": "VID_10C4&PID_EA60",
        "driver_inf": "SILABSER.INF",
    },
]

OPENSSH_CLIENT_CAPABILITY = "OpenSSH.Client~~~~0.0.1.0"


def check_windows_port_drivers() -> Dict[str, Any]:
    """
    Queries PowerShell `Get-PnpDevice -Class Ports` and audits devices
    matching CH340, FTDI, and CP210x hardware IDs for driver problems.
    """
    ps_cmd = (
        "Get-PnpDevice | Where-Object { "
        "($_.Class -eq 'Ports' -or $_.Class -eq 'Other') -and "
        "($_.HardwareID -match 'VID_1A86&PID_7523' -or "
        "$_.HardwareID -match 'VID_0403&PID_6001' -or "
        "$_.HardwareID -match 'VID_10C4&PID_EA60') "
        "} | Select-Object -Property FriendlyName, InstanceId, Status, Problem, ConfigManagerErrorCode, Class "
        "| ConvertTo-Json"
    )

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        output = res.stdout.strip()
        devices = []
        if output:
            parsed = json.loads(output)
            if isinstance(parsed, dict):
                devices = [parsed]
            elif isinstance(parsed, list):
                devices = parsed
    except Exception as e:
        devices = []

    missing_or_problem_drivers = []
    healthy_devices = []

    for dev in devices:
        status = str(dev.get("Status", "")).upper()
        problem = dev.get("Problem")
        err_code = dev.get("ConfigManagerErrorCode", 0)
        friendly_name = dev.get("FriendlyName", "Unknown USB Serial Device")

        is_healthy = status == "OK" and (problem == 0 or problem is None) and (err_code == 0 or err_code is None)
        if not is_healthy:
            missing_or_problem_drivers.append(dev)
        else:
            healthy_devices.append(dev)

    return {
        "devices": devices,
        "healthy_devices": healthy_devices,
        "problem_devices": missing_or_problem_drivers,
        "elevation_command": "pnputil /add-driver <inf_path> /install",
        "powershell_elevated_command": 'Start-Process powershell -Verb RunAs -ArgumentList "pnputil /add-driver <inf_path> /install"',
    }


def check_windows_openssh_capability() -> Dict[str, Any]:
    """
    Verifies OpenSSH Client capability (`OpenSSH.Client~~~~0.0.1.0`) on Windows.
    Provides automated installation command if missing.
    """
    ps_cmd = (
        f"Get-WindowsCapability -Online | Where-Object Name -like '{OPENSSH_CLIENT_CAPABILITY}*' "
        "| Select-Object -Property Name, State | ConvertTo-Json"
    )

    is_installed = False
    state_str = "Unknown"
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            check=True,
        )
        output = res.stdout.strip()
        if output:
            data = json.loads(output)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            state_str = str(data.get("State", "")).strip()
            is_installed = (state_str.lower() == "installed")
    except Exception as e:
        state_str = f"Error: {e}"

    install_cmd = f"Add-WindowsCapability -Online -Name {OPENSSH_CLIENT_CAPABILITY}"
    ps_elevated_cmd = f'Start-Process powershell -Verb RunAs -ArgumentList "{install_cmd}"'

    return {
        "capability": OPENSSH_CLIENT_CAPABILITY,
        "is_installed": is_installed,
        "state": state_str,
        "remediation_command": install_cmd,
        "powershell_elevated_command": ps_elevated_cmd,
    }


# ============================================================================
# Universal Guided Elevation & Platform Bootstrap Engine
# ============================================================================

def run_bootstrap(
    auto: bool = True,
    elevate: bool = False,
    interactive: bool = False,
    target_platform: Optional[str] = None,
) -> BootstrapReport:
    """
    Zero-install platform bootstrap and automated driver installer for t2-BOTS SDK.
    
    Args:
        auto: If True, automatically applies non-destructive configuration where possible.
        elevate: If True, executes root/admin privilege escalation (sudo / UAC RunAs).
        interactive: If True and elevation is needed, prompts user interactively.
        target_platform: Override for testing or cross-auditing ("linux", "darwin", "win32").
    """
    plat = target_platform or sys.platform
    report = BootstrapReport(platform=plat, success=True)

    # ------------------------------------------------------------------------
    # 1. Linux Operations
    # ------------------------------------------------------------------------
    if plat.startswith("linux"):
        # Audit udev rules
        rules_ok, missing_rules = check_linux_udev_rules()
        user = get_linux_target_user()
        groups_ok, present_groups, missing_groups = check_linux_user_groups(user)

        if rules_ok and groups_ok:
            report.add(PlatformDiagnostic(
                name="Linux udev Rules & Permissions",
                status=CheckStatus.PASS,
                message=f"Rules present in {LINUX_UDEV_RULES_PATH} and user '{user}' belongs to dialout,plugdev.",
            ))
        else:
            missing_desc = []
            if not rules_ok:
                missing_desc.append(f"udev rules missing for: {', '.join(missing_rules)}")
            if not groups_ok:
                missing_desc.append(f"user '{user}' not in groups: {', '.join(missing_groups)}")

            # Check if we should fix
            if auto and (elevate or (hasattr(os, "geteuid") and os.geteuid() == 0)):
                apply_res = apply_linux_udev_and_groups(user=user, elevate=elevate)
                if apply_res["success"]:
                    report.add(PlatformDiagnostic(
                        name="Linux udev Rules & Permissions",
                        status=CheckStatus.PASS,
                        message=apply_res["message"],
                    ))
                else:
                    report.add(PlatformDiagnostic(
                        name="Linux udev Rules & Permissions",
                        status=CheckStatus.ELEVATION_REQUIRED,
                        message=f"{'; '.join(missing_desc)}. Sudo elevation failed or required.",
                        remediation=apply_res.get("remediation_cmd"),
                        elevation_required=True,
                    ))
            else:
                apply_res = apply_linux_udev_and_groups(user=user, elevate=False)
                remediation = apply_res.get("remediation_cmd")
                if auto and interactive and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                    print(f"\n🔒 Linux udev rules and user groups need configuration:")
                    print(f"   {'; '.join(missing_desc)}")
                    try:
                        confirm = input("Run elevation command with sudo now? [y/N]: ").strip().lower()
                        if confirm in ("y", "yes"):
                            return run_bootstrap(auto=True, elevate=True, interactive=False, target_platform=plat)
                    except (EOFError, KeyboardInterrupt):
                        pass

                report.add(PlatformDiagnostic(
                    name="Linux udev Rules & Permissions",
                    status=CheckStatus.ELEVATION_REQUIRED,
                    message=f"{'; '.join(missing_desc)}. Root elevation required to apply.",
                    remediation=remediation,
                    elevation_required=True,
                    details={"missing_rules": missing_rules, "missing_groups": missing_groups},
                ))

    # ------------------------------------------------------------------------
    # 2. macOS Operations
    # ------------------------------------------------------------------------
    elif plat.startswith("darwin"):
        # A. Python Architecture Audit
        arch_res = audit_macos_python_arch()
        if arch_res["is_rosetta"]:
            report.add(PlatformDiagnostic(
                name="macOS Python Architecture Audit",
                status=CheckStatus.WARN,
                message=(
                    "WARNING: Python is executing under Rosetta 2 (x86_64 translation) on Apple Silicon. "
                    "This emulation causes timing jitter in high-frequency 60Hz USB teleoperation loops and "
                    "incompatibilities with native arm64 robotics wheels."
                ),
                remediation="Install native Apple Silicon Python: 'brew install python@3.12' or miniforge arm64.",
                elevation_required=False,
                details=arch_res,
            ))
        elif arch_res["is_arm64"]:
            report.add(PlatformDiagnostic(
                name="macOS Python Architecture Audit",
                status=CheckStatus.PASS,
                message="Native Apple Silicon (arm64) Python verified. Low-latency serial operations enabled.",
                details=arch_res,
            ))
        else:
            report.add(PlatformDiagnostic(
                name="macOS Python Architecture Audit",
                status=CheckStatus.PASS,
                message=f"Intel x86_64 native architecture detected ({arch_res['machine']}).",
                details=arch_res,
            ))

        # B. Serial Device Node Audit
        serial_res = audit_macos_serial_nodes()
        perm_issues = serial_res["permission_issues"]
        if perm_issues:
            nodes_str = ", ".join(perm_issues)
            chmod_cmd = f"sudo chmod 666 {' '.join(perm_issues)}"
            if elevate:
                try:
                    subprocess.run(["sudo", "chmod", "666"] + perm_issues, check=True)
                    report.add(PlatformDiagnostic(
                        name="macOS Serial Device Nodes & Permissions",
                        status=CheckStatus.PASS,
                        message=f"Granted rw permissions on {nodes_str}.",
                    ))
                except Exception as e:
                    report.add(PlatformDiagnostic(
                        name="macOS Serial Device Nodes & Permissions",
                        status=CheckStatus.ELEVATION_REQUIRED,
                        message=f"Elevation failed for nodes: {nodes_str}. Error: {e}",
                        remediation=chmod_cmd,
                        elevation_required=True,
                    ))
            else:
                report.add(PlatformDiagnostic(
                    name="macOS Serial Device Nodes & Permissions",
                    status=CheckStatus.ELEVATION_REQUIRED,
                    message=f"User lacks read/write permissions on serial nodes: {nodes_str}.",
                    remediation=chmod_cmd,
                    elevation_required=True,
                    details=serial_res,
                ))
        else:
            total_devs = serial_res["total_robot_nodes"]
            msg = f"Audited {total_devs} active USB-serial nodes (/dev/cu.* & /dev/tty.*). Permissions: RW OK. Note: {serial_res['note']}"
            report.add(PlatformDiagnostic(
                name="macOS Serial Device Nodes & Permissions",
                status=CheckStatus.PASS,
                message=msg,
                details=serial_res,
            ))

    # ------------------------------------------------------------------------
    # 3. Windows Operations
    # ------------------------------------------------------------------------
    elif plat.startswith("win"):
        # A. Detect Missing COM Port Drivers via PowerShell
        driver_res = check_windows_port_drivers()
        problem_devs = driver_res["problem_devices"]
        if problem_devs:
            dev_names = [d.get("FriendlyName", "USB Serial Device") for d in problem_devs]
            dev_str = ", ".join(dev_names)
            elevated_cmd = driver_res["powershell_elevated_command"]
            if elevate:
                try:
                    subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", elevated_cmd],
                        check=True,
                    )
                    report.add(PlatformDiagnostic(
                        name="Windows COM Port Drivers (CH340/FTDI/CP210x)",
                        status=CheckStatus.PASS,
                        message=f"Triggered elevated driver installation for: {dev_str}.",
                    ))
                except Exception as e:
                    report.add(PlatformDiagnostic(
                        name="Windows COM Port Drivers (CH340/FTDI/CP210x)",
                        status=CheckStatus.ELEVATION_REQUIRED,
                        message=f"Failed to elevate driver installer for: {dev_str}. Error: {e}",
                        remediation=elevated_cmd,
                        elevation_required=True,
                    ))
            else:
                report.add(PlatformDiagnostic(
                    name="Windows COM Port Drivers (CH340/FTDI/CP210x)",
                    status=CheckStatus.ELEVATION_REQUIRED,
                    message=f"Drivers missing or misconfigured for {dev_str}.",
                    remediation=elevated_cmd,
                    elevation_required=True,
                    details=driver_res,
                ))
        else:
            report.add(PlatformDiagnostic(
                name="Windows COM Port Drivers (CH340/FTDI/CP210x)",
                status=CheckStatus.PASS,
                message="All CH340, FTDI, and CP210x COM port drivers are installed and functioning normally.",
                details=driver_res,
            ))

        # B. Verify OpenSSH Client Capability
        ssh_res = check_windows_openssh_capability()
        if not ssh_res["is_installed"]:
            elevated_ssh_cmd = ssh_res["powershell_elevated_command"]
            if elevate:
                try:
                    subprocess.run(
                        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", elevated_ssh_cmd],
                        check=True,
                    )
                    report.add(PlatformDiagnostic(
                        name="Windows OpenSSH Client Capability",
                        status=CheckStatus.PASS,
                        message=f"Installed {OPENSSH_CLIENT_CAPABILITY} with administrator privileges.",
                    ))
                except Exception as e:
                    report.add(PlatformDiagnostic(
                        name="Windows OpenSSH Client Capability",
                        status=CheckStatus.ELEVATION_REQUIRED,
                        message=f"Elevation failed while installing OpenSSH Client: {e}",
                        remediation=elevated_ssh_cmd,
                        elevation_required=True,
                    ))
            else:
                report.add(PlatformDiagnostic(
                    name="Windows OpenSSH Client Capability",
                    status=CheckStatus.ELEVATION_REQUIRED,
                    message=f"OpenSSH Client capability ({OPENSSH_CLIENT_CAPABILITY}) is not installed.",
                    remediation=elevated_ssh_cmd,
                    elevation_required=True,
                    details=ssh_res,
                ))
        else:
            report.add(PlatformDiagnostic(
                name="Windows OpenSSH Client Capability",
                status=CheckStatus.PASS,
                message=f"OpenSSH Client capability ({OPENSSH_CLIENT_CAPABILITY}) is installed and ready.",
                details=ssh_res,
            ))

    else:
        report.add(PlatformDiagnostic(
            name="Platform Support",
            status=CheckStatus.WARN,
            message=f"Unsupported or unrecognized operating system: {plat}",
        ))

    report.summary = (
        "All platform checks passed successfully!"
        if report.success
        else f"Platform setup incomplete ({len(report.elevation_commands)} elevation command(s) pending)."
    )
    return report


def main() -> None:
    """CLI entrypoint for standalone platform bootstrap."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="t2-platform-bootstrap",
        description="t2-BOTS Universal Swarm SDK Platform Bootstrap & Driver Installer",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        default=True,
        help="Automatically apply non-destructive fixes where possible (default: True)",
    )
    parser.add_argument(
        "--no-auto",
        action="store_false",
        dest="auto",
        help="Dry-run audit mode without making modifications",
    )
    parser.add_argument(
        "--elevate",
        action="store_true",
        default=False,
        help="Prompt and execute elevated administrator/root commands (sudo/UAC)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output diagnostics in JSON format for automated tooling",
    )
    args = parser.parse_args()

    report = run_bootstrap(auto=args.auto, elevate=args.elevate, interactive=True)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        report.print_report()

    sys.exit(0 if report.success else 1)


if __name__ == "__main__":
    main()
