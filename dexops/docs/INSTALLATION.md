# Install once, return to the website

## First setup

1. Install Python 3.10+ and Git if they are missing. On Windows, install the Python
   launcher (`py`); on macOS/Linux, the command is `python3`. Debian/Ubuntu may
   also need the `python3-venv` package.
2. Open https://servosocialruss.vercel.app/ or https://play.trydexops.com/.
   Choose the operating system in the installation step.
3. Leave **Start the idle companion when I sign in** checked for automatic
   detection after a reboot, or uncheck it to start manually.
4. Copy the displayed command into PowerShell on Windows or Terminal on macOS/Linux.
   Any working folder is fine. The command downloads the website's Python bootstrap
   script and runs it using your installed Python. No ZIP or unsigned EXE is needed.
5. Let setup finish. It reads the website's deployed commit, checks for a registered
   clone, and clones only when needed. A healthy registered environment is reused.
   A new or repaired environment is verified before handing off the service.
6. The hosted workspace opens automatically. Allow access to local devices/network
   if your browser asks. The website detects the companion and advances to choosing
   a username, or resumes saved onboarding/dashboard for returning users.
7. Add one leader and optionally one follower, inspect and calibrate each, and use
   the follower dashboard. Sharing, connecting, and enabling movement remain
   explicit actions. Startup and detection never enable torque or movement.

The website command is available after this release has been committed and
deployed. An uncommitted local build does not advertise an older Git commit as
though it contained the latest changes.

## Returning visits

If the companion is running, opening either approved website reconnects
automatically. With sign-in startup enabled, this also works after signing in
following a reboot. Windows uses a per-user Startup shortcut; macOS uses a
LaunchAgent; desktop Linux uses an XDG autostart entry. No administrator rights
are needed. Headless Linux needs a separately managed service and is not covered
by desktop autostart.

If you deliberately stopped the companion, run this in a new terminal:

```text
dexops
```

It starts or reuses the service and opens the saved hosted workspace. Closing the
terminal does not stop the background companion. Keep the workspace page open
during a robot session; the existing browser watchdog still stops movement after
loss of contact.

The website remembers only that this browser connected before. This is a hint,
not proof that software is installed. A website cannot scan your disk or start a
stopped program without a local service or user action. Clearing browser storage
does not remove the clone or station data; rerunning setup still finds the
registered installation.

## Commands

| Command | Behavior |
| --- | --- |
| `dexops` | Start/reuse the companion and open the saved hosted website |
| `dexops --no-browser` | Start without opening a tab |
| `dexops --local` | Open the local development UI |
| `dexops update` | Prepare the website's deployed Git commit, verify it, then hand off |
| `dexops doctor` | Report registration, Python, Git, startup and reachability |
| `dexops repair` | Prepare a fresh environment, preserving the previous one until handoff |
| `dexops rollback` | Restore the recorded previous verified environment |
| `dexops stop` | Stop the idle companion; active sessions/capture must finish first |
| `dexops autostart on` | Enable per-user sign-in startup |
| `dexops autostart off` | Disable future sign-in startup; does not stop the current service |

Updates require an idle station: finish/cancel calibration and stop sharing and
following first. Updates use the commit in the current website's `release.json`,
not whatever happens to be latest on `main`. Existing Git edits and unrelated
folders are never reset or overwritten. A new release uses a separate Git
worktree and environment, retaining the previous registration for rollback.
Dependency installation occurs during setup/update/repair, not ordinary starts.
`requirements-companion.lock` pins runtime dependencies and verifies their package
hashes, including Python-version markers. Maintainers regenerate it with:

```bash
uv pip compile pyproject.toml --extra gateway --universal --python-version 3.10 --generate-hashes --output-file requirements-companion.lock
```

## Existing clones and launchers

You can run the shared setup directly from the repository root:

```powershell
py dexops/scripts/setup-dexops.py --autostart
```

On macOS/Linux:

```bash
python3 dexops/scripts/setup-dexops.py --autostart
```

From inside `dexops/`, use `scripts/setup-dexops.py`. Existing Start Dexops
launchers delegate to the same setup. Without `--autostart` or `--no-autostart`,
setup preserves an existing startup preference; first local setup defaults off.
`--install-only` registers the environment without starting the companion.

The website bootstrap checks the installation record first, then a bounded set
of earlier `Downloads/dexops*` clones and `Downloads/t2_bots_teleop`. If several
clones are found, it asks you to choose one by appending `--repo "FULL_PATH"` to
the **bootstrap Python invocation** in the copied command. It does not guess or
make another clone. A legacy ZIP can be run locally but `dexops update` requires
the bootstrap to register a Git clone once.

If `dexops` is not found, open a fresh terminal (on Windows, restart the terminal
application). Setup prints an absolute command usable immediately. The default
Windows fallback is:

```powershell
& "$env:USERPROFILE\.dexops\bin\dexops.cmd"
```

On macOS/Linux:

```bash
"$HOME/.dexops/bin/dexops"
```

## Data and troubleshooting

Installation registration, managed clone, prepared releases, environments and
logs are in `~/.dexops/`. Background service logs are in
`~/.dexops/logs/companion.log` (previous log rotates at 2 MB).
Your username/device key and calibration remain in
`~/.config/t2_bots/connect/` or the existing `T2_CONNECT_HOME` override. Installer
commands do not delete or reset that folder. Do not share `station.json`.

If setup fails, read its error and run it again after fixing the prerequisite.
Interrupted setup/update locks release automatically when the process exits.
If browser access fails while `dexops doctor` reports a running service, check
the browser's local network permission and that the tab uses an approved origin.
An API/minimum-version/capability mismatch offers `dexops update`; a source-build
hash difference alone does not force reinstalling.
