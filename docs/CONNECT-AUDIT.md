# t2 Connect audit — 24 October 2026

## Result

The source development runtime is validated by 102 automated checks: 73 Python
tests and 29 frontend state/rendering tests. Full onboarding and remote sessions
were exercised over actual loopback HTTP and WebSocket connections using two
isolated stations, a real SQLite directory, and simulated motor buses.

This is not a claim of completed production or physical robot qualification.
The new unsigned Windows executable was blocked by Windows Application Control
(`WinError 4551`). It was not activated and security settings were not changed.
The user explicitly selected the documented Python source runtime instead.

## Verified flow

1. Runtime detection alone cannot approve installation or unlock operations.
2. Two stations claim unique usernames without email/password accounts.
3. Each selects its controller and inspects all six motors.
4. Each records its rest reference and measured ranges, then saves calibration.
5. Qualification produces an A+ certificate and leaves torque released.
6. Certificate download works; qualification preserves the measured profile.
7. A follower owner explicitly shares a PIN-protected listener.
8. The leader discovers it through the directory and connects without writes.
9. Explicit enabling allows bounded simulated following; stopping releases torque.
10. Reservations and listings recover; restarting restores identity and profiles.

Existing failure checks also cover unreadable/low-voltage motors, torque
readback failures, occupied serial ports, certificate tampering/expiry,
disconnects, session watchdogs, exclusive access, and loopback/Origin guards.

## Repairs verified in this audit

| Finding | Repair and evidence |
| --- | --- |
| Owners with both arms could not share and operate at the same time | My arms exposes one named leader and one named follower, each with independent status/profile/qualification. Separate session engines keep follower sharing active during outgoing leader control. Actual loopback HTTP/WebSocket regression covers owner registration, same-owner pairing, explicit enable, switching to a remote follower, a guest controlling the local follower concurrently, independent stops and restart persistence. |
| A motor-status flag discarded the capture with a generic error | Status faults now pause, show/log the motor ID, raw hexadecimal flag, position, voltage and temperature, and retain the last complete healthy sample. Explicit recheck requires healthy status, power, temperature and released torque before continuing. Saving while paused is blocked. The reference frontend's 20-second passive browser grace period replaces the five-second calibration timeout; powered sessions retain five seconds. Nine recovery tests fail against the preceding behavior or verify its associated guards. |
| Calibration positioning looked inactive because every row showed zero travel | The reference stage now displays actual live encoder positions, received sample count, an explicit stage label and a primary Record reference & start measuring action. Simulated frontend click/poll regressions verify transition into measured travel and save readiness. No rest pose is recorded automatically. |
| Hand calibration repeatedly stopped with “Encoder jump detected” | Reproduced the 1500-tick browser-paced rejection during ordinary positioning/sweeping and missed between-poll travel. The companion now samples locally with a 50 ms pause between reads, positions the reference before collecting ranges, and resets ranges on re-record. Regression tests cover a 1700-tick change, a continuous 2400-tick six-joint sweep through save, true encoder boundary rejection, and persistent background motor faults. |
| Old tabs repeatedly demanded another download | A local page checks fresh server metadata and reloads once when the companion has actually updated. A genuinely older companion still stays blocked. |
| Post-action refresh could be dropped behind an existing poll | Forced refresh waits and then fetches current state. Regression reproduces the race and verifies the saved state/next step. |
| Save appeared before all measured joints were ready | Live joint count and reference state gate Review & save; all six require the existing minimum travel. Backend checks remain authoritative. |
| Handshake accepted a signed non-passing follower grade | Leader now explicitly requires A+ at handshake, in addition to signature, role and protocol validation. |
| Running from source could encourage repeated downloads | Current source mode is labelled explicitly and says when no additional download is needed. It still requires runtime confirmation. |
| Building a new EXE required stopping the current app | Optional staged executable output allows the running app to remain available throughout build. |
| Missing deployment assets/configuration were easy to publish | Release checker validates ZIP contents, metadata, download paths, private-data exclusion and the public directory URL. |

