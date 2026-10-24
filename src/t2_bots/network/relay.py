"""
Autonomous Headless Pinggy Cloud Relay Manager for t2-BOTS Robotics SDK.
Manages zero-install OpenSSH reverse tunnels across Windows, macOS, and Linux.
"""

import os
import sys
import time
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Any, Callable

@dataclass
class TunnelInfo:
    url: str
    host: str
    port: int
    local_port: int
    started_at: float
    max_duration_s: int = 3600  # 60 minutes session cap for free tier
    bytes_read: int = 0
    bytes_sent: int = 0
    active_connections: int = 0

class PinggyRelayManager:
    """
    Automated zero-install reverse tunnel controller via OpenSSH and Pinggy.
    """

    PINGGY_HOST = "a.pinggy.io"
    PINGGY_PORT = 443
    PINGGY_USER = "tcp"

    def __init__(self, local_port: int = 8765):
        self.local_port = local_port
        self.process: Optional[subprocess.Popen] = None
        self.tunnel_info: Optional[TunnelInfo] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._on_warning_cb: Optional[Callable[[str], None]] = None

    @staticmethod
    def is_openssh_available() -> bool:
        """Returns True if the OpenSSH client 'ssh' binary is on PATH."""
        return shutil.which("ssh") is not None

    @staticmethod
    def ensure_openssh_installed() -> bool:
        """
        Verifies OpenSSH availability, offering guided remediation for Windows if missing.
        """
        if PinggyRelayManager.is_openssh_available():
            return True

        if sys.platform.startswith("win"):
            print("⚠️ OpenSSH Client not found on Windows PATH.")
            print("To auto-enable OpenSSH on Windows 10/11, run PowerShell as Administrator:")
            print("   Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0")
        elif sys.platform.startswith("linux"):
            print("⚠️ OpenSSH Client not found. Install via: sudo apt install openssh-client")
        return False

    def start_tunnel(
        self,
        local_port: Optional[int] = None,
        timeout_s: float = 20.0,
        on_warning: Optional[Callable[[str], None]] = None,
    ) -> TunnelInfo:
        """
        Starts the reverse TCP tunnel to Pinggy Cloud Relay and waits for the public endpoint.
        """
        if local_port is not None:
            self.local_port = local_port

        if not self.is_openssh_available():
            raise RuntimeError(
                "OpenSSH client ('ssh') is not installed or not found on PATH. "
                "Please run 't2-bots bootstrap' or install OpenSSH."
            )

        if self.process is not None and self.process.poll() is None:
            if self.tunnel_info:
                return self.tunnel_info

        self._on_warning_cb = on_warning
        self._stop_event.clear()

        # Build OpenSSH reverse tunnel command
        # -p 443 tcp@a.pinggy.io -R0:localhost:<local_port>
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=" + ("NUL" if sys.platform.startswith("win") else "/dev/null"),
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "ExitOnForwardFailure=yes",
            "-p", str(self.PINGGY_PORT),
            f"-R0:localhost:{self.local_port}",
            f"{self.PINGGY_USER}@{self.PINGGY_HOST}",
        ]

        # Use non-interactive pipes
        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Parse output stream for public URL
        start_time = time.time()
        url_pattern = re.compile(r"tcp://([a-zA-Z0-9\.\-]+):(\d+)")
        endpoint_found = False
        startup_output = []

        while time.time() - start_time < timeout_s:
            if self.process.poll() is not None:
                remainder = self.process.stdout.read() if self.process.stdout else ""
                err_output = "".join(startup_output) + remainder
                raise RuntimeError(f"SSH process terminated unexpectedly (exit code {self.process.returncode}): {err_output}")

            line = self.process.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue

            startup_output.append(line)
            startup_output = startup_output[-30:]

            match = url_pattern.search(line)
            if match:
                full_host = match.group(1)
                port = int(match.group(2))
                full_url = f"tcp://{full_host}:{port}"
                self.tunnel_info = TunnelInfo(
                    url=full_url,
                    host=full_host,
                    port=port,
                    local_port=self.local_port,
                    started_at=time.time(),
                )
                endpoint_found = True
                break

        if not endpoint_found or not self.tunnel_info:
            self.stop_tunnel()
            raise TimeoutError(f"Failed to obtain public Pinggy endpoint within {timeout_s} seconds.")

        # Spawn background stream monitor for session telemetry & warnings
        self._monitor_thread = threading.Thread(target=self._monitor_stream, daemon=True)
        self._monitor_thread.start()

        return self.tunnel_info

    def _monitor_stream(self):
        """Monitors Pinggy telemetry output and session expiration."""
        stat_pattern = re.compile(r"RB:\s*(\d+),\s*SB:\s*(\d+),\s*TC:\s*(\d+),\s*AC:\s*(\d+)")
        warned_50m = False

        while not self._stop_event.is_set() and self.process and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if not line:
                    time.sleep(0.2)
                    continue

                # Parse live stats (Read Bytes, Sent Bytes, Active Connections)
                match = stat_pattern.search(line)
                if match and self.tunnel_info:
                    self.tunnel_info.bytes_read = int(match.group(1))
                    self.tunnel_info.bytes_sent = int(match.group(2))
                    self.tunnel_info.active_connections = int(match.group(4))

                # Check elapsed time for 60-min session cap
                if self.tunnel_info:
                    elapsed = time.time() - self.tunnel_info.started_at
                    if elapsed > 3000 and not warned_50m:  # 50 minutes
                        warned_50m = True
                        msg = "⚠️ Pinggy Free Tunnel will expire in 10 minutes (60-minute limit)."
                        if self._on_warning_cb:
                            self._on_warning_cb(msg)
                        else:
                            print(f"\n{msg}")

            except Exception:
                break

    def get_status(self) -> Dict[str, Any]:
        """Returns the current operational status of the tunnel."""
        if not self.process or self.process.poll() is not None:
            return {"status": "STOPPED", "active": False}

        if not self.tunnel_info:
            return {"status": "INITIALIZING", "active": True}

        elapsed = time.time() - self.tunnel_info.started_at
        remaining = max(0, self.tunnel_info.max_duration_s - int(elapsed))
        return {
            "status": "ONLINE",
            "active": True,
            "url": self.tunnel_info.url,
            "host": self.tunnel_info.host,
            "port": self.tunnel_info.port,
            "local_port": self.tunnel_info.local_port,
            "elapsed_s": int(elapsed),
            "remaining_s": remaining,
            "bytes_read": self.tunnel_info.bytes_read,
            "bytes_sent": self.tunnel_info.bytes_sent,
            "active_connections": self.tunnel_info.active_connections,
        }

    def stop_tunnel(self):
        """Cleanly stops the tunnel process and background monitor."""
        self._stop_event.set()
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        self.tunnel_info = None
