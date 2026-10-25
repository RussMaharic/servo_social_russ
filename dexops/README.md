# Dexops

The maintained Dexops application lives in this folder, inside the existing Git
repository. It contains the browser workspace, local robot companion, shared
follower directory, and only the SO-101 support code those components use.

The app still supports Windows, macOS, and Linux; username-only onboarding;
one leader and one follower per computer; guided calibration; follower sharing;
explicit movement enabling; and bounded reconnection after temporary link loss.
The robot workflow, wire protocol, version, and saved-data location are retained.

## Start locally

Install Python 3.10 or newer. From this folder on Windows:

```powershell
py scripts/setup-dexops.py
```

On macOS or Linux:

```bash
bash scripts/start-connect.sh
```

The source launchers register this checkout and open the hosted Dexops workspace.
Healthy environments are reused; ordinary starts do not run pip. Installation
metadata and environments live in `~/.dexops/`, separate from your station data.
The companion runs in the background; terminal closure does not stop it.

In a **new terminal** after setup:

```text
dexops
dexops update
dexops doctor
```

For local UI development, `dexops --local` opens port 4840. Existing direct
`python -m t2_bots.connect.app` usage remains available in an environment where
the app is installed. To run a local directory in a separate development venv:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[directory]"
.\.venv\Scripts\python.exe -m t2_bots.connect.directory --port 8090
```

For public setup, returning-user detection, optional sign-in startup, updates and
rollback, read [INSTALLATION.md](docs/INSTALLATION.md).

## Where the code lives

| Path | Responsibility |
| --- | --- |
| `src/t2_bots/connect/static/` | Browser UI: onboarding, owned arms, follower dashboard |
| `src/t2_bots/connect/app.py` | Local HTTP API, browser watchdog, directory coordination |
| `src/t2_bots/connect/hardware.py` | USB discovery, inspection, guided calibration |
| `src/t2_bots/connect/sessions.py` | Leader/follower packets, motor checks, movement, reconnects |
| `src/t2_bots/connect/storage.py` | Private station identity and calibration persistence |
| `src/t2_bots/connect/runtime.py` | Runtime compatibility and source-build identification |
| `src/t2_bots/connect/cli.py` | Start, stop, update, repair, doctor and rollback commands |
| `src/t2_bots/connect/installation.py` | Clone registration, environment reuse and staged update handoff |
| `src/t2_bots/connect/startup.py` | Optional per-user sign-in startup on Windows/macOS/Linux |
| `src/t2_bots/connect/directory.py` | SQLite usernames, follower listings, expiring reservations |
| `src/t2_bots_so101/driver/` | SO-101 serial bus and register definitions |
| `src/t2_bots/network/` | Packet framing and Pinggy SSH relay |
| `src/t2_bots/platform/installer.py` | Read-only platform probes; no system changes |
| `scripts/` | Existing installation, launcher, release, and verification commands |
| `tests/` | Simulated hardware, API, reconnect, calibration, UI, and release checks |

Python package names remain `t2_bots` and `t2_bots_so101` so existing launch
commands and station files continue to work. This focused distribution does not
include the original SDK's unrelated AI, vision, evaluation, swarm, or legacy
certification tooling. See [NOTICE](NOTICE) for upstream attribution.

## Deployment and maintenance

Use [CLOUD-SETUP.md](docs/CLOUD-SETUP.md) for Vercel and Render configuration.
The directory uses SQLite and needs no external database keys. The Vercel build
only needs the public `T2_DIRECTORY_URL`.

See [FRONTEND.md](docs/FRONTEND.md) for the existing API and onboarding behavior,
[SETUP.md](docs/SETUP.md) for hardware prerequisites, and
[ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data flow.

Run checks from this folder:

```bash
python -m pip install -e ".[gateway,dev]"
python -m pytest -q
node --test tests/*.test.cjs
```

Tests use simulated motors and isolated storage. Actual hardware operation and
relay connectivity still require checks with the two participating computers.
