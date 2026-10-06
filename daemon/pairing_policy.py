"""Explicit first pairing and host-targeted background reconnection."""

import json
import os
import re
import time
from pathlib import Path

STATE_FILE = Path('/var/lib/nsogcd/controllers.json')
PAIR_WINDOW = Path('/run/nsogcd/pair-until')
PAIR_WINDOW_SECONDS = 120
_MAC = re.compile(r'^(?:[0-9A-F]{2}:){5}[0-9A-F]{2}$')


def open_pairing_window():
    """Let the running daemon accept an unbonded GameCube controller briefly."""
    PAIR_WINDOW.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = PAIR_WINDOW.with_suffix('.tmp')
    temporary.write_text(str(time.time() + PAIR_WINDOW_SECONDS))
    os.chmod(temporary, 0o600)
    temporary.replace(PAIR_WINDOW)


def wait_for_pairing(timeout_seconds: int = 300) -> bool:
    """Keep first-pairing available while an interactive user presses Sync."""
    deadline = time.monotonic() + timeout_seconds
    open_pairing_window()
    renew_at = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            if not PAIR_WINDOW.exists():
                return True
            now = time.monotonic()
            if now >= renew_at:
                open_pairing_window()
                renew_at = now + 60
            time.sleep(0.5)
        return False
    finally:
        PAIR_WINDOW.unlink(missing_ok=True)


class PairingPolicy:
    def __init__(self, host_address: bytes):
        self.host_address = host_address
        try:
            state = json.loads(STATE_FILE.read_text())
            self.known = {mac for value in state['controller_macs']
                          if (mac := str(value).upper()) and _MAC.fullmatch(mac)}
        except (OSError, ValueError, KeyError, TypeError):
            self.known = set()

    @staticmethod
    def _pairing_window_open():
        try:
            return time.time() < float(PAIR_WINDOW.read_text())
        except (OSError, ValueError):
            return False

    def classify(self, address: str, advertisement):
        """Return 'pair', 'reconnect', or None without opening a BLE link."""
        data = getattr(advertisement, 'data', None)
        manufacturer = data.get(0xFF, raw=True) if data is not None else None
        if manufacturer is None:
            # Bleak separates the two-byte Bluetooth company identifier.
            payload = getattr(advertisement, 'manufacturer_data', {}).get(0x0553)
            if payload is not None:
                manufacturer = b'\x53\x05' + payload
        if not manufacturer or len(manufacturer) < 18:
            return None
        # Nintendo company ID, Switch 2 vendor ID, NSO GameCube product ID.
        if manufacturer[:2] != b'\x53\x05' or manufacturer[5:9] != b'\x7e\x05\x73\x20':
            return None
        target_host = manufacturer[12:18]
        if target_host == self.host_address and address in self.known:
            return 'reconnect'
        if target_host == bytes(6) and self._pairing_window_open():
            return 'pair'
        return None

    def remember(self, address: str):
        address = address.upper()
        if not _MAC.fullmatch(address):
            raise ValueError('invalid controller address')
        self.known.add(address)
        STATE_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = STATE_FILE.with_suffix('.tmp')
        temporary.write_text(json.dumps({'controller_macs': sorted(self.known)}) + '\n')
        os.chmod(temporary, 0o600)
        temporary.replace(STATE_FILE)
        PAIR_WINDOW.unlink(missing_ok=True)
