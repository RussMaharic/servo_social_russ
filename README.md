# Dexops

Dexops guides users from installation and a unique username through USB detection,
motor inspection and calibration, then into a dashboard for sharing followers
and connecting a leader to an available arm.

The maintained application is in **[dexops/](dexops/README.md)**, inside this same
Git repository. Its existing functionality is preserved: Windows/macOS/Linux,
one leader and one follower per computer, no login, local calibration profiles,
PIN-protected sharing, explicit movement enabling and bounded link reconnection.

## Start here

New users open [the Dexops workspace](https://servosocialruss.vercel.app/) and copy
the setup command for Windows, macOS or Linux. It clones the release deployed on
the website once, creates a reusable environment, and opens the hosted onboarding.
It reuses a registered clone on subsequent runs; local edits are never overwritten.
Choose sign-in startup during setup to have future website visits reconnect
automatically after signing in to the computer.

From this repository on Windows:

```powershell
cd dexops
py scripts/setup-dexops.py
```

On macOS/Linux:

```bash
cd dexops
bash scripts/start-connect.sh
```

Use Python 3.10+. Keep the companion process running while using the browser.
The Python commands, version, wire protocol and station-data location are retained.
The service runs in the background. In a new terminal, `dexops` starts or reuses it;
`dexops update` updates to the deployed release; `dexops doctor` diagnoses setup.
See the [installation and update guide](dexops/docs/INSTALLATION.md).

## Repository map

| Folder | Purpose |
| --- | --- |
| `dexops/` | Self-contained application, required driver code, launchers and tests |
| `dexops/docs/` | Current setup, architecture, onboarding and hosting guides |
| `scripts/` | Thin wrappers preserving the existing root setup/build commands |
| `.github/` | Cross-platform app tests and download-build checks |
| `vercel.json`, `render.yaml` | Hosting configuration targeting `dexops/` |

Make browser-app changes in `dexops/`; it is the only application source tree.
The retired SDK, duplicate tests/docs and obsolete build output have been removed.
Root `pyproject.toml` keeps `pip install -e ".[gateway]"` working against that
same source; it does not contain or install a second SDK. The directory uses SQLite.
The retired external database adapter, migrations, environment variables and SQL
validation are removed.

Read the [code map](dexops/README.md#where-the-code-lives),
[architecture](dexops/docs/ARCHITECTURE.md), and
[deployment guide](dexops/docs/CLOUD-SETUP.md).
The Vercel build needs only the public `T2_DIRECTORY_URL` of the Render directory.

## Verify

From `dexops/`:

```bash
python -m pip install -e ".[gateway,dev]"
python -m pytest -q
node --test tests/*.test.cjs
```

The automated checks use simulated motors. Physical behavior and public relay
connectivity still need verification on the participating computers.

Original SDK attribution and the Apache-2.0 license are preserved in
[LICENSE](LICENSE) and [dexops/NOTICE](dexops/NOTICE).
