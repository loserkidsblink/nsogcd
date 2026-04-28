#!/usr/bin/env python3
"""NSO GC SPI flash R/W via USB Interface 1 (vendor channel).
Based on BlueRetro sw2.c command formats and Nohzockt enabler init.
"""
import sys, time, struct, argparse, usb.core, usb.util

VID, PID = 0x057E, 0x2073

# Command bytes (BlueRetro sw2.h)
SW2_CMD_READ_SPI    = 0x02
SW2_CMD_SET_LED     = 0x09
SW2_CMD_PAIRING     = 0x15
SW2_TYPE_REQ        = 0x91
SW2_TYPE_RSP        = 0x01
SW2_INT_USB         = 0x00
SW2_INT_BLE         = 0x01
SW2_SUBCMD_READ_SPI = 0x04

# Nohzockt enabler payloads (init the vendor channel)
INIT_DEFAULT = bytes([0x03, 0x91, 0x00, 0x0d, 0x00, 0x08, 0x00, 0x00, 0x01, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
INIT_SET_LED = bytes([0x09, 0x91, 0x00, 0x07, 0x00, 0x08, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

class NSOGC:
    def __init__(self):
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None:
            sys.exit('Controller not found')
        try: dev.reset()
        except Exception as e: print(f"reset: {e}")
        time.sleep(0.3)
        for i in (0, 1):
            try:
                if dev.is_kernel_driver_active(i):
                    dev.detach_kernel_driver(i)
            except Exception:
                pass
        # Claim Interface 1 (vendor) - skip set_configuration (Steam may have config set already)
        cfg = dev.get_active_configuration()
        intf = cfg[(1, 0)]
        usb.util.claim_interface(dev, 1)
        ep_out = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
        ep_in  = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
        if ep_out is None or ep_in is None:
            sys.exit('Could not find bulk endpoints on iface 1')
        self.dev = dev
        self.ep_out = ep_out
        self.ep_in = ep_in
        print(f'iface1 claimed; OUT=0x{ep_out.bEndpointAddress:02x} IN=0x{ep_in.bEndpointAddress:02x}')

    def send(self, data, timeout=1000):
        n = self.dev.write(self.ep_out.bEndpointAddress, data, timeout=timeout)
        return n

    def recv(self, size=64, timeout=1500):
        try:
            return bytes(self.dev.read(self.ep_in.bEndpointAddress, size, timeout=timeout))
        except usb.core.USBError as e:
            return None

    def drain_in(self, total_ms=200):
        """Drain any pending IN data so we get a fresh response."""
        deadline = time.time() + total_ms/1000.0
        while time.time() < deadline:
            r = self.recv(64, timeout=50)
            if r is None or len(r) == 0:
                break

    def init_vendor(self):
        """Send Nohzockt's init packets to wake up the vendor channel."""
        print(f'init: sending DEFAULT report ({INIT_DEFAULT.hex()})')
        self.send(INIT_DEFAULT)
        time.sleep(0.05)
        print(f'init: sending SET_LED report ({INIT_SET_LED.hex()})')
        self.send(INIT_SET_LED)
        time.sleep(0.05)

    def spi_read(self, offset, length):
        """Read 'length' bytes from SPI flash at 'offset'. length max ~64."""
        cmd = bytearray([
            SW2_CMD_READ_SPI, SW2_TYPE_REQ, SW2_INT_USB, SW2_SUBCMD_READ_SPI,
            0x00, 0x08, 0x00, 0x00,
            length & 0xFF,
            0x7e, 0x00, 0x00,
        ])
        cmd += struct.pack('<I', offset)
        # Pad to 16 bytes if shorter
        while len(cmd) < 16:
            cmd.append(0x00)
        self.drain_in()
        print(f'spi_read offset=0x{offset:08x} len={length}')
        print(f'  TX: {bytes(cmd).hex(" ")}')
        self.send(bytes(cmd))
        # Read response
        for attempt in range(5):
            r = self.recv(64, timeout=1500)
            if r is None:
                print(f'  RX[{attempt}]: timeout')
                continue
            print(f'  RX[{attempt}] {len(r)}B: {r.hex(" ")}')
            # SW2 ack format: [cmd, type=01, interface, subcmd, ...payload]
            if len(r) >= 4 and r[1] == SW2_TYPE_RSP and r[0] == SW2_CMD_READ_SPI:
                return r
        return None

    def close(self):
        try:
            usb.util.release_interface(self.dev, 1)
        except Exception:
            pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--init', action='store_true', help='Send vendor init packets first')
    ap.add_argument('--wipe-bond', action='store_true'); ap.add_argument('--read', nargs=2, metavar=('OFFSET_HEX', 'LENGTH'), help='Read SPI flash, e.g. --read 1fa01a 16')
    args = ap.parse_args()
    c = NSOGC()
    try:
        if args.init:
            c.init_vendor()
        if args.read:
            offset = int(args.read[0], 16)
            length = int(args.read[1])
            c.spi_read(offset, length)
        if args.wipe_bond:
            cmd_set_bdaddr_zeros(c)
        if not args.init and not args.read and not args.wipe_bond:
            print('Use --init and/or --read OFFSET_HEX LENGTH')
    finally:
        c.close()

if __name__ == '__main__':
    main()

def cmd_set_bdaddr_zeros(c):
    """Send SET_BDADDR command with all-zeros peer to invalidate the bond."""
    # cmd=0x15 PAIRING, type=0x91 REQ, interface=0x00 USB, subcmd=0x01 STEP1
    # bytes 4-9: 0x00 0x0e 0x00 0x00 0x00 0x02 (header)
    # bytes 10-15: peer BD_ADDR (6 bytes, LE)
    # bytes 16-21: peer BD_ADDR with LSB-1
    pkt = bytes([
        0x15, 0x91, 0x00, 0x01,
        0x00, 0x0e, 0x00, 0x00, 0x00, 0x02,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0xFF, 0x00, 0x00, 0x00, 0x00, 0x00,
    ])
    c.drain_in()
    print(f'SET_BDADDR (zero peer): TX {pkt.hex(" ")}', flush=True)
    c.send(pkt)
    for i in range(5):
        r = c.recv(64, timeout=1500)
        if r is None:
            print(f'  RX[{i}]: timeout', flush=True)
            continue
        print(f'  RX[{i}] {len(r)}B: {r.hex(" ")}', flush=True)
        if len(r) >= 4 and r[0] == 0x15:
            return r
    return None
