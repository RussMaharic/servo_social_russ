# Browser onboarding and remote follower directory

Status: APPROVED — user approved the design and Render hosting
Date: 2026-10-24

## Goal

Take a first-time SO-101 user from installation through actual USB discovery,
guided calibration and hardware qualification to a dashboard of available
remote followers. Use a unique username without an email, password or login
screen. Support leader-only, follower-only and dual-arm stations.

## Proposed hosting

- **Vercel:** Public entry page and frontend assets.
- **Local Python companion:** USB access, SDK setup, calibration, certificates
  and session processes on each robot workstation.
- **Render:** Shared directory API with continuously running ownership and
  availability tracking. Initially use one instance and SQLite on a persistent
  disk; adopt a shared database before adding API instances.
- **Existing SDK peer/Pinggy transport:** Robot traffic. The new directory
  advertises reachable connection metadata; it is not a new motor-command relay.
- **GitHub Releases:** Versioned companion downloads. Release builds must include
  the new source rather than silently installing the old v0.2.0 wheel.

The public website hands off to the installed companion's loopback workspace
using an application link or an explicit local-workspace link. Cloud directory
requests go through the companion. This avoids requiring the hosted HTTPS page
to directly call arbitrary local HTTP control APIs.

Vercel now supports WebSockets in public beta, with connections bounded by
Function duration. A separate continuously running service is a deployment
choice for this design, not a claim that Vercel cannot serve WebSockets.

## Reference and existing capabilities

Use the supplied frontend as inspiration for progressive setup, installation
verified by a companion handshake, physical device confirmation, measured motor
inspection, persistent profiles, reopenable steps and separate connect/enable
actions. Create distinct branding, copy, layout and implementation here.

Do not transplant its group accounts, Supabase authentication, local pair
protocol or unsupported hardware claims. This SDK already provides the gateway,
serial discovery, calibration utilities, CertificationEngine, peer sessions,
relay management and CLI swarm support. Its gateway is an integration starting
point, not a ready public motor-control API.

## User journey

1. **Install and open:** Show OS-specific release availability and instructions.
   Confirm the actual companion/version before completing installation. A
   download click does not count as installation; missing installers stay marked
   unavailable.
2. **Choose your name:** Atomically claim a normalized unique username. Generate
   a random device credential and store it locally; no recurring login screen.
   Typing an existing username cannot reclaim it. Explain backup/recovery.
3. **Choose your setup:** Leader, follower or both. Discover actual USB adapters,
   require identification when ambiguous and bind profiles to controller identity
   rather than a COM number alone.
4. **Inspect:** Display actual motor communication, voltage, temperature and
   errors. Handle unplugging, occupied ports and permissions. Missing readings
   never become healthy defaults.
5. **Calibrate:** Guide physical reference and range capture appropriate to this
   SDK. Require support before releasing torque, review measured values before
   saving, and preserve prior profiles. Physical positioning remains a user task.
6. **Certify:** Explain firmware-limit changes before applying them. Issue the
   README qualification certificate only after current measurements pass. Bind
   it to controller identity and calibration revision, preserve saved calibration,
   and provide a JSON download.
7. **Dashboard:** Show local readiness and real shared followers with owner,
   availability, certificate summary and last seen time. Design empty, loading,
   occupied, expired and offline states as first-class screens.
8. **Connect and enable:** Select a follower, enter its private PIN, review both
   stations and connect. Powered following requires a separate explicit action.
   Show actual session state and stop/disconnect controls.

## Directory and lifecycle

Sharing is an explicit follower-owner action. Certification alone does not
publish or start an arm. Advertise only a listener with a usable address; expire
availability on missed heartbeats and revoke it immediately on local unplug or
shutdown when possible. Keep PINs out of public listings. Device credentials
authorize ownership changes; usernames are display identifiers.

Initially control one selected follower from the UI. Existing swarm commands
remain available; multi-follower UI follows reliable per-follower lifecycle
handling. A listed certificate is a station's claim, not independent inspection
by the directory operator, and its hash does not authorize a control session.

## Code prerequisites

- Certification currently substitutes plausible values for missing register
  reads and can qualify holding torque after errors. Make these paths fail closed
  before a passing certificate can unlock the dashboard.
- Confirm firmware changes by register readback, not just write completion.
- Replace the gateway's permissive CORS/unauthenticated control exposure with a
  loopback companion, Host/Origin validation and protected mutation requests.
- Enforce one serial-port owner across inspection, calibration, qualification
  and teleoperation.

## Alternatives

- Local-only gateway: smallest deployment; lacks the shared discovery requested.
- Hosted frontend plus companion: recommended, consistent with Vercel preference
  and the SDK's existing networking model.
- Desktop-only shell: possible later; more packaging/update work before it
  improves shared discovery.

## Verification and delivery

Implement locally first and check in Vercel configuration and Render deployment
instructions. This design does not provision accounts, spend money or deploy.

Test username collisions/ownership, disconnect invalidation, failed register
reads, calibration retention, certificate download, directory expiry and session
lifecycle using fake hardware. Browser checks must include honest disconnected
states. Never seed actual discovery with fictional arms.

The upstream tests are absent from this checkout. Physical acceptance requires
a clean-machine install and a real SO-101 two-workstation session, including
unplugging, ambiguous USB adapters, low voltage, calibration failures and expired
certificates. Automated tests do not establish physical performance.

**User acceptance assignment:** Walk through setup on a leader station and a
follower station and verify each on-screen gate matches the physical hardware,
then confirm PIN-authenticated connection, enable and stop behavior.

## References

- SDK gateway, certification, calibration and peer modules under src/.
- User-supplied reference frontend README, welcome page and live flow.
- https://vercel.com/docs/frameworks/frontend/vite
- https://vercel.com/kb/guide/do-vercel-serverless-functions-support-websocket-connections
- https://render.com/docs/websocket
- https://render.com/docs/disks
