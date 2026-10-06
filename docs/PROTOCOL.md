# Switch 2 SW2 BLE Protocol Reference

This document captures the proprietary BLE protocol used by the Nintendo Switch 2 controller family (NSO GameCube, Pro Controller 2, Joy-Con 2 L/R). Synthesized from reverse engineering by [BlueRetro](https://github.com/darthcloud/BlueRetro), [ndeadly](https://gist.github.com/ndeadly/7d27aa63e2f653a902a2474dbcbc08b3), [Vicki Pfau](https://github.com/Senko-p/hid-switch2-dkms), [RyanCopley](https://github.com/RyanCopley/NSO-GameCube-Controller-Pairing-App), and original work documented in this project.

## 1. Hardware Identifiers

| Family Member | USB VID | USB PID |
|---|---|---|
| NSO GameCube | `0x057E` | `0x2073` |
| Pro Controller 2 | `0x057E` | `0x2069` |
| Joy-Con 2 L | `0x057E` | `0x2067` |
| Joy-Con 2 R | `0x057E` | `0x2066` |

Bluetooth identifiers:
- BLE Manufacturer Company ID (Bumble/Linux): `0x0553`
- BLE Manufacturer Company ID (Bleak/macOS docs): `0x037E` (USB VID byte-flipped)
- BLE BD_ADDR Nintendo OUI prefixes: `3C:A9:AB`, `98:B6:E9`, `7C:BB:8A`, `58:2F:40`, `D8:6B:F7`, `04:03:D6`, `A4:C0:E1`, `40:F4:07`

## 2. USB Topology

Two interfaces are exposed:
- **Interface 0**: Standard HID class (class 3). Bulk/interrupt endpoints. Used by Steam Input native USB support.
- **Interface 1**: Vendor specific (class 255). Bulk endpoints (`0x02` OUT, `0x82` IN). Used for the SW2 protocol.

## 3. SW2 Command Frame Structure

All commands sent and received over the SW2 channel (Interface 1 bulk over USB, GATT handle `0x0014` over BLE) follow this 16-byte structure:

```
Offset | Size | Field        | Description
-------|------|--------------|------------------------------------------
  0    |  1   | cmd          | Command code
  1    |  1   | type         | 0x91 REQ, 0x01 RSP, 0x00 ERR
  2    |  1   | interface    | 0x00 USB, 0x01 BLE
  3    |  1   | subcmd       | Subcommand code
  4    |  4   | header       | Length/flags. 0x0008 read-only, 0x0008+N for data
  8    |  1   | data_length  | Bytes of payload following the address
  9    |  3   | constant     | Always 0x7E 0x00 0x00 (purpose unknown)
 12    |  4   | address      | Target address (LE), or zero
 16    |  N   | payload      | Variable, depends on command
```

For READ operations, no payload follows the address. For WRITE operations, payload contains the bytes to write at `address`.

## 4. Known Commands

### `cmd=0x02` — SPI Flash Operations

| subcmd | Operation | Notes |
|---|---|---|
| `0x01` | Flash read alt | Returns version info (~24 bytes including SYS marker) |
| `0x02` | Flash write block | Larger writes, may trigger device reset |
| `0x03` | Flash erase block | Returns error type but may also work |
| `0x04` | **SPI READ** | Documented and widely used |
| `0x05` | **SPI WRITE** | **Undocumented in public source. Requires `interface=0x01` (BLE) byte even when sent over USB transport.** |

### `cmd=0x09` — LED Control

| subcmd | Operation |
|---|---|
| `0x07` | Set player LED mask |

### `cmd=0x15` — Pairing Handshake

| subcmd | Operation | Payload |
|---|---|---|
| `0x01` | STEP1: Set host BD_ADDR | `0x00 0x0e 0x00 0x00 0x00 0x02` + host BD_ADDR (6) + host BD_ADDR-1 (6) |
| `0x04` | STEP2: Send fixed nonce 1 | `0xea 0xbd 0x47 0x13 0x89 0x35 0x42 0xc6 0x79 0xee 0x07 0xf2 0x53 0x2c 0x6c 0x31` |
| `0x02` | STEP3: Send fixed nonce 2 | `0x40 0xb0 0x8a 0x5f 0xcd 0x1f 0x9b 0x41 0x12 0x5c 0xac 0xc6 0x3f 0x38 0xa0 0x73` |
| `0x03` | STEP4: Finalize | Empty |

The 4-step handshake is required after MTU exchange and GATT service enable, before LE encryption. The fixed nonces are not session-derived; they appear to be Nintendo's shared secret embedded in firmware on both sides.

### `cmd=0x03 sub=0x0d` — USB Mode Init (Nohzockt enabler)

Sent over USB Interface 1 to wake the vendor channel before any other commands:

```
03 91 00 0d 00 08 00 00 01 00 FF FF FF FF FF FF
```

## 5. SPI Bond Record Layout (`0x001fa000`)

The pair record at SPI offset `0x001fa000` is 0x80 bytes total. Structure:

```
Offset      | Size | Field
------------|------|--------------------------------------
0x1fa000    |  1   | Status flag (0x02 = bonded valid, 0x00 = empty)
0x1fa001    |  7   | Padding (zeros)
0x1fa008    |  6   | Peer (host) BD_ADDR (LE wire byte order)
0x1fa00e    |  2   | EDIV (encrypted diversifier, little-endian uint16)
0x1fa010    |  8   | RAND (random number, 8 bytes)
0x1fa018    |  2   | Padding
0x1fa01a    | 16   | LTK (Long-Term Key, BLE wire byte order — reverse for human display)
0x1fa02a    | 22   | Padding
0x1fa040    |  6   | Peer BD_ADDR (LSB-1 backup copy, BlueRetro convention)
0x1fa046    | ...  | Additional padding/duplicates of LTK
```

For Just Works pairing, EDIV and RAND are typically `0x0000` and `00 00 00 00 00 00 00 00`. The LTK is what's used for HCI LE Enable Encryption.

## 6. GATT Layout

Two custom services (no HID-over-GATT):

| Service UUID | Purpose |
|---|---|
| `00c5af5d-1964-4e30-8f51-1956f96bd280` | SW2 service enable (write `0x01 0x00` to handle 0x0005) |
| `ab7de9be-89fe-49ad-828f-118f09df7fd0` | Input/output/command channel |

Key handles:
- `0x0005` — service enable (write `0x01 0x00`)
- `0x000A` — input report (legacy/native format)
- `0x000B` — input report CCCD
- `0x000E` — input report (BlueRetro 63-byte format)
- `0x0014` — command write
- `0x0016` — command + rumble write
- `0x001A` — command response
- `0x001B` — command response CCCD

The NSO GameCube controller accepted native motor output on BLE value handle
`0x0016` in our Legion Go test. The BLE on/off packet built by
`build_rumble_packet` uses a rolling transaction ID. The Linux daemon sends
native on/off output at `FF_RUMBLE` effect transitions, preserving game timing.
The separate `0x0A` command on `0x0014` plays built-in samples; repeatedly
playing sample 2 produced harsh, long rumble in Melee Unlocked and should not
be used for game force feedback.

## 7. Input Report Format (BlueRetro layout, 63 bytes)

```
Offset | Size | Field
-------|------|------------------------------------
0x00   |  4   | reserved/header
0x04   |  4   | buttons (uint32 LE, see button mask below)
0x08   |  2   | reserved
0x0A   |  6   | stick axes (packed 12-bit: LX, LY, RX, RY)
0x10   | 44   | IMU/accel/gyro
0x3C   |  1   | left trigger analog (0x00-0xFF)
0x3D   |  1   | right trigger analog
0x3E   |  1   | reserved
```

Button uint32 mask bits:
```
0x00000001 Y       0x00010000 D-Down     0x01000000 GR
0x00000002 X       0x00020000 D-Up       0x02000000 GL
0x00000004 B       0x00040000 D-Right
0x00000008 A       0x00080000 D-Left
0x00000040 R       0x00400000 L
0x00000080 ZR      0x00800000 ZL
0x00000200 Plus
0x00001000 Home
0x00002000 Capture
0x00004000 Chat
```

## 8. SMP Pairing Quirks

When a host attempts standard SMP pairing with the controller, the controller responds:
- `Pairing Request (0x01)`: requests `Bonding + MITM + SC + CT2` (auth requirement byte `0x2d`)
- If host can't satisfy MITM (no IO capability), controller `Pairing Failed (0x05)`

This means **Linux BlueZ with NoInputNoOutput cannot complete standard SMP** with the controller — Project Bumble/userspace solutions bypass standard SMP and run the proprietary handshake (cmd 0x15) on top of an unencrypted ATT channel, then use the LTK extracted from the controller's SPI to encrypt the link via HCI LE Enable Encryption.

## 9. Special Encoding Notes

### SPI WRITE Interface Byte Quirk
The SPI WRITE command (`cmd=0x02 sub=0x05`) only takes effect if the interface byte is `0x01` (BLE), even when the command is sent over USB transport. Sending with `interface=0x00` (USB) returns an ack but does not modify SPI.

### LTK Byte Order
The LTK as stored in SPI at offset `0x1fa01a` is in BLE wire byte order (LSB-first). When using this with `HCI_LE_Enable_Encryption_Command`, the order should match what the host stack expects (Bumble accepts wire-order directly; BlueZ info file expects MSB-first display order).

### BD_ADDR Discovery via SET_BDADDR ack
When `cmd=0x15 sub=0x01` (PAIRING STEP1) is sent with all-zero BD_ADDR, the controller's response includes 6 bytes that match its own BLE BD_ADDR. This provides a way to determine the controller's BD_ADDR over USB without scanning.
