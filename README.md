# nsogcd — NSO GameCube controller research and legacy Linux bridge

> **Maintenance status: paused.** For a new installation, start with one of the projects below. This repository remains available for its source code and [protocol notes](docs/PROTOCOL.md), but its v0.1 Linux installer and compatibility claims have not been maintained against current systems.

## Use a maintained controller bridge

| Platform | Project | What it offers |
| --- | --- | --- |
| Linux, including Bazzite and SteamOS | [switch2-controllers-linux](https://github.com/trevlars/switch2-controllers-linux) | NSO GameCube and Switch 2 Pro support, virtual gamepads, desktop pairing, a background service, and an optional Decky plugin. Its README documents remaining wake and multi-controller limits. |
| macOS 15+ on Apple Silicon | [Finally the Controller Works](https://github.com/Peterksharma/switch2mac) | A signed Mac app with Bluetooth pairing and a system-wide virtual gamepad. See its README for current rumble and app compatibility details. |

Follow each project's own installation and pairing instructions. These are independent projects; `nsogcd` is not required for either one.

## Status of this project's fixes

The public v0.1 code still has the installer dependency problem in [#1](https://github.com/loserkidsblink/nsogcd/issues/1), the bonded reconnect failure in [#2](https://github.com/loserkidsblink/nsogcd/issues/2), and the HCI transport cleanup problem discussed in [PR #3](https://github.com/loserkidsblink/nsogcd/pull/3). Do not treat this README update as a release of those fixes.

In local development on a Bazzite Legion Go, we bundled the missing backend, used a dedicated Python environment, closed the Bumble transport, and changed reconnect handling. We also verified Z/ZL input and native GameCube rumble on/off against the physical controller. That development branch is not published as a supported release, and its fresh installation on other distributions has not been verified. The maintained projects above are the recommended path for new users.

## If you installed nsogcd already

Its original Linux service takes control of the Bluetooth adapter while it runs. Stop and disable it before trying another controller bridge:

```bash
sudo systemctl disable --now nsogcd
sudo systemctl start bluetooth.service
```

If the Bluetooth service was masked by a later experimental build, unmask it with `sudo systemctl unmask bluetooth.service` before starting it. To remove the original install, check its file locations first, then remove the service file and installed `nsogcd` program. The default paths are `/etc/systemd/system/nsogcd.service`, `/usr/local/bin/nsogcd`, and `/usr/local/lib/nsogcd`; SteamOS could use a different prefix. Run `sudo systemctl daemon-reload` after removing the service file.

## Research and credits

- [Pairing walkthrough](docs/PAIRING.md)
- [Protocol notes](docs/PROTOCOL.md)
- [Research notes](docs/RESEARCH.md)
- [Credits and upstream sources](CREDITS.md)

The Linux bridge was based on community Switch 2 controller research and Ryan Copley's pairing code. The code remains under [GPL-3.0](LICENSE). Some later controller findings were verified locally, but are not part of the public v0.1 release.
