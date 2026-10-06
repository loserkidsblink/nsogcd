# Credits

`nsogcd` would not exist without the work of these reverse engineers and developers. **All credit for figuring out the SW2 protocol goes to them — this project is mostly packaging.**

## Primary Source — RyanCopley/NSO-GameCube-Controller-Pairing-App

**Repository:** https://github.com/RyanCopley/NSO-GameCube-Controller-Pairing-App
**License:** GPL-3.0
**What we use directly:**
- `BumbleBackend.scan_and_connect()` — the working BLE pair flow
- `sw2_protocol.py` — the proprietary 4-step handshake, SPI read/parse logic, encryption attempts loop, button translation
- `_NINTENDO_OUIS` list for MAC-prefix scanning
- The PairingDelegate configuration (Legacy SMP, no MITM, IDENTITY+ENCRYPTION key distribution)

`nsogcd` now bundles an adapted copy of the BLE backend and protocol modules
instead of importing them from an external checkout. Their GPL-3.0 provenance
remains the same. Without Ryan's code, this project would have taken months
instead of one night.

If you find this project useful, please go star Ryan's repo too.

## BlueRetro — darthcloud / Jacques Gagnon

**Repository:** https://github.com/darthcloud/BlueRetro
**License:** Apache-2.0
**Contribution:**
- Original SW2 protocol reverse engineering (`main/bluetooth/hidp/sw2.h` + `sw2.c`)
- Discovered the 4-step proprietary pairing handshake
- Documented the fixed crypto nonces (EA BD 47 13... and 40 B0 8A 5F...)
- Defined the input report format we use
- Documented GATT service UUIDs and handle layout
- Identified SPI bond record offsets

BlueRetro is an ESP32-based receiver that uses these reverse-engineered details to make Switch 2 controllers work on real GameCube hardware.

## ndeadly — switch2_input_viewer

**Gist:** https://gist.github.com/ndeadly/7d27aa63e2f653a902a2474dbcbc08b3
**Contribution:**
- Identified Bluetooth manufacturer ID `0x0553` for Nintendo BLE devices
- Documented embedded VID/PID location in advertising manufacturer data
- Authored `write_spi_memory()` function (declared the SPI write structure even though their code didn't exercise it)
- Documented pair record offsets: `host_address1=0x08`, `host_address2=0x30`, `LTK=0x1A`
- Provided a Bleak-based reference implementation for macOS

## Vicki Pfau (endrift) — hid-switch2 Linux kernel patch

**Reference:** Linux kernel `linux-input` mailing list patch series
**Mirror:** https://github.com/Senko-p/hid-switch2-dkms
**Contribution:**
- Original Linux kernel HID driver design for Switch 2 controllers (USB only)
- Full flash subcommand enum: FLASH_READ_BLOCK (0x01), FLASH_WRITE_BLOCK (0x02), FLASH_ERASE_BLOCK (0x03), FLASH_READ (0x04), FLASH_WRITE (0x05)
- Without this enum, we wouldn't have known to try cmd=0x02 sub=0x05 for SPI write

## Nohzockt — Switch2-Controllers

**Repository:** https://github.com/Nohzockt/Switch2-Controllers
**Contribution:**
- USB-mode "enabler" packet bytes (`03 91 00 0d ...` and `09 91 00 07 ...`) that wake the SW2 vendor channel
- C reference implementations for Linux

## SDL Project — flibitijibibo (Ethan Lee)

**Repository:** https://github.com/libsdl-org/SDL
**Contribution:**
- `SDL_hidapi_switch2.c` — SDL's USB driver for the controller family (merged 2025-08-28)
- gamecontrollerdb mapping for VID 0x057E:0x2073
- This is what makes our cloned uinput device get recognized as a "real" GameCube controller in any SDL-based application (Dolphin, Steam, RetroArch, etc.)

## Bluetooth Stack — Google's Bumble Project

**Repository:** https://github.com/google/bumble
**License:** Apache-2.0
**Contribution:**
- Pure Python BLE stack we use to bypass BlueZ's limitations
- Allows raw HCI access for proprietary protocols

## Linux input subsystem — evdev / uinput

The Linux kernel's `uinput` module is what lets us create virtual gamepads from userspace. This is what makes "any application can use this controller" work.

## Bazzite team — KyleGospo and others

**Project:** https://github.com/ublue-os/bazzite
This was developed and tested on Bazzite. The Bazzite team's work on the immutable Fedora gaming distro is what makes this kind of project possible without breaking the OS.

---

## What This Project (`nsogcd`) Adds

Three novel reverse-engineering findings:

1. **SPI WRITE encoding empirically confirmed** — interface byte must be `0x01` (BLE) even over USB transport
2. **BD_ADDR discovery via SET_BDADDR ack** — the controller leaks its own BLE address in the pairing handshake response
3. **Full byte-level SPI bond region map** — documented every byte from `0x1fa000` through `0x1fa080`

Plus the packaging:
- systemd service with an explicit first-pairing command and button-wake reconnect
- Native GameCube motor on/off output verified on a Bazzite Legion Go
- uinput device clone matching SDL's expected NSO GC identity
- Distro-adaptive install script
- Documentation
