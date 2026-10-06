# nsogcd v0.2.0

This is the first regular GitHub release for the official Switch 2 NSO GameCube controller on Linux. The controller path was exercised on a Bazzite Legion Go. Fresh installation on the issue reporters' distributions and SteamOS remains unverified.

## Changes

- Bundle the GPL-3.0 pairing backend and protocol code that the original installer omitted. Install Python dependencies in a dedicated virtual environment instead of changing system Python packages.
- Close both the daemon session and Bumble's asynchronous HCI transport when a session ends. This addresses the two-part socket leak reported in PR #3; the exact 300-second scan-timeout reproduction has not been rerun on the published build.
- Pair explicitly with `sudo nsogcd pair --wait`. After enrollment, an ordinary button wakes the pad for host-targeted reconnect. The background scanner ignores generic Sync advertisements outside a pairing window.
- Decode Z, ZL, L/R clicks, sticks, D-pad, and analog triggers. Keep the previous virtual button layout by default and offer an optional `NSOGCD_LAYOUT=modern` layout; per-game Steam mappings can still be needed.
- Map Linux `FF_RUMBLE` effect timing to the GameCube motor's native on/off command. A physical short pulse stopped promptly, and game rumble was checked in Melee Unlocked. The single motor does not reproduce separate strong/weak channels or HD rumble waveforms.
- Update pairing and protocol documentation, credit the bundled source, and link to maintained Linux and Mac alternatives.

## Known limits

- Bumble takes control of the Bluetooth adapter while the service runs, so other Bluetooth devices on that adapter may disconnect.
- One GameCube controller at a time. SteamOS, non-Bazzite installs, and the optional modern layout need independent checks.
- This release does not include the experimental BlueZ coexistence backend or the experimental Mac bridge.

If you already installed v0.1, run `sudo nsogcd pair --wait` once after upgrading to populate the new saved-controller list. See the README for installation, status, and Bluetooth restoration instructions.
