# nsogcd — NSO GameCube controller bridge for Linux

**Status: v0.2.1.** The controller path was exercised on a Bazzite Legion Go with the official Switch 2 NSO GameCube controller. Fresh installation on other distributions and SteamOS has not been verified. See [Releases](https://github.com/loserkidsblink/nsogcd/releases) for the downloadable Linux installer bundle and known limits.

`nsogcd` connects to the controller over its proprietary BLE protocol and exposes a Linux virtual gamepad. The bridge bundles its BLE pairing code and uses a dedicated Python environment, so it no longer depends on a separate checkout of the pairing app or a hard-coded home directory.

## Consider these alternatives

| Platform | Project | What it offers |
| --- | --- | --- |
| Linux, including Bazzite and SteamOS | [switch2-controllers-linux](https://github.com/trevlars/switch2-controllers-linux) | Multiple Switch 2 controllers, virtual gamepads, desktop pairing, a background service, and an optional Decky plugin. Check its README for current wake and rumble limits. |
| macOS 15+ on Apple Silicon | [Finally the Controller Works](https://github.com/Peterksharma/switch2mac) | A signed Mac app with Bluetooth pairing and a system-wide virtual gamepad. Check its README for game rumble support. |

Neither project needs `nsogcd`. The Linux project has a broader feature set; this release keeps a GameCube-focused bridge and a physically verified native motor on/off path.

## Install and pair

On a Linux machine with a Bluetooth LE adapter, Python 3, and systemd, download the `nsogcd-v0.2.1-linux.tar.gz` asset from [v0.2.1](https://github.com/loserkidsblink/nsogcd/releases/tag/v0.2.1), then extract and run its installer:

```bash
tar -xzf nsogcd-v0.2.1-linux.tar.gz
cd nsogcd-v0.2.1-linux
sudo ./install.sh
```

The bundle contains the daemon and installer; no Git checkout is needed. The installer still downloads its Python dependencies, creates `/usr/local/lib/nsogcd/.venv` by default, installs its service, and opens a first-pairing window. Hold the controller's Sync button by its USB-C port until the player LEDs sweep. If the window expires, run:

```bash
sudo nsogcd pair --wait
```

If upgrading from v0.1, run that command once to save the controller in the new host-targeted reconnect list.

After pairing, press an ordinary controller button to wake and reconnect. **Sync is for explicit pairing.** The background scanner accepts saved controllers advertising this host's address and ignores generic Sync advertisements outside a pairing window, so it should not grab the controller while you pair it to a Switch. Pairing with another host replaces the controller's saved host; run `sudo nsogcd pair --wait` to pair it with Linux again.

Check service and controller state with `nsogcd status`, and view detailed logs with `journalctl -u nsogcd -f`.

## Input and rumble

- The physical A/B/X/Y, Z, ZL, L/R clicks, D-pad, sticks, and analog triggers are decoded into a `uinput` gamepad. Z/ZL and L/R were captured on the Legion Go. Steam may still need a per-game controller layout for Z; Steam Input mappings are separate from the physical input decoder.
- The Linux gamepad accepts `FF_RUMBLE`. This release maps an effect's start, stop, and duration to the GameCube motor's native on/off command. The physical controller produced a short pulse that stopped promptly, and game rumble in Melee Unlocked felt timed appropriately. Its single motor cannot reproduce independent strong and weak channels or HD rumble waveforms.
- `NSOGCD_LAYOUT=modern` is an optional input layout that maps Z/ZL to conventional shoulder buttons and L/R clicks to trigger buttons. The default retains the earlier layout for existing profiles. The optional layout has not been verified across Steam and emulators.

For the optional layout in the system service, add `Environment=NSOGCD_LAYOUT=modern` under `[Service]` with `sudo systemctl edit nsogcd`, then restart the service. Existing game profiles may need remapping.

## Bluetooth limitation

The Bumble backend uses raw HCI access. While `nsogcd` runs, the service temporarily masks `bluetooth.service` and takes control of the adapter; other Bluetooth devices on that adapter can disconnect. Stopping the service restores Bluetooth:

```bash
sudo systemctl stop nsogcd
```

This release supports one controller at a time. The broader Linux alternative above uses a different transport and is the better starting point when Bluetooth coexistence or multiple pads matter. An experimental BlueZ coexistence backend exists only in local development and is not in this release.

## Uninstall

Stop and disable the service before removing it:

```bash
sudo systemctl disable --now nsogcd
sudo systemctl unmask --runtime bluetooth.service
sudo systemctl start bluetooth.service
```

The default install paths are `/etc/systemd/system/nsogcd.service`, `/usr/local/bin/nsogcd`, and `/usr/local/lib/nsogcd`. Check your actual paths before deleting them; SteamOS may use `/home/deck/.local` instead. Run `sudo systemctl daemon-reload` after removing the service file.

## Development status

- [Issue #1](https://github.com/loserkidsblink/nsogcd/issues/1): the missing backend and hard-coded author path are addressed in this release; a fresh install on the reporter's distro remains unverified.
- [Issue #2](https://github.com/loserkidsblink/nsogcd/issues/2): bonded button-wake reconnect was verified on a Legion Go; the reporter's exact setup remains unverified.
- [PR #3](https://github.com/loserkidsblink/nsogcd/pull/3): the session and its bundled Bumble backend now both await transport cleanup; the exact 300-second scan-timeout reproduction remains unverified.

See the [pairing walkthrough](docs/PAIRING.md), [protocol notes](docs/PROTOCOL.md), [research notes](docs/RESEARCH.md), and [credits](CREDITS.md). Code is [GPL-3.0](LICENSE).
