# Reverse Engineering Findings

This document captures everything we learned reverse-engineering the NSO GameCube controller for Linux pairing. Three findings are novel; the rest builds on prior work.

## Three Novel Discoveries

### 1. SPI Write Encoding Over USB

Public sources (BlueRetro, Ryan Copley) only document SPI READ. Vicki Pfau's `hid-switch2` Linux patch declares `FLASH_WRITE = 0x05` as a subcommand but no public code exercises it.

**We confirmed it works** with this exact encoding:

```
cmd=0x02, type=0x91, interface=0x01, subcmd=0x05, addr, payload
```

Critical: the **interface byte must be 0x01 (BLE) even when sent over USB transport**. Sending with `interface=0x00` (USB) returns an ack but does not modify SPI flash. We verified with 16-byte chunks of zeros written to the bond region (offset 0x1fa000), then confirmed via subsequent SPI reads that the bytes were genuinely zeroed.

This finding enables:
- SPI hot-swap tools (save/restore bond state for multi-host setups)
- Bond invalidation without console-side intervention
- Future research into controller firmware modification

### 2. BD_ADDR Discovery via SET_BDADDR Acknowledgment

When the SET_BDADDR command (`cmd=0x15 sub=0x01`) is sent with all-zero BD_ADDR bytes, the controller responds with an acknowledgment that includes 6 bytes matching its own BLE BD_ADDR.

We discovered this by sending:
```
15 91 00 01 00 0e 00 00 00 02
00 00 00 00 00 00 00 00 00 00 00 00
```

And receiving:
```
15 01 00 01 00 f8 00 00  01 04 01  3c bb 92 ab a9 3c
                          ^^^^^^^^  ^^^^^^^^^^^^^^^^
                          metadata  BD_ADDR (LE wire order)
```

The bytes `3c bb 92 ab a9 3c` decoded MSB-first give `3C:A9:AB:92:BB:3C` — a Nintendo OUI (3C:A9:AB) BD_ADDR.

This means a tool can determine the controller's BLE BD_ADDR purely over USB, without scanning. Useful for pre-staging BlueZ pairing records or implementing a userspace "BT menu pair" helper.

### 3. Full SPI Bond Record Byte-Level Map

While Ryan Copley's code reads specific offsets, the complete byte-level layout has not been published. We documented it byte-by-byte by comparing SPI dumps before/after operations:

```
0x1fa000:  02         status flag (0x02 = bonded valid, 0x00 = empty)
0x1fa001:  00 x7      padding
0x1fa008:  XX x6      peer (host) BD_ADDR (BLE wire order: LSB first)
0x1fa00e:  XX XX      EDIV (encrypted diversifier, LE uint16)
0x1fa010:  XX x8      RAND (random number, 8 bytes)
0x1fa018:  00 00      padding
0x1fa01a:  XX x16     LTK (16 bytes, BLE wire order)
0x1fa02a:  00 x22     padding
0x1fa040:  XX x6      peer BD_ADDR (LSB-1 backup, BlueRetro convention)
0x1fa046:  XX x16     LTK (duplicate)
```

The duplicate LTK at offset 0x1fa042/0x1fa046 is a BlueRetro-documented design choice — used as fallback if primary write fails.

## Pre-Existing Knowledge We Built On

### From BlueRetro (darthcloud)
- Two custom GATT services with non-standard UUIDs
- 4-step proprietary pairing handshake with fixed nonces
- Input report format (63 bytes, BlueRetro layout)
- USB Interface 1 = vendor SW2 channel

### From Ryan Copley
- Bumble configuration: Legacy SMP, no MITM, IDENTITY+ENCRYPTION key distribution
- Pair flow handles SMP "failure" gracefully and continues to proprietary handshake
- Three-attempt LTK encryption strategy (extracted, zeros, reversed)
- LTK SPI offset 0x1A within bond record

### From ndeadly
- Bluetooth manufacturer ID 0x0553 in advertising data
- Embedded VID/PID at offsets 3-7 of mfr data
- write_spi_memory function declaration (declared but not used in their code)
- Pair record offsets: host_address1=0x08, host_address2=0x30, LTK=0x1A

### From Vicki Pfau (endrift) hid-switch2-dkms
Flash subcommand enum:
- 0x01 FLASH_READ_BLOCK
- 0x02 FLASH_WRITE_BLOCK
- 0x03 FLASH_ERASE_BLOCK
- 0x04 FLASH_READ
- 0x05 FLASH_WRITE

## Things That Did Not Work

### BlueZ-Native Auto-Reconnect

We tried injecting our captured LTK into BlueZ's `/var/lib/bluetooth/<adapter>/<device>/info` file. BlueZ correctly recognized the controller as paired but **rejected its SMP request** because:
- Controller demands SC + MITM + CT2 (auth req byte 0x2d)
- BlueZ with NoInputNoOutput cannot satisfy MITM
- BlueZ's LTK encryption attempt happens silently and does not match controller's expectations

This is a fundamental BlueZ limitation, not a flaw in our LTK extraction. macOS CoreBluetooth and Windows BLE handle this controller's SMP request natively. BlueZ does not. Watch BlueZ pull request #2009 ("BLE-HID/Switch 2 support") for upstream fix.

### USB "Enter BLE Pair Mode" Command

We fuzzed cmd 0x00-0x07 with subcmd 0x00/0x01 looking for an undocumented USB command that would force the controller into BLE advertising mode. Found 5 undocumented responding commands but none triggered BLE advertising. cmd=0x07 sub=0x01 caused a controller reset.

The conclusion (consistent with Ryan Copley's claim of "full USB command space probed without finding one"): **only the physical sync button triggers BLE advertising**. There is no USB shortcut.

### Other Investigations
- LTK byte order: tried both MSB-first and LSB-first in BlueZ info file. Neither was accepted by BlueZ's encryption attempt.
- Various Authenticated values in BlueZ info file (0, 1, 2): none made BlueZ accept the LTK before falling through to SMP.
- Spoofing Switch 2 BD_ADDR in scan: directed adv from controller still not received by chip with privacy enabled.

## Methodology Notes

All findings verified empirically with:
- Bumble-based USB+BLE access (Python)
- Direct HCI manipulation via `btmgmt` and `btmon`
- Bond region SPI before/after dumps
- Full daemon log capture during pair flow

Test environment: Bazzite 43 (Fedora Kinoite immutable), kernel 6.17.7-ba29, BlueZ 5.84, on Lenovo Legion Go 83E1 with internal MediaTek Bluetooth.
