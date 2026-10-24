# t2 Connect: onboarding, local hardware and shared followers

For the Supabase + Render + Vercel deployment, follow [CLOUD-SETUP.md](CLOUD-SETUP.md).
It supersedes the older SQLite-only deployment instructions below. The hosted
directory now supports private Supabase Postgres via the `directory` extra;
local development can continue using SQLite. No cloud deployment is claimed yet.

The browser workspace guides users through installation, a unique username,
USB selection, measured motor inspection, calibration, qualification and remote
follower discovery. There are no email/password accounts or fictional devices.

## Register and use your pair

Open **My arms** to register one leader and one follower on this computer.
Give each a name and select its own USB controller. Complete inspection,
calibration and qualification for each; their profiles and certificates stay
separate, and adding the second arm preserves the first arm's setup.

After follower qualification, **Share my follower** explicitly opens its
PIN-protected listener and publishes it to the configured community directory.
The directory contains owner-added, owner-shared followers. The leader can
select its own follower or another owner's available SO-101 follower. Its own
listener PIN is reused locally; another owner's PIN is entered privately.
Connecting sends no movement targets; following still needs explicit enabling.

Leader control and follower sharing run independently on separate USB ports.
You can offer your follower while your leader controls a different follower.
Disconnect my leader and Stop sharing my follower operate separately. Stopping
a local follower also ends any leader connected to that follower; it does not
stop an outgoing leader connection to another arm. Each follower accepts one
operator at a time. The owner can stop sharing whenever needed. Both computers
must use the updated directory/companion for same-computer pair connections.

## Installation detection and older versions

A responding localhost service proves only that a process is running. It does
not prove a download, desktop installation or current SDK. The workspace now
checks the service's actual version, SDK version, API revision, build identity
and runtime dependencies. An old or incompatible service stays on the install
step with update instructions and cannot unlock hardware operations.

A source-launched service is labelled **Running from project source**. The user
can explicitly confirm using that compatible runtime, or download a packaged
app. Detection alone never completes installation. Confirmation is bound to
version, build and runtime kind; changing those requires confirmation again.
Usernames, profiles, controller bindings and certificates are not deleted.

Windows, macOS and Linux each have an installation tab. The Windows portable
app bundles Python. Source downloads support all three; macOS (Apple Silicon
and Intel) and Linux currently use the source launcher and need Python 3.10+.
The UI links to Python and matching driver vendors only when relevant, shows
OpenSSH as optional for LAN/VPN and required for Pinggy, and offers read-only
platform audits. No native Mac/Linux app is claimed unless that artifact exists.

Stop active following and close the old companion before updating. The launcher
does not reuse an older process just because it responds on the expected port.
It asks you to close that version and reopen the current one instead.

## Run from this checkout

Windows: double-click `Start t2 Connect.cmd`. It installs the source with the
gateway extra into `.venv`, then opens the companion workspace. Python 3.10+
and internet access for dependencies are needed on the first source install.
On macOS/Linux run `bash scripts/start-connect.sh`.

For development:

```text
python -m pip install -e ".[gateway,dev]"
t2-connect
```

The companion binds to `127.0.0.1:4840`. It requires same-origin requests, validates
Host, and protects writes with an in-memory browser session token. It does not
enable the older gateway's permissive public control endpoints. Do not expose
the companion through a public proxy. `--port` changes its local port and
`--no-browser` suppresses automatic browser opening.

Start the community directory separately:

```text
t2-directory --port 8090
```

Enter `http://127.0.0.1:8090` in the username step's directory setting for local
development. For real independent workstations, deploy a shared HTTPS directory
and use that same address on both. The directory is required to claim a globally
unique username. A device key stored locally proves ownership on later visits.
Clearing browser data does not remove the key. Losing the key means an existing
username cannot be reclaimed by simply typing it again; back up station data.

## Onboard actual arms

1. Choose leader or follower and confirm the actual USB adapter. An adapter alone
   is not proof of a robot; all six motors must pass measured inspection.
