# Browser workspace and local companion

The browser UI is in `src/t2_bots/connect/static`. `app.js` contains the current
onboarding and dashboard; `styles.css` and `index.html` provide the presentation.
The code organization has changed, while the current user flow is preserved.

## User flow

1. Copy the website setup command once to clone/register the companion. Subsequent
   visits detect the running service and resume saved onboarding. Optional sign-in
   startup handles reboot; a stopped companion can be started with `dexops`.
2. Choose a unique username. A generated private device credential stays local.
3. Add a leader, follower, or one of each using separate USB controllers.
4. Inspect motors and perform passive guided calibration: record the reference,
   move each joint gently through its comfortable range, then review and save.
5. Share the calibrated follower through Pinggy or a reachable LAN/VPN address.
6. Select a shared follower from the dashboard and enter the owner's PIN.
7. Connect read-only, then explicitly enable following. Connecting and saving
   calibration do not enable torque.

Calibration capture runs locally between browser polls. Recoverable motor status
faults pause measurement and preserve the reference/ranges for a healthy recheck.
One leader and one follower can run concurrently on separate controllers.

## Compatibility and local state

The public workspaces remain `servosocialruss.vercel.app` and
`play.trydexops.com`. They access the approved loopback API on port 4840. Mutating
requests require the current `X-T2-Session` token. The protocol is `t2-connect/2`.

The companion identifies its process build. The website checks API version,
minimum companion version, required capabilities and runtime health; a source-build
hash difference alone does not block a compatible runtime. Approved hosted pages
verify compatible runtimes automatically and continue onboarding. Updates prepare
the website's exact Git commit in a separate worktree/environment before handing
off the idle companion. Active robot work must finish before updating.
See [INSTALLATION.md](INSTALLATION.md) for commands and returning-user behavior.

The state location remains `~/.config/t2_bots/connect`, overridden by
`T2_CONNECT_HOME`. `station.json` holds the device identity and arm assignments;
`calibration/so101_leader.json` and `so101_follower.json` hold profiles. Profile
replacement preserves a backup. Never distribute these private files.

## Session recovery and limits

Browser heartbeats run independently once per second. A warning appears after
three seconds without a successful response; the local five-second browser
watchdog still ends sessions if contact is lost. Browser suspension can stop
timers, so keep the workspace open.

Temporary transport failure triggers up to three retries of the same endpoint
and PIN after 1, 2 and 4 seconds. Movement remains paused after recovery until
Enable following is clicked again. Stop cancels pending retries. USB and motor
faults, owner shutdown and expired reservations do not automatically resume.

Motor error flags are read every exchange. Voltage and temperature reads rotate
through six motors; all readings must be fresh within 1.5 seconds before enabling
and during following. The peer receive timeout is 0.5 seconds. Targets remain
bounded to the existing calibration rules and limited to 30 degrees/second.
The software loop targets up to 60 Hz; actual speed depends on serial/network I/O.

Directory maintenance runs separately from the watchdog. Temporary outages are
retried while the existing 45-second reservation remains valid; rejection or
expiry ends the session with a visible reason. The directory is SQLite-backed
and deployed on Render. See [CLOUD-SETUP.md](CLOUD-SETUP.md).

Timing remains best effort. Stop attempts to release torque on every motor and
reports unverified release; hardware failure can prevent a software release.

## Verification

Run `python -m pytest -q` and `node --test tests/*.test.cjs` from `dexops/`.
Tests cover onboarding gates, calibrated arms without certification, profile
persistence, username ownership, session exclusivity, motion bounds, disconnects,
reconnect cancellation, directory outages and the deployed-to-local handoff.
They use simulated motors and isolated storage; real hardware and public relay
operation require separate verification.
