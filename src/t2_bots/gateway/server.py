"""
t2-BOTS Web Automation Gateway Server.
Provides Dual-Channel REST + WebSocket Interface for Web Apps & Automation.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from t2_bots.core.registry import get_robot, list_available_drivers
from t2_bots.core.schema import RobotAction
from t2_bots_so101.driver.port_resolver import list_candidate_ports

app = FastAPI(
    title="t2-BOTS Universal Robotics Gateway",
    version="0.1.0",
    description="Dual-channel REST & WebSocket automation interface for Physical AI robots.",
)

# Enable CORS for external Next.js/React frontends
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global active robot session state
_ROBOT: Optional[Any] = None
_TELEMETRY_SUBSCRIBERS: list[WebSocket] = []

class ConnectRequest(BaseModel):
    driver: str = "so101"
    port: str
    role: str = "follower"

class ActionRequest(BaseModel):
    target_positions: Dict[str, float]
    target_gripper: Optional[float] = None

class TorqueRequest(BaseModel):
    enabled: bool

@app.get("/api/v1/health")
def get_health():
    global _ROBOT
    return {
        "status": "ONLINE",
        "robot_connected": _ROBOT is not None and getattr(_ROBOT, "is_connected", False),
        "robot_name": getattr(_ROBOT, "name", None),
        "robot_port": getattr(_ROBOT, "port", None),
    }

@app.get("/api/v1/scan")
def scan_hardware():
    ports = list_candidate_ports()
    drivers = list_available_drivers()
    return {"ports": ports, "drivers": drivers}

@app.post("/api/v1/connect")
def connect_robot(req: ConnectRequest):
    global _ROBOT
    if _ROBOT is not None:
        try:
            _ROBOT.disconnect()
        except Exception:
            pass
    try:
        _ROBOT = get_robot(name=req.driver, port=req.port, role=req.role)
        _ROBOT.connect()
        return {"status": "CONNECTED", "driver": req.driver, "port": req.port}
    except Exception as e:
        _ROBOT = None
        raise HTTPException(status_code=500, detail=f"Connection failed: {e}")

@app.post("/api/v1/disconnect")
def disconnect_robot():
    global _ROBOT
    if _ROBOT is not None:
        try:
            _ROBOT.disconnect()
        except Exception:
            pass
        _ROBOT = None
    return {"status": "DISCONNECTED"}

@app.get("/api/v1/state")
def get_robot_state():
    global _ROBOT
    if _ROBOT is None or not getattr(_ROBOT, "is_connected", False):
        raise HTTPException(status_code=400, detail="Robot not connected")
    obs = _ROBOT.get_observation()
    return {
        "timestamp": obs.timestamp,
        "joints": obs.joint_positions,
        "gripper": obs.gripper_aperture,
        "latency_ms": obs.latency_ms,
    }

@app.post("/api/v1/action")
def send_action(req: ActionRequest):
    global _ROBOT
    if _ROBOT is None or not getattr(_ROBOT, "is_connected", False):
        raise HTTPException(status_code=400, detail="Robot not connected")
    action = RobotAction(
        target_positions=req.target_positions,
        target_gripper=req.target_gripper,
    )
    _ROBOT.send_action(action)
    return {"status": "ACTION_DISPATCHED"}

@app.post("/api/v1/torque")
def set_torque(req: TorqueRequest):
    global _ROBOT
    if _ROBOT is None or not getattr(_ROBOT, "is_connected", False):
        raise HTTPException(status_code=400, detail="Robot not connected")
    _ROBOT.set_torque(req.enabled)
    return {"status": "TORQUE_UPDATED", "enabled": req.enabled}

@app.post("/api/v1/safety/estop")
def emergency_stop():
    global _ROBOT
    if _ROBOT is not None:
        try:
            _ROBOT.set_torque(False)
            _ROBOT.disconnect()
        except Exception:
            pass
        _ROBOT = None
    return {"status": "ESTOP_TRIGGERED", "torque": "DISABLED"}

class HomeRequest(BaseModel):
    pose: str = "rest"
    duration_s: float = 2.5

@app.post("/api/v1/robot/home")
def go_home(req: HomeRequest):
    global _ROBOT
    if _ROBOT is None or not getattr(_ROBOT, "is_connected", False):
        raise HTTPException(status_code=400, detail="Robot not connected")
    if not hasattr(_ROBOT, "go_home"):
        raise HTTPException(status_code=400, detail="Robot does not support go_home")
    _ROBOT.go_home(pose=req.pose, duration_s=req.duration_s)
    return {"status": "HOMED", "pose": req.pose}

@app.get("/api/v1/certificate")
def get_certificate():
    cert_path = Path("/Users/mindflow/Lerobot Stack/lerobot-so101-mac/docs/FOLLOWER_ARM_COMPATIBILITY_CERTIFICATE.md")
    if cert_path.exists():
        return FileResponse(cert_path, media_type="text/markdown", filename="certificate.md")
    raise HTTPException(status_code=404, detail="Certificate not found")

@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """High-speed 60 Hz observational telemetry stream for 3D digital twins."""
    await websocket.accept()
    _TELEMETRY_SUBSCRIBERS.append(websocket)
    try:
        while True:
            if _ROBOT is not None and getattr(_ROBOT, "is_connected", False):
                try:
                    obs = _ROBOT.get_observation()
                    payload = {
                        "ts": obs.timestamp,
                        "joints": obs.joint_positions,
                        "grip": obs.gripper_aperture,
                        "lat_ms": round(obs.latency_ms, 2),
                    }
                    await websocket.send_text(json.dumps(payload))
                except Exception:
                    pass
            await asyncio.sleep(1.0 / 60.0)
    except WebSocketDisconnect:
        if websocket in _TELEMETRY_SUBSCRIBERS:
            _TELEMETRY_SUBSCRIBERS.remove(websocket)

@app.websocket("/ws/control")
async def ws_control(websocket: WebSocket):
    """Low-latency WebSocket channel for browser gamepads and real-time control."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if _ROBOT is not None and getattr(_ROBOT, "is_connected", False):
                try:
                    msg = json.loads(data)
                    action = RobotAction(
                        target_positions=msg.get("joints", {}),
                        target_gripper=msg.get("grip", None),
                    )
                    _ROBOT.send_action(action)
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    """Serves the standalone, embedded single-page Web App Dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>t2-BOTS Robotics Gateway</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
    h1 { margin-top: 0; color: #38bdf8; font-size: 24px; }
    .card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); border: 1px solid #334155; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .joint-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
    .joint-name { font-weight: 600; width: 140px; color: #94a3b8; }
    .joint-val { font-family: monospace; font-size: 16px; width: 80px; text-align: right; color: #38bdf8; }
    .slider { flex-grow: 1; margin: 0 16px; }
    button { background: #0284c7; color: white; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-right: 8px; }
    button:hover { background: #0369a1; }
    button.estop { background: #dc2626; }
    button.estop:hover { background: #b91c1c; }
    .badge { display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; background: #10b981; color: white; }
    .badge.offline { background: #ef4444; }
  </style>
</head>
<body>
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
    <div>
      <h1>⚡ t2-BOTS Web Automation Gateway</h1>
      <p style="color: #64748b; margin: 0;">Physical AI Hardware Abstraction Layer & Live Real-Time Controller</p>
    </div>
    <div>
      <span id="conn-badge" class="badge offline">DISCONNECTED</span>
      <button onclick="parkRobot()" style="background: #10b981; margin-right: 8px;">PARK / HOME</button>
      <button class="estop" onclick="triggerEStop()">EMERGENCY STOP</button>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>🔌 Hardware Connection</h3>
      <div style="margin-bottom: 12px;">
        <label style="display: block; font-size: 13px; color: #94a3b8;">Driver</label>
        <select id="driver-select" style="width: 100%; padding: 8px; background: #0f172a; color: white; border: 1px solid #334155; border-radius: 6px; margin-top: 4px;">
          <option value="so101">SO101 Follower Arm</option>
          <option value="so101_leader">SO101 Leader Arm</option>
        </select>
      </div>
      <div style="margin-bottom: 16px;">
        <label style="display: block; font-size: 13px; color: #94a3b8;">Serial Port</label>
        <input id="port-input" type="text" value="/dev/tty.usbmodem5C821078261" style="width: calc(100% - 18px); padding: 8px; background: #0f172a; color: white; border: 1px solid #334155; border-radius: 6px; margin-top: 4px;">
      </div>
      <button onclick="connectRobot()">Connect Arm</button>
      <button onclick="disconnectRobot()" style="background: #475569;">Disconnect</button>
    </div>

    <div class="card">
      <h3>📊 Observational Telemetry (60 Hz)</h3>
      <div id="joints-container">
        <p style="color: #64748b;">Connect arm to stream telemetry...</p>
      </div>
      <div style="margin-top: 16px; font-size: 13px; color: #64748b; display: flex; justify-content: space-between;">
        <span>Stream Latency: <strong id="latency-val" style="color: #38bdf8;">--</strong></span>
        <span>WebSocket: <strong id="ws-status" style="color: #10b981;">Connecting...</strong></span>
      </div>
    </div>
  </div>

  <script>
    let ws = null;
    function initWebSocket() {
      const loc = window.location;
      const wsUrl = (loc.protocol === "https:" ? "wss://" : "ws://") + loc.host + "/ws/telemetry";
      ws = new WebSocket(wsUrl);
      ws.onopen = () => { document.getElementById("ws-status").innerText = "Active"; };
      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        document.getElementById("latency-val").innerText = data.lat_ms + " ms";
        document.getElementById("conn-badge").className = "badge";
        document.getElementById("conn-badge").innerText = "CONNECTED (60 Hz)";
        
        let html = "";
        for (const [name, val] of Object.entries(data.joints)) {
          html += `<div class="joint-row"><span class="joint-name">${name}</span><div style="flex-grow: 1; background: #334155; height: 8px; border-radius: 4px; margin: 0 12px; overflow: hidden;"><div style="background: #38bdf8; height: 100%; width: ${(val + 180) / 3.6}%;"></div></div><span class="joint-val">${val.toFixed(1)}°</span></div>`;
        }
        const gripPct = (data.grip * 100).toFixed(1);
        html += `<div class="joint-row"><span class="joint-name">gripper</span><div style="flex-grow: 1; background: #334155; height: 8px; border-radius: 4px; margin: 0 12px; overflow: hidden;"><div style="background: #10b981; height: 100%; width: ${gripPct}%;"></div></div><span class="joint-val">${gripPct}%</span></div>`;
        document.getElementById("joints-container").innerHTML = html;
      };
      ws.onclose = () => {
        document.getElementById("ws-status").innerText = "Disconnected (Retrying)";
        document.getElementById("conn-badge").className = "badge offline";
        document.getElementById("conn-badge").innerText = "OFFLINE";
        setTimeout(initWebSocket, 2000);
      };
    }
    initWebSocket();

    async function connectRobot() {
      const driver = document.getElementById("driver-select").value;
      const port = document.getElementById("port-input").value;
      const res = await fetch("/api/v1/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ driver, port })
      });
      const data = await res.json();
      if (!res.ok) alert("Error: " + data.detail);
    }

    async function disconnectRobot() {
      await fetch("/api/v1/disconnect", { method: "POST" });
    }

    async function parkRobot() {
      const res = await fetch("/api/v1/robot/home", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pose: "rest", duration_s: 2.5 })
      });
      if (!res.ok) {
        const err = await res.json();
        alert("Park error: " + err.detail);
      }
    }

    async function triggerEStop() {
      await fetch("/api/v1/safety/estop", { method: "POST" });
      alert("⚠️ EMERGENCY STOP ACTIVATED: Torque killed and connection dropped.");
    }
  </script>
</body>
</html>
"""

def start_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    print(f"\n🚀 [t2-BOTS Gateway] Starting Web App Automation Server...")
    print(f"👉 Web Dashboard:    http://localhost:{port}/")
    print(f"👉 OpenAPI Docs:     http://localhost:{port}/docs")
    print(f"👉 WebSocket Stream: ws://localhost:{port}/ws/telemetry\n")
    uvicorn.run(app, host=host, port=port, log_level="info")