2. Support the arm and start calibration. This releases torque with readback
   verification. Record the canonical rest reference (base 0°, shoulder -90°,
   elbow +90°, wrist flex +90°, wrist roll 0°, gripper closed), then gently move
   each joint through a comfortable range. Review and save. No targets are sent.
3. Each joint must show at least 120 ticks of travel for capture to save, with
   30-tick bounds removed at each end. This is a software acceptance threshold,
   not proof of full mechanical travel. Never force a joint. Cancellation,
   an encoder jump, missing reads or browser loss ends capture.
4. Qualification requires explicit confirmation. Every motor must satisfy power,
   temperature and error checks. The follower shoulder limit may be updated to
   3300 ticks. Qualification primes current holding targets, briefly verifies
   all six torque registers, then releases and verifies torque. A failure does
   not issue a passing record. The JSON certificate uses the SDK README schema.
5. Enter the dashboard. On a follower station, explicitly share a listener and
   optionally let the SDK create a Pinggy public address. Share the displayed PIN
   privately. On a leader station, select a listed follower and enter that PIN.
6. Connecting reads state without enabling motion. A separate enable action
   anchors relative joint tracking to both arms' current poses. Targets are
   clamped to measured ranges and limited to 30°/s, with a nominal maximum
   software loop of 60 Hz. Actual throughput depends on serial/network latency.

One leader and one follower can run on separate controllers in the same
companion. Their session engines and profiles are independent; follower sharing
can stay active while the leader controls another arm. The swarm CLI is separate.

The browser session protocol is `t2-connect/1`. Both stations need this companion;
it reuses SDK servo transport, packets, certificate schema and Pinggy management,
but does not connect to legacy `t2-bots peer` listeners, which enable motion on
their first trajectory packet. This distinction preserves explicit UI enabling.

The directory provides atomic, expiring reservations for cooperating clients.
The actual follower independently accepts only one authenticated operator at a
time. Sharing/listening does not enable torque. Network silence over 0.5 seconds
triggers release; loss of browser heartbeat over five seconds ends local sessions.
Timing is best effort and can be delayed by serial/network I/O or OS scheduling.
Stop releases torque: support the arm. If release cannot be verified the error
is reported; a software stop cannot guarantee release after a hardware failure.

## Persistence

The default data directory is `~/.config/t2_bots/connect`; `T2_CONNECT_HOME`
overrides it for tests or isolated stations. It holds device credentials,
controller bindings, certificates and saved calibration. Previous calibration
versions are backed up before replacement. The companion uses its own explicit
profile path, so qualification does not overwrite captured ranges or LeRobot
cache profiles. Back up this directory privately; never distribute station.json.

Qualification is a locally generated hardware report, valid for 30 days. Its
SDK hash detects ordinary modification but uses a public SDK salt and is not
proof of an independent authority's inspection. The directory does not establish
physical safety or identity from a username or certificate alone. PINs are never
published. Use a trusted private network or protected transport: a `ws://` public
address is not end-to-end TLS merely because Pinggy uses SSH on one tunnel leg.

## Build downloads

```text
python -m build --outdir build/packages
python scripts/build-connect-release.py --directory-url https://YOUR-DIRECTORY.onrender.com
```

The second command creates a source download and updates release metadata. For
a self-contained Windows app, build on Windows with PyInstaller installed:

```text
python -m pip install pyinstaller
python scripts/build-connect-release.py --windows --directory-url https://YOUR-DIRECTORY.onrender.com
```

Windows users extract the resulting ZIP and open `t2-Connect.exe`; Python is
bundled. This is a portable unsigned app, not a signed native installer. Test it
on a clean Windows computer before distributing publicly. macOS/Linux have the
source launcher; standalone macOS packages are not claimed or offered.

Downloads are generated under `src/t2_bots/connect/static/downloads/` and ignored
by Git. CI or a local build must generate them before deploying the static site,
or release.json must point to real hosted GitHub Release artifacts. Do not publish
metadata advertising absent files. No GitHub Release is created automatically.

## Deploy

