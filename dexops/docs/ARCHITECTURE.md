# Code and data flow

The application has three running components:

```text
Vercel browser workspace
        | local HTTP, authenticated mutation requests
        v
Local companion <--- WebSocket via LAN/VPN/Pinggy ---> Other local companion
        | USB serial                                      | USB serial
        v                                                 v
     Leader arm                                      Follower arm

Both companions ---> Render directory ---> SQLite
                     usernames, listings, reservations
```

The browser never opens a USB controller directly. It requests inspection,
calibration and session actions from the local companion. Render provides
discovery and exclusive reservations; robot angle packets flow between companions.

`app.py` composes `Hardware`, two `Sessions` instances and `LocalStore`. It owns
the browser watchdog and background directory maintenance. Each `Sessions`
instance owns its serial bus, preventing the leader and follower from sharing
one controller. `hardware.py` provides the passive calibration workflow.

The frontend is plain HTML/CSS/JavaScript. `app.js` renders server state and sends
commands to `/api/`; deployed pages call the approved loopback companion. Browser
heartbeats run separately from state refresh and directory requests.

`sessions.py` keeps initial connection read-only, establishes pose baselines only
after explicit enabling, checks motors and bounds targets. Temporary transport
loss allows three connection retries. Reconnection leaves movement disabled.
Hardware faults, deliberate stops and expired reservations do not auto-resume.

Station credentials and calibration remain in `~/.config/t2_bots/connect`, or
`T2_CONNECT_HOME`. They are never bundled in downloads or committed. SQLite
contains directory identities and listings, not motor trajectories.

The original Python namespaces, wire protocol `t2-connect/2`, API session header,
version `0.3.1`, SQLite schema and storage paths are retained. The directory's
historically named `certificate` column now stores calibration readiness; keeping
that column avoids changing existing SQLite databases.

The retained upstream pieces are the serial bus/register definitions, joint
constants, packet framing, SSH relay and read-only platform probes. They are
included inside this folder. The retired SDK source tree is not required and
has been removed from this repository's current layout.
