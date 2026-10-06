#!/usr/bin/env python3
"""NSO GameCube BLE to Linux uinput gamepad bridge."""
import asyncio, json, os, queue, select, signal, subprocess, sys, logging, time
from pathlib import Path

import evdev
from evdev import UInput, ecodes as e
from gc_controller.ble.sw2_protocol import build_rumble_packet
from pairing_policy import (PAIR_WINDOW, STATE_FILE, PairingPolicy,
                            open_pairing_window, wait_for_pairing)

# Pro Controller VID/PID (Steam Input recognizes this natively)
PRO_VID = 0x057E
PRO_PID = 0x2073
DEVICE_NAME = 'Nintendo GameCube Controller'

# USB report byte/bit -> evdev keycode. The modern layout uses conventional
# shoulder/trigger codes so Steam can identify Z/ZL without device-input setup.
LEGACY_BUTTON_MAP = [
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

MODERN_BUTTON_MAP = [
    (3, 0x01, e.BTN_EAST),       # B
    (3, 0x02, e.BTN_SOUTH),      # A
    (3, 0x04, e.BTN_NORTH),      # Y
    (3, 0x08, e.BTN_WEST),       # X
    (3, 0x10, e.BTN_TR2),        # R full press (R analog remains ABS_RZ)
    (3, 0x20, e.BTN_TR),         # Z = right bumper
    (3, 0x40, e.BTN_START),      # Start (+)
    (4, 0x10, e.BTN_TL2),        # L full press (L analog remains ABS_Z)
    (4, 0x20, e.BTN_TL),         # ZL = left bumper
    (5, 0x01, e.BTN_MODE),       # Home
    (5, 0x02, e.BTN_SELECT),     # Capture
    (5, 0x04, e.BTN_THUMBR),
    (5, 0x08, e.BTN_THUMBL),
]

LAYOUT = os.environ.get('NSOGCD_LAYOUT', 'legacy').lower()
if LAYOUT not in ('legacy', 'modern'):
    raise ValueError(f'unknown NSOGCD_LAYOUT: {LAYOUT}')
BUTTON_MAP = MODERN_BUTTON_MAP if LAYOUT == 'modern' else LEGACY_BUTTON_MAP

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
    e.EV_FF: [e.FF_RUMBLE],
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

def trigger_norm(raw, idle):
    """Remove the controller's nonzero trigger rest value (~30-35)."""
    start = idle + 8  # ignore a few counts of idle noise
    if raw <= start:
        return 0
    return min(255, (raw - start) * 255 // max(1, 230 - start))

class NSOGameCubeDaemon:
    def __init__(self):
        self.ui = None
        self.last_buttons = (0, 0, 0)
        self.last_dpad = (0, 0)
        self.trigger_idle = [50, 50]
        self._running = True
        self._stop_event = asyncio.Event()
        self._ff_effects = {}
        self._ff_playing = {}
        self._motor_on = False
        self._rumble_tid = 0

    def _create_uinput(self):
        self.last_buttons = (0, 0, 0)
        self.last_dpad = (0, 0)
        self._ff_effects.clear()
        self._ff_playing.clear()
        self._motor_on = False
        self._rumble_tid = 0
        self.trigger_idle = [50, 50]
        self.ui = UInput(UINPUT_CAPS, name=DEVICE_NAME, vendor=PRO_VID, product=PRO_PID, version=0x100)
        log.info(f'Created uinput device: {DEVICE_NAME}')

    def _destroy_uinput(self):
        self._ff_effects.clear()
        self._ff_playing.clear()
        if self.ui:
            try: self.ui.close()
            except Exception: pass
            self.ui = None

    def _handle_feedback(self):
        """Acknowledge effect uploads and track playback from the virtual pad."""
        if self.ui is None or self.ui.device is None:
            return
        if not select.select([self.ui.fd], [], [], 0)[0]:
            return
        for event in self.ui.read():
            if event.type == e.EV_UINPUT and event.code == e.UI_FF_UPLOAD:
                upload = self.ui.begin_upload(event.value)
                try:
                    effect = upload.effect
                    if effect.type == e.FF_RUMBLE:
                        rumble = effect.u.ff_rumble_effect
                        self._ff_effects[effect.id] = (
                            max(rumble.strong_magnitude, rumble.weak_magnitude),
                            effect.ff_replay.length,
                            effect.ff_replay.delay,
                        )
                        upload.retval = 0
                    else:
                        upload.retval = -22  # EINVAL
                finally:
                    self.ui.end_upload(upload)
            elif event.type == e.EV_UINPUT and event.code == e.UI_FF_ERASE:
                erase = self.ui.begin_erase(event.value)
                try:
                    self._ff_effects.pop(erase.effect_id, None)
                    self._ff_playing.pop(erase.effect_id, None)
                    erase.retval = 0
                finally:
                    self.ui.end_erase(erase)
            elif event.type == e.EV_FF:
                if event.value and event.code in self._ff_effects:
                    magnitude, length, delay = self._ff_effects[event.code]
                    start = time.monotonic() + delay / 1000
                    end = start + max(length, 1) * min(event.value, 100) / 1000
                    self._ff_playing[event.code] = (magnitude, start, end)
                else:
                    self._ff_playing.pop(event.code, None)

    async def _tick_rumble(self, backend, mac):
        now = time.monotonic()
        for effect_id, (_, _, end) in list(self._ff_playing.items()):
            if now >= end:
                self._ff_playing.pop(effect_id, None)
        motor_on = any(mag > 0 and start <= now
                       for mag, start, _ in self._ff_playing.values())
        if motor_on == self._motor_on:
            return
        if await backend.send_rumble(mac, build_rumble_packet(motor_on, self._rumble_tid)):
            self._motor_on = motor_on
            self._rumble_tid = (self._rumble_tid + 1) & 0x0F
        else:
            log.warning('rumble command failed')

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
            for i, (code, raw) in enumerate(((e.ABS_Z, data[13]),
                                             (e.ABS_RZ, data[14]))):
                if 16 <= raw < self.trigger_idle[i]:
                    self.trigger_idle[i] = raw
                self.ui.write(e.EV_ABS, code, trigger_norm(raw, self.trigger_idle[i]))
        except Exception:
            pass
        self.ui.syn()

    async def session(self):
        """One pair-and-serve session. Blocks until disconnect."""
        from gc_controller.ble.bumble_backend import BumbleBackend
        b = BumbleBackend()
        disconnected = asyncio.Event()
        def status(s): log.info(f'STATUS: {s}')
        def disc():
            log.info('controller disconnected')
            disconnected.set()
        q = queue.Queue()
        mac = None
        try:
            await b.open(hci_index=int(os.environ.get('NSOGCD_HCI_INDEX', '0')))
            policy = PairingPolicy(b.host_address)
            log.info('Bumble backend opened, scanning for known controllers...')
            mac = await b.scan_and_connect(slot_index=0, data_queue=q,
                                            on_status=status, on_disconnect=disc,
                                            accept_advertisement=policy.classify,
                                            scan_timeout=300.0, connect_timeout=30.0,
                                            stop_event=self._stop_event)
            if not mac:
                log.warning('pair failed/timeout')
                return False
            log.info('%s: %s', b.last_connection_mode.upper(), mac)
            if b.last_connection_mode == 'pair':
                policy.remember(mac)
            self._create_uinput()
            # Process input until disconnected
            while not disconnected.is_set() and self._running:
                self._handle_feedback()
                await self._tick_rumble(b, mac)
                try:
                    while True:
                        d = q.get_nowait()
                        self._handle_frame(d)
                except queue.Empty:
                    pass
                await asyncio.sleep(0.005)
        finally:
            try:
                if mac and self._motor_on:
                    await b.send_rumble(mac, build_rumble_packet(False, self._rumble_tid))
            finally:
                self._destroy_uinput()
                await b.close()
        return True

    async def run(self):
        while self._running:
            try:
                await self.session()
            except Exception as ex:
                log.exception(f'session error: {ex}')
            if not self._running:
                break
            log.info('session ended, restarting in 5s')
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    def stop(self):
        log.info('stop requested')
        self._running = False
        self._stop_event.set()

def main():
    if len(sys.argv) > 1:
        if sys.argv[1:] in (['status'], ['status', '--json']):
            active = subprocess.run(['systemctl', 'is-active', '--quiet', 'nsogcd'],
                                    check=False).returncode == 0
            try:
                devices = Path('/proc/bus/input/devices').read_text()
                connected = any(
                    'N: Name="Nintendo GameCube Controller"' in block
                    and 'P: Phys=py-evdev-uinput' in block
                    for block in devices.split('\n\n')
                )
            except OSError:
                connected = False
            try:
                known_count = len(json.loads(STATE_FILE.read_text())['controller_macs'])
            except (OSError, ValueError, KeyError, TypeError):
                known_count = None
            try:
                pair_seconds = max(0, int(float(PAIR_WINDOW.read_text()) - time.time()))
            except PermissionError:
                pair_seconds = None
            except (OSError, ValueError):
                pair_seconds = 0
            info = {'service': 'active' if active else 'inactive',
                    'controller': 'connected' if connected else 'waiting',
                    'known_controllers': known_count,
                    'pairing_seconds_left': pair_seconds}
            if sys.argv[-1] == '--json':
                print(json.dumps(info))
            else:
                print(f"Service: {info['service']}")
                print(f"GameCube controller: {info['controller']}")
                print(f"Known controllers: {known_count if known_count is not None else 'unknown'}")
                if pair_seconds is None:
                    print('Pairing window: unknown (run with sudo for details)')
                else:
                    print(f"Pairing window: {pair_seconds}s left" if pair_seconds
                          else 'Pairing window: closed')
            return
        if sys.argv[1:] not in (['pair'], ['pair', '--wait']):
            raise SystemExit('usage: nsogcd [status [--json] | pair [--wait]]')
        if os.geteuid() != 0:
            raise SystemExit('run sudo nsogcd pair to allow first pairing')
        if sys.argv[1:] == ['pair', '--wait']:
            print('Hold Sync until the LEDs sweep. Waiting up to 5 minutes...',
                  flush=True)
            if wait_for_pairing():
                print('Controller paired.')
                return
            raise SystemExit('Pairing timed out. Run sudo nsogcd pair --wait to retry.')
        open_pairing_window()
        print('Pairing enabled for 2 minutes. Hold Sync until the LEDs sweep.')
        return
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