**Render:** Connect this repo and select `render.yaml`. It defines one paid web
service with a persistent disk. The database path is `/var/data/directory.sqlite3`.
The service runs the directory only, never serial hardware or the companion.
Check `/healthz`. This file describes paid infrastructure; applying it is a
separate owner action. A free ephemeral disk loses username ownership on restart.
Before scaling past one instance, migrate SQLite and reservation transactions
to shared storage.

**Vercel:** Import the repo with framework **Other**, no install/build step, and
output directory `src/t2_bots/connect/static`. Root `vercel.json` sets these
defaults. Generate/download release artifacts before deployment. Set the actual
Render URL in `release.json` or pass it to the release builder. On the hosted page,
Open local workspace hands off to loopback; it does not contact local hardware
directly from the public origin. No user accounts or service-role keys belong
in the frontend assets. This implementation does not deploy or provision services.

## Verify

```text
python -m pytest -q
node --test tests/frontend.test.cjs
node --test tests/frontend_audit.test.cjs
python scripts/check-connect-release.py
```

Tests use fake motor buses, temporary databases and loopback WebSocket sessions.
They do not establish physical behavior, worldwide latency or clean-machine
installation. Validate the full leader/follower flow on real hardware before use.

## Hosting credentials and production handoff

| Component | Runtime key required? | Configuration |
| --- | --- | --- |
| Vercel static download site | No | Deploy the built static folder and its actual ZIP downloads. |
| Render directory service | No vendor API key | One persistent disk and `T2_DIRECTORY_DB=/var/data/directory.sqlite3`. |
| Supabase | No | This project uses SQLite and has no Supabase dependency or Auth integration. |
| Companion identity | Generated automatically | Private device credential stays in the local station folder; users only choose a username. |

Vercel/Render account authorization is needed to deploy. CI deployment tokens,
if used, belong in CI/platform secret settings, never frontend files or chat.
No deployment has been performed by this audit. Both stations need the same
public HTTPS directory URL for real remote discovery; localhost is development.
Build with `--directory-url https://YOUR-DIRECTORY.onrender.com`, then run:

```text
python scripts/check-connect-release.py --production
```

The check rejects absent ZIPs, mismatched build metadata, private station data
inside source archives, and a missing public directory URL. A plain Git checkout
does not contain ignored generated downloads, so build/upload them before
deploying. Do not add Supabase keys to solve a directory configuration issue.

Updates can be staged with `--desktop-dir build/connect-release/staged-desktop`
while the current companion continues running. Replace/restart it only while
idle. A refreshed local manifest lets an outdated tab reload the matching UI;
it does not automatically approve a changed runtime or enable motion.

The audit's newly generated unsigned Windows executable was blocked on this PC
with `WinError 4551` (Application Control). It was not activated and no Windows
security setting was changed. The user selected the documented source launcher
for development. The new native binary remains a release candidate; distribution
needs trusted code signing and a clean-machine installation test. Source mode
is labelled explicitly and does not ask for another download when its required
Python components are already present.

Calibration shows measured joint progress and enables Review & save only after
the rest reference and all six minimum travel checks are complete. Inspection
results remain for the selected controller; calibration still performs a fresh
hardware check. Capture errors stay visible across polling and multiple tabs.
Nonzero motor-status flags pause measurement and preserve the reference/ranges.
The pause shows and logs the motor, raw flag, encoder position, voltage and
temperature. Recheck motors & continue performs a fresh six-motor inspection;
it does not clear flags, enable torque or send movement targets. Save remains
blocked until the fault is resolved. Passive calibration tolerates a 20-second
browser gap; powered sessions still use the five-second browser watchdog.

Source releases now use a version/build-specific download filename. The build
also writes the current source ZIP, Python wheel, and a SHA256SUMS file to
`dist/`, preserving previous releases. The source ZIP includes `START-HERE.txt`
with Windows, macOS and Linux launch/update instructions. Its embedded build
metadata matches the download page. The legacy `t2-connect-source.zip` URL is
updated for existing tabs; new manifests advertise the build-specific ZIP.
