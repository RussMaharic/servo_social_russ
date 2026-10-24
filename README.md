# servo_social_russ

> **Connect, Certify, and Teleoperate SO-101 Arms Across the World in Under 60 Seconds.**

[![Release](https://img.shields.io/github/v/release/RussMaharic/servo_social_russ?color=brightgreen&label=version)](https://github.com/RussMaharic/servo_social_russ/releases)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20Apple%20Silicon%20%7C%20Linux-orange)](https://github.com/RussMaharic/servo_social_russ)
[![Tests](https://img.shields.io/badge/tests-82%20passed-success)](https://github.com/RussMaharic/servo_social_russ)

---

## 1. Welcome to t2-BOTS Teleop

Welcome to the **t2-BOTS Teleop** community distribution. 

This repository provides zero-install tools to control **SO-101 robotic arms** over the public internet. You can connect arms located in different cities or on different Wi-Fi routers. 

### New: Guided browser workspace (v0.3.1 source)

Open **Start t2 Connect.cmd** on Windows, or run `bash scripts/start-connect.sh`
on macOS/Linux. The source launcher needs Python 3.10+; the generated portable
Windows app bundles Python. The workspace opens at **http://127.0.0.1:4840/**.

The flow is **install → choose a unique username → detect USB → inspect motors
→ calibrate → browse shared followers → connect → explicitly enable**.
No email, password or login screen is required. Users need a shared directory
address; for development, run `t2-directory --port 8090` on localhost.

Each computer can register **one leader and one follower** under **My arms**.
Add your own controllers, then inspect and calibrate each arm separately.
Adding a follower keeps your existing leader calibration. Calibrated followers
appear in the directory only after their owner explicitly shares them.
Your leader can connect to your own shared follower or another owner's available
SO-101 follower. The same computer can share its follower while its leader
controls a different arm. Each leader has one active connection; each follower
accepts one operator. Connecting stays read-only until following is enabled.

The installation step supports **Windows, macOS and Linux**. A running service
is labelled by its actual version and launch mode; a source process is not
presented as proof of a desktop installation. Older/incompatible companions
must be updated, and a compatible runtime must be explicitly confirmed before
setup continues. See the platform tabs for required downloads and prerequisites.

See the [frontend and hosting guide](docs/FRONTEND.md) for Vercel, Render, download
packaging, data persistence and current limits. Both remote stations need the
new companion. The original `dist/` wheel remains v0.2.0; install the source to
use this interface. Hosting has not been deployed by adding these files.

For the simplest $0 pilot without Supabase, follow the
[Render Free + Vercel guide](docs/RENDER-FREE-SETUP.md). It runs with SQLite;
directory registrations reset whenever Render's free instance restarts.

For cloud setup with the prepared Supabase project, use the
[SQL and environment setup guide](docs/CLOUD-SETUP.md). It includes the private
database schema, Render-only connection secret, and Vercel's public directory URL.

For the quickest pilot deployment, use the
[Railway + Vercel guide](docs/RAILWAY-SETUP.md). It needs no Supabase keys: attach
a Railway volume, generate its public domain, and give that URL to Vercel.

```
                                      PUBLIC INTERNET
[ Leader Station ] <=========> [ Pinggy Cloud Relay ] <=========> [ Follower Station ]
 Windows / Mac / Linux               (Port 443 TCP)                 Windows / Mac / Linux
 60 Hz Teleop Trajectory                                           12.4V Holding Torque
 Gated PIN Handshake                                               1:1 Joint Tracking
```

---

## 2. What Can It Do Today? (Live Capabilities Matrix)

Every feature in the table below is built, tested, and ready to run:

| Capability | Feature Description | CLI Command |
| :--- | :--- | :--- |
| **Zero-Install Bootstrap** | Auto-detects serial adapters, installs Linux udev rules, and checks macOS / Windows drivers. | `t2-bots bootstrap` |
| **Hardware Certification** | Unlocks Motor 2 limits (3300 ticks), checks 12V bus power, and signs a SHA-256 certificate. | `t2-bots certify` |
| **1:1 Remote Teleoperation** | Streams 60 Hz joint angles across separate Wi-Fi routers using encrypted cloud tunnels. | `t2-bots peer` |
| **Autonomous Cloud Relay** | Starts and manages zero-install OpenSSH reverse tunnels without third-party client software. | `t2-bots relay` |
| **One-to-Many Swarm Teleop** | One Leader controls multiple Follower arms worldwide with operator admission control. | `t2-bots swarm` |
| **Isolated Deadman Safety** | Quarantines a lagging follower without stopping healthy arms in the fleet. | Automatic |

---

## 3. Hardware Checklist

Prepare the items below before you start:

1. **SO-101 Robot Arm**:
   * Leader arm (passive tracking console) or Follower arm (active motor unit).
2. **Actuators**:
   * 6 $\times$ Feetech STS3215 bus servos.
3. **USB Serial Adapter**:
   * Waveshare Bus Servo Adapter, CH340, FTDI, or CP210x serial interface.
4. **Power Supply**:
   * 12.0V DC (5A minimum recommended) for Follower arms.
   * 5.0V USB power or 12.0V DC for Leader arms.

---

## 4. Rapid Installation (Zero Dependencies)

Open your terminal or command prompt. Run the command for your operating system:

### macOS & Linux (Ubuntu / Debian / Raspberry Pi)
```bash
curl -sSL https://raw.githubusercontent.com/RussMaharic/servo_social_russ/main/scripts/install.sh | bash
```
Then activate the environment:
```bash
source ~/t2_bots_teleop/.venv/bin/activate
```

### Windows 10 & Windows 11 (PowerShell)
```powershell
irm https://raw.githubusercontent.com/RussMaharic/servo_social_russ/main/scripts/install.ps1 | iex
```
Then activate the environment:
```powershell
~\t2_bots_teleop\.venv\Scripts\Activate.ps1
```

### Manual Installation via Pip
If you downloaded this repository directly:
```bash
python3 -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install dist/t2_bots-0.2.0-py3-none-any.whl
```

---

### Developing from Source

The editable Python packages live in `src/t2_bots/` (SDK and CLI) and
`src/t2_bots_so101/` (SO-101 driver). They were recovered unchanged from the
bundled v0.2.0 wheel. `pyproject.toml` defines installation and packaging;
`dist/` retains the original release wheel.

Create and activate a virtual environment as shown above, then install the
source in editable mode so code changes take effect without rebuilding:

```bash
python -m pip install -e ".[dev]"
t2-bots --help
```

For the optional web gateway, install `python -m pip install -e ".[dev,gateway]"`.
Build a wheel and source archive with:

```bash
python -m build --outdir build/packages
```

Builds go into `build/packages/` to preserve the bundled release in `dist/`.
The upstream test suite mentioned in the documentation was not included in
this repository or wheel; installing the test dependencies does not restore it.

---

## 5. Mission 1: Qualify & Certify Your Arm

The Connect dashboard requires saved calibration for each arm. Certification is not required to share or connect; the optional legacy CLI qualification command is described below.

### Step 1: Run the Hardware Certification Command
Connect your arm USB cable and power supply. Run:
```bash
t2-bots certify --arm follower
```
*(On a Leader arm, replace `follower` with `leader`).*

### What This Command Does:
1. Pings all 6 servo motors over the serial bus.
2. Checks that bus voltage is at least 11.5V for holding torque.
3. Unclamps Motor 2 (`shoulder_lift`) from 2659 ticks to 3300 ticks (+56.3° forward reach).
4. Sets 30-tick soft safety clearance off mechanical hard stops.
5. Saves a signed cryptographic certificate:
   `~/.config/t2_bots/certificates/<ARM_ID>_qualification.json`

### Expected Terminal Output:
```text
=======================================================
🎯 Hardware Qualification Certificate Issued
   Arm ID:       SO101-FOL-5C821078261
   Role:         follower
   Power Rail:   12.4V (Healthy)
   Motor 2:      UNLOCKED (3300 ticks)
   Clearance:    30 ticks
   Grade:        A+ (100% Qualified)
   SHA-256:      8f4a2b91c0e34f71a9...c4b2
=======================================================
```

---

## 6. Mission 2: Drive an Arm Over the Public Internet (1-to-1)

Use this flow when the Leader and Follower are on **different Wi-Fi routers** or in **different locations**.

```
[ Leader Arm (Windows) ]                                [ Follower Arm (Mac) ]
         |                                                        |
         |                                                        | 1. Starts Follower Daemon:
         |                                                        |    t2-bots peer listen --auto --pin 123456
         |                                                        |
         |                                                        | 2. Starts Autonomous Relay:
         |                                                        |    t2-bots relay start --port 8765
         |                                                        |    -> tcp://fbrky-arm.run.pinggy.link:45937
         |
         | 3. Connects via Public Link:
         |    t2-bots peer connect --auto --host fbrky-arm.run.pinggy.link:45937 --pin 123456
         |
         +==================== AUTHENTICATED 60 Hz TELEOP ====================+
         |                                                                    |
         v                                                                    v
   Tracks 1:1 Angle                                                  Engages 12.4V Torque
```

### Station B: Follower Workstation (e.g. Mac / Linux)

#### Terminal 1 — Start the Follower Daemon:
```bash
t2-bots peer listen --auto --listen-port 8765 --pin 123456
```

#### Terminal 2 — Start the Public Tunnel:
```bash
t2-bots relay start --port 8765
```
Copy the generated public address from the output:
```text
✔ Public Relay Live: tcp://fbrky-2401-4900-1cb9-25bb.run.pinggy-free.link:45937
```

---

### Station A: Leader Workstation (e.g. Windows)

Connect your Leader arm to your computer. Run:
```powershell
t2-bots peer connect --auto --host fbrky-2401-4900-1cb9-25bb.run.pinggy-free.link:45937 --pin 123456
```

### What Happens:
1. Leader arm authenticates using Gated PIN `123456`.
2. Both arms synchronize to rest position ($0.0^\circ$ disparity).
3. Follower engages 12.4V holding torque.
4. Move your Leader arm. The remote Follower mirrors every movement in real time!

---

## 7. Mission 3: Drive an Entire Fleet ("One-to-Many Movement")

In Swarm Mode, **one Leader operator** controls multiple remote Follower arms simultaneously.

```
                                    +---> Follower #1 (Lab A, Tokyo)
                                    |     [Admitted: Grade A+, 12.4V]
[ Leader Station ] === Swarm Hub ===+
(Hosts Broadcast)                   +---> Follower #2 (Lab B, London)
                                    |     [Admitted: Grade A+, 12.3V]
                                    |
                                    +---> Follower #3 (Production, New York)
                                          [Admitted: Grade A+, 12.4V]
```

### 1. Leader Workstation: Host the Swarm Hub
```bash
t2-bots swarm host --auto --pin 888999 --relay
```
The Swarm Hub starts and opens a public tunnel automatically.

### 2. Follower Workstations: Join the Swarm
Each remote follower connects to the Leader Hub:
```bash
# Follower 1 (Lab A)
t2-bots swarm join --auto --host tcp://<HUB_URL>:<PORT> --pin 888999 --name "Lab-A"

# Follower 2 (Lab B)
t2-bots swarm join --auto --host tcp://<HUB_URL>:<PORT> --pin 888999 --name "Lab-B"
```

### 3. Leader Console: Interactive Admission Gate
When a follower requests connection, the Leader console prompts the operator:
```text
========================================================================
🔔 [SWARM ADMISSION REQUEST] Incoming Follower Arm:
   Name:     Lab-A
   Arm ID:   SO101-FOL-5C821078261
   Voltage:  12.4V (Grade A+ Certified)
👉 Grant teleoperation admission to this Follower? [Y/n]: y
========================================================================
✔ [SWARM ADMITTED] Follower 'Lab-A' joined! Active fleet: 1 arm
```
Type `y` and press Enter. The follower joins the broadcast group!

### 4. Isolated Deadman Safety
If one follower experiences Wi-Fi lag ($>150\text{ms}$) or a voltage drop ($<11.0\text{V}$):
* Only that degraded arm enters safe-hold.
* All other healthy follower arms continue moving smoothly at 60 Hz.

---

## 8. Flight Surgeon Runbook (Troubleshooting)

### Problem 1: "Permission Denied" on Serial Port (Linux)
* **Cause**: Your user account is not in the `dialout` or `plugdev` group.
* **Correction**:
  ```bash
  t2-bots bootstrap --elevate
  ```
  Or run manually:
  ```bash
  sudo usermod -aG dialout,plugdev $USER
  ```
  Log out and log back in to apply group changes.

### Problem 2: Follower Fails Certification with Low Voltage
* **Cause**: 12V power supply is disconnected or delivers less than 11.5V.
* **Correction**: Plug in the external 12V 5A power brick into the motor bus board. Do not run follower motors on 5V USB power alone.

### Problem 3: Motor 2 Will Not Reach Past ~55°
* **Cause**: Factory EEPROM register `0x0B` is restricted to 2659 ticks.
* **Correction**:
  ```bash
  t2-bots certify --arm follower
  ```
  The tool automatically unlocks the EEPROM register to 3300 ticks.

### Problem 4: Pinggy Free Tunnel Session Expired
* **Cause**: Unauthenticated reverse tunnels close after 60 minutes.
* **Correction**: Stop the relay and start a new session:
  ```bash
  t2-bots relay start --port 8765
  ```
  Share the new port number with the Leader station.

---

## 9. Documentation Reference

Detailed technical documentation and operational playbooks are included in the repository:

* **[Comprehensive User Manual](docs/USER_MANUAL.md)**: Master architecture, CLI reference, calibration offsets, and kinematics.
* **[Platform Bootstrap Playbook](docs/playbooks/01_platform_bootstrap.md)**: Zero-install driver verification.
* **[Certification Engine Playbook](docs/playbooks/02_certification_engine.md)**: EEPROM unclamp and SHA-256 certificate schema.
* **[Cloud Relay Playbook](docs/playbooks/03_teleop_cloud_relay.md)**: OpenSSH reverse tunnel management.
* **[Swarm Teleop Playbook](docs/playbooks/04_one_to_many_swarm.md)**: 1-to-N broadcast and isolated deadman safety.
* **[CI/CD & DevOps Playbook](docs/playbooks/05_devops_ci_cd.md)**: Multi-OS regression testing standards.

---

## 10. Community & Contributing

Contributions are welcome! If you find a bug or build an exciting demo with your SO-101 arm, please open an issue or submit a pull request.

* **License**: Apache 2.0 (Open Source & Permissive)
* **Author**: Ronie Joseph & t2-BOTS Authors
