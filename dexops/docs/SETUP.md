# Hardware prerequisites

Use a supported Python 3.10+ interpreter, USB data cable and powered SO-101
controller. Close other applications using its serial port. A follower requires
the correct 12 V supply; the leader checks use the existing lower voltage floor.

## Windows

Install Python from python.org with the Python launcher available and Git.
Copy the Windows setup command from the hosted workspace; it clones once and
opens onboarding. Existing source checkouts can run `py scripts/setup-dexops.py`
from this `dexops/` folder. If a controller is absent, check Device Manager and install
only the driver matching its CH340/CH343, FTDI or CP210x adapter.

The source launcher uses Python; no unsigned application executable is required.
Public relay links require the Windows OpenSSH Client optional feature. Check
availability with `ssh -V`.

## macOS

Use a Python build matching your Mac's architecture and install Git if needed.
Copy the macOS setup command from the hosted workspace. Existing source checkouts
can use `Start Dexops.command` or `bash scripts/start-connect.sh`. Connect the USB adapter and check the
`/dev/cu.*` serial device. Check OpenSSH with `ssh -V`.

## Linux

Copy the Linux setup command from the hosted workspace. Existing source checkouts
can run `bash scripts/start-connect.sh`. Ensure your user can read and write the
controller's `/dev/ttyUSB*` or `/dev/ttyACM*` device. On Debian/Ubuntu this usually
requires membership in the serial device's `dialout` group; apply your distro's
USB/udev guidance and sign out/in after group changes. The retained platform
probe also checks the existing `/etc/udev/rules.d/99-t2-so101.rules` and `plugdev`
configuration. It only reports findings and never modifies the system.

Check the OpenSSH client with `ssh -V`. Install the distro's `openssh-client`
package if public relay links are needed. A reachable LAN/VPN connection does not
need an SSH relay.

See [INSTALLATION.md](INSTALLATION.md) for environment reuse, startup and updates.
