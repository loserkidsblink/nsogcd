#!/usr/bin/env python3
"""NSO GameCube Controller Daemon (nsogcd)
Pairs the controller via BLE using RyanCopley's BumbleBackend, exposes input
as a uinput Switch Pro Controller for Steam Input native recognition.
Requires HCI takeover (bluetoothd is masked while running).
"""
import asyncio, sys, queue, os, signal, time, subprocess, logging
sys.path.insert(0, '/home/bazzite/nso-app/src')

import evdev
from evdev import UInput, ecodes as e

# Pro Controller VID/PID (Steam Input recognizes this natively)
PRO_VID = 0x057E
PRO_PID = 0x2073
DEVICE_NAME = 'Nintendo GameCube Controller'

# Button mapping: USB report byte/bit -> evdev keycode
BUTTON_MAP = [
    (3, 0x01, e.BTN_EAST),       # B
    (3, 0x02, e.BTN_SOUTH),      # A
    (3, 0x04, e.BTN_NORTH),      # Y (top)
    (3, 0x08, e.BTN_WEST),       # X (left)
    (3, 0x10, e.BTN_TR),         # R
    (3, 0x20, e.BTN_Z),          # Z
    (3, 0x40, e.BTN_START),      # Start (+)
    (4, 0x10, e.BTN_TL),         # L
    (4, 0x20, e.BTN_TL2),        # ZL
    (5, 0x01, e.BTN_MODE),       # Home
    (5, 0x02, e.BTN_SELECT),     # Capture
    (5, 0x04, e.BTN_THUMBR),     # GR (mapped to R-stick click)
    (5, 0x08, e.BTN_THUMBL),     # GL
]

# D-Pad: byte/bit -> (axis, value)
DPAD_MAP = [
    (4, 0x08, e.ABS_HAT0Y, -1),  # Up
    (4, 0x01, e.ABS_HAT0Y,  1),  # Down
    (4, 0x04, e.ABS_HAT0X, -1),  # Left
    (4, 0x02, e.ABS_HAT0X,  1),  # Right
]

UINPUT_CAPS = {
    e.EV_KEY: [c for _, _, c in BUTTON_MAP],
    e.EV_ABS: [
        (e.ABS_X,    evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
        (e.ABS_Y,    evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
        (e.ABS_RX,   evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
        (e.ABS_RY,   evdev.AbsInfo(0, -32768, 32767, 0, 0, 0)),
        (e.ABS_Z,    evdev.AbsInfo(0, 0, 255, 0, 0, 0)),  # L trigger analog
        (e.ABS_RZ,   evdev.AbsInfo(0, 0, 255, 0, 0, 0)),  # R trigger analog
        (e.ABS_HAT0X, evdev.AbsInfo(0, -1, 1, 0, 0, 0)),
        (e.ABS_HAT0Y, evdev.AbsInfo(0, -1, 1, 0, 0, 0)),
    ],
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('nsogcd')

def unpack_12bit_xy(data6):
    """Unpack 6 bytes of packed 12-bit XY values into (x, y)."""
    if len(data6) < 3:
        return (0, 0)
    x = ((data6[1] & 0x0F) << 8) | data6[0]
    y = (data6[2] << 4) | (data6[1] >> 4)
    return (x, y)

def stick_norm(raw, neutral=0x800, span=0x600):
    """Normalize 12-bit stick to int16 evdev range."""
    v = (raw - neutral) * 32767 // span
    return max(-32768, min(32767, v))

class NSOGameCubeDaemon:
    def __init__(self):
        self.ui = None
        self.last_buttons = (0, 0, 0)
        self.last_dpad = (0, 0)
        self._running = True

    def _create_uinput(self):
        self.ui = UInput(UINPUT_CAPS, name=DEVICE_NAME, vendor=PRO_VID, product=PRO_PID, version=0x100)
        log.info(f'Created uinput device: {DEVICE_NAME}')

    def _destroy_uinput(self):
        if self.ui:
            try: self.ui.close()
            except Exception: pass
            self.ui = None

    def _handle_frame(self, data):
        if len(data) < 16 or self.ui is None: return
        # Buttons
        cur = (data[3], data[4], data[5])
        if cur != self.last_buttons:
            for byte_idx, mask, code in BUTTON_MAP:
                was = (self.last_buttons[byte_idx-3] & mask) != 0
                now = (cur[byte_idx-3] & mask) != 0
                if was != now:
                    self.ui.write(e.EV_KEY, code, 1 if now else 0)
            # D-Pad
            dpad_x = 0
            dpad_y = 0
            if cur[1] & 0x08: dpad_y = -1
            if cur[1] & 0x01: dpad_y = 1
            if cur[1] & 0x04: dpad_x = -1
            if cur[1] & 0x02: dpad_x = 1
            if (dpad_x, dpad_y) != self.last_dpad:
                self.ui.write(e.EV_ABS, e.ABS_HAT0X, dpad_x)
                self.ui.write(e.EV_ABS, e.ABS_HAT0Y, dpad_y)
                self.last_dpad = (dpad_x, dpad_y)
            self.last_buttons = cur
        # Sticks (bytes 6-11)
        try:
            lx, ly = unpack_12bit_xy(data[6:9])
            rx, ry = unpack_12bit_xy(data[9:12])
            self.ui.write(e.EV_ABS, e.ABS_X,  stick_norm(lx))
            self.ui.write(e.EV_ABS, e.ABS_Y,  -stick_norm(ly))  # Y inverted typical
            self.ui.write(e.EV_ABS, e.ABS_RX, stick_norm(rx))
            self.ui.write(e.EV_ABS, e.ABS_RY, -stick_norm(ry))
        except Exception:
            pass
        # Triggers (bytes 13, 14)
        try:
            self.ui.write(e.EV_ABS, e.ABS_Z,  data[13])
            self.ui.write(e.EV_ABS, e.ABS_RZ, data[14])
        except Exception:
            pass
        self.ui.syn()

    async def session(self):
        """One pair-and-serve session. Blocks until disconnect."""
        from gc_controller.ble.bumble_backend import BumbleBackend
        b = BumbleBackend()
        await b.open(hci_index=0)
        log.info('Bumble HCI opened, waiting for sync press...')

        disconnected = asyncio.Event()
        def status(s): log.info(f'STATUS: {s}')
        def disc():
            log.info('controller disconnected')
            disconnected.set()
        q = queue.Queue()
        try:
            mac = await b.scan_and_connect(slot_index=0, data_queue=q,
                                            on_status=status, on_disconnect=disc,
                                            scan_timeout=300.0, connect_timeout=30.0)
            if not mac:
                log.warning('pair failed/timeout')
                return False
            log.info(f'PAIRED: {mac}')
            self._create_uinput()
            # Process input until disconnected
            while not disconnected.is_set() and self._running:
                try:
                    while True:
                        d = q.get_nowait()
                        self._handle_frame(d)
                except queue.Empty:
                    pass
                await asyncio.sleep(0.005)
        finally:
            self._destroy_uinput()
        return True

    async def run(self):
        while self._running:
            try:
                await self.session()
            except Exception as ex:
                log.exception(f'session error: {ex}')
            log.info('session ended, restarting in 5s')
            await asyncio.sleep(5)

    def stop(self):
        log.info('stop requested')
        self._running = False

def main():
    d = NSOGameCubeDaemon()
    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, d.stop)
    try:
        loop.run_until_complete(d.run())
    finally:
        loop.close()

if __name__ == '__main__':
    main()
