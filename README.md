# nsogcd — Nintendo Switch 2 GameCube Controller for Linux

**Pair your NSO GameCube controller wirelessly to Bazzite, SteamOS, or any Linux box. Use it in Dolphin, Steam, RetroArch, Project+, Mario Eclipse, and other emulators.**

> **Status: Beta.** Tested on Bazzite. Should work on SteamOS, Arch, Fedora, Ubuntu — please file an issue if you test on something else.

The Nintendo Switch Online GameCube Controller (the Switch 2 generation released 2025) doesn't speak standard Bluetooth HID. It uses a proprietary BLE protocol that no Linux Bluetooth stack handles natively. This daemon does the protocol handshake for you, then exposes the controller as a normal Linux gamepad that any application can use.

---

## One-line install (Steam Deck, Bazzite, anything)

Open a terminal (Konsole on Steam Deck Desktop Mode), paste, run:

```bash
curl -fsSL https://raw.githubusercontent.com/loserkidsblink/nsogcd/main/install.sh | sudo bash
```

After install:
1. Reboot (or `sudo systemctl start nsogcd` to start without rebooting)
2. Press the sync button on the NSO GameCube controller
3. Wait ~3 seconds
4. Done

The controller will now appear in Dolphin, Steam, RetroArch, and any other application that reads input devices.

---

## How to pair (after install)

**Just press the sync button.** That's it.

The daemon runs in the background 24/7 watching for sync presses. It pairs the controller automatically — no Bluetooth menu, no app, no terminal.

If the controller ever disconnects (turn it off, walks out of range, sleeps for too long): press sync again. Same 3 seconds, same result.

---

## How to use with Dolphin / Project+ / Mario Eclipse

After the daemon is paired, the controller appears as `Nintendo GameCube Controller` (VID `0x057E`, PID `0x2073`) — exactly like the real USB version. Most Dolphin builds have working profiles for this controller already.

For best results in emulator games:
- **Disable Steam Input** for the specific game (Steam → game properties → Controller → "Disable Steam Input"). Steam Input intercepts our virtual gamepad and translates it; emulators like Dolphin work better with raw input.
- For Steam library games (non-emulator), leave Steam Input enabled — it provides per-profile bindings.

The repo includes `scripts/configure-dolphin.sh` which auto-detects every Dolphin instance on your machine (Flatpak, AppImage, EmuDeck-managed) and writes a controller profile that uses the NSO GC.

---

## Compatibility

| Distro | Status |
|---|---|
| Bazzite (immutable Fedora) | ✅ Tested by author |
| Steam Deck SteamOS | 🟡 Should work, untested |
| Arch / EndeavourOS | 🟡 Should work, untested |
| Fedora / Nobara | 🟡 Should work, untested |
| Ubuntu / Debian | 🟡 Untested |
| ChimeraOS / HoloISO | 🟡 Untested |

| Controller | Status |
|---|---|
| NSO GameCube Controller (Switch 2, PID `0x2073`) | ✅ Tested |
| Switch 2 Pro Controller (PID `0x2069`) | 🟡 Same protocol family, should work |
| Switch 2 Joy-Con L/R (PID `0x2067`/`0x2066`) | 🟡 Same protocol family, should work |

If you test on something not listed, please [open an issue](https://github.com/loserkidsblink/nsogcd/issues) with results.

---

## Important caveats

### The daemon takes over Bluetooth (`hci0`) while running

This is the biggest gotcha. The Switch 2 controllers use a proprietary BLE protocol that BlueZ (the standard Linux Bluetooth stack) cannot handle. The daemon takes over the Bluetooth radio directly. While the daemon runs, **other Bluetooth devices disconnect** — headphones, mice, keyboards.

**To pause:** `sudo systemctl stop nsogcd` (Bluetooth comes back).
**To resume:** `sudo systemctl start nsogcd` (controller can re-pair).

If you want to use both the controller AND BT headphones simultaneously, the cleanest fix today is a **dedicated $5 USB Bluetooth dongle** for the controller (multi-adapter support is on our roadmap).

The long-term solution is upstream BlueZ patches landing — see [BlueZ PR #2009](https://github.com/bluez/bluez/pulls) which adds proper Switch 2 support to BlueZ itself. Once that's released, this daemon may not be needed.

### Single host bond

The controller stores ONE host pairing in its flash memory. When you pair to your Legion Go via this daemon, the controller's pairing on your Switch 2 console is overwritten. To switch back, you have to re-pair on the Switch 2 (one-time annoyance per swap).

A future "loaner mode" / "SPI hot-swap" tool is on the roadmap — would let you snapshot SPI state and restore it to switch hosts without re-pairing.

### One controller at a time

Multi-controller support is on the roadmap. Currently the daemon handles one connection.

---

## Troubleshooting

### Press sync, nothing happens

Check the daemon is running: `systemctl is-active nsogcd` → should print `active`.

If `inactive` or `failed`: check logs with `journalctl -u nsogcd -n 50`.

If `active` but controller not pairing: try holding sync button longer (1-2 seconds). The chase pattern on the player LEDs means it's advertising.

### Controller pairs but Project+ / Mario Eclipse not responding

Most likely Steam Input is intercepting. Disable Steam Input for that specific game:
1. Steam → right-click the game → Properties
2. Controller tab
3. Override → "Disable Steam Input"
4. Quit and relaunch the game

### Bluetooth headphones disconnected

Yes — see "Important caveats" above. The daemon's HCI takeover blocks other BT. Use `sudo systemctl stop nsogcd` to pause.

### "uinput: Permission denied"

The daemon needs root to create uinput devices. The systemd service runs as root. If you're running directly: use `sudo`.

---

## Uninstall

```bash
sudo systemctl disable --now nsogcd
sudo rm -rf /usr/local/lib/nsogcd /usr/local/bin/nsogcd /etc/systemd/system/nsogcd.service
sudo systemctl daemon-reload
sudo systemctl start bluetooth
```

---

## How does this work?

See [`docs/PAIRING.md`](docs/PAIRING.md) for a step-by-step technical walkthrough of what happens when you press sync.

See [`docs/PROTOCOL.md`](docs/PROTOCOL.md) for the SW2 BLE protocol reference.

See [`docs/RESEARCH.md`](docs/RESEARCH.md) for our reverse-engineering findings (three of them are novel — not documented in any prior public source).

---

## Credits

This project is mostly **packaging** of work done by other reverse engineers. See [`CREDITS.md`](CREDITS.md) for full attribution.

The most important credits:
- **[RyanCopley/NSO-GameCube-Controller-Pairing-App](https://github.com/RyanCopley/NSO-GameCube-Controller-Pairing-App)** — the actual working pair flow code we use
- **[darthcloud/BlueRetro](https://github.com/darthcloud/BlueRetro)** — original SW2 protocol reverse engineering
- **[ndeadly/switch2_input_viewer](https://gist.github.com/ndeadly/7d27aa63e2f653a902a2474dbcbc08b3)** — manufacturer ID + bond layout
- **[Vicki Pfau (endrift)](https://github.com/Senko-p/hid-switch2-dkms)** — Linux kernel patch series, flash subcommand enum

If this project saves you time, **please star their repos too**. They did the hard work.

---

## License

GPL-3.0 (matches RyanCopley/NSO-GameCube-Controller-Pairing-App which we depend on).

See [`LICENSE`](LICENSE).

---

## Contributing

Issues and PRs welcome. See [`docs/RESEARCH.md`](docs/RESEARCH.md) for protocol details and known unknowns.