The preceding inspection/calibration repair was also rechecked: inspection no
longer expires after 30 seconds and stopped captures retain their explanation
across polls/tabs. A packaged read-only inspection of the real COM9 leader
passed all six motors (minimum 5.3 V, maximum 29 °C) and remained available
after 33 seconds. No movement commands were sent during that check.

## Credentials and deployment

| Service | Required by the current application |
| --- | --- |
| Vercel | No runtime API key. A hosting account/authorized deployment and real built assets are needed. |
| Render | No vendor API key in the app. The prepared cloud Blueprint uses the private `T2_DATABASE_URL` and Supabase storage, without a disk. Local development still uses SQLite. |
| Supabase | Postgres support and a private-schema migration are prepared for `fwamzeswdfhqtabakaib`. The user will apply SQL and configure the database connection. No browser key or Supabase Auth is needed. |
| Directory access | Each companion generates its own private device credential automatically; ownership is not based on a username alone. |

Both stations need the same deployed HTTPS directory URL for shared remote
discovery. The configured localhost directory is for development. No cloud
service was provisioned, published or billed by this audit. Platform/CI deployment
credentials, if used later, stay in platform secret settings.

The production checker rejects a missing public directory URL. A source-only
release must be explicitly requested with `--source-only`; the Vercel build uses
that mode and regenerates downloads from source. Trusted Windows signing remains
separate from hosting/database configuration.

Cloud preparation was validated with an isolated embedded PostgreSQL engine:
schema idempotence, preservation of unrelated tables, uniqueness, row-lock
queries, RLS and private-role permissions passed. An isolated copy also completed
the real Vercel build, matched the download's embedded directory address, and
rejected missing configuration. These checks do not establish a live Supabase
connection or successful Render/Vercel deployment. No remote SQL was applied.

## Remaining verification

- Real browser automation is disabled in Work settings. DOM/state and HTTP
  checks do not establish actual click behavior, screenshots or responsive QA.
- Hands-on calibration/certification and a real two-arm session remain to be
  validated. Simulated motor tests do not prove mechanical safety or latency.
- The original generic motor-status failure did not retain its motor/flag. A
  subsequent read-only check completed 120 six-motor status rounds without a
  nonzero flag. Later pause diagnostics captured Motor 6 (gripper), status
  `0x01`, with 3.9 V and 28 °C. The 3.9 V reading is below the leader's 4.8 V
  inspection minimum; the cause of that voltage drop remains unconfirmed.
  Diagnostics retain this evidence instead of suppressing or clearing it.
- Native macOS/Linux packages were not built. Source launchers are supplied;
  installation on real macOS/Linux hardware remains unverified here.
- The new unsigned native Windows candidate needs a trusted signing path and
  clean-machine install verification. Repeatedly downloading it will not resolve
  an operating-system Application Control block.
- Public Pinggy operation was not opened/tested in this audit. The current raw
  `ws://` TCP path is not end-to-end TLS merely because one tunnel leg uses SSH.
  Use a trusted private network/VPN or add protected transport before public use.
- Qualification is the SDK's local hardware report, not an independent safety
  authority. One-to-many swarm control remains in the existing CLI, outside this
  single-follower dashboard.

## Reproduce

```text
python -m pytest -q
node --test tests/frontend.test.cjs tests/frontend_audit.test.cjs
python scripts/check-connect-release.py
python scripts/check-connect-release.py --production
```

The last command should fail until a public directory and the intended
production downloads are configured. It must not be treated as a passing
installation, signing, browser or physical robot test.

Official platform references: [Vercel environment variables](https://vercel.com/docs/environment-variables),
[Render persistent disks](https://render.com/docs/disks),
[Render environment variables](https://render.com/docs/configure-environment-variables),
[Microsoft Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview).
