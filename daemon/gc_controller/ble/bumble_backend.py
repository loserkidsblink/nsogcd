"""
Bumble BLE Backend

Linux-only BLE backend using Google Bumble with raw HCI sockets.
Bypasses BlueZ entirely for full control over SMP key distribution.
"""

import asyncio
import queue
from typing import Callable, Optional

from bumble.device import Device, Peer, ConnectionParametersPreferences
from bumble.hci import Address, HCI_LE_1M_PHY, HCI_LE_2M_PHY, OwnAddressType
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport
from bumble import smp  # noqa: F401

from .sw2_protocol import sw2_init, translate_ble_to_usb

# Known Nintendo BLE MAC OUI prefixes (first 3 octets)
_NINTENDO_OUIS = (
    '3C:A9:AB', '98:B6:E9', '7C:BB:8A', '58:2F:40',
    'D8:6B:F7', '04:03:D6', 'A4:C0:E1', '40:F4:07',
)


class BumbleBackend:
    """Manages HCI transport and Bumble Device for BLE connections."""

    def __init__(self):
        self._transport = None
        self._device: Optional[Device] = None
        self._connections: dict[str, object] = {}  # mac -> connection
        self._peers: dict[str, Peer] = {}  # mac -> Peer
        self._hci_index: Optional[int] = None
        self.last_connection_mode: Optional[str] = None

    @property
    def is_open(self) -> bool:
        return self._device is not None

    @property
    def host_address(self) -> bytes:
        """Address stored in a controller's host-targeted wake advertisement."""
        return bytes(self._device.public_address)

    async def open(self, hci_index: int):
        """Open the HCI transport and power on the Bumble device."""
        self._hci_index = hci_index
        transport_name = f"hci-socket:{hci_index}"

        self._transport = await open_transport(transport_name)
        hci_source, hci_sink = self._transport

        self._device = Device.with_hci(
            "Bumble-GC",
            Address("F0:F1:F2:F3:F4:F5"),
            hci_source,
            hci_sink,
        )

        # Configure SMP for Legacy "Just Works" with exact BlueRetro key distribution
        self._device.pairing_config_factory = lambda connection: PairingConfig(
            sc=False,
            mitm=False,
            bonding=True,
            delegate=PairingDelegate(
                io_capability=PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT,
                local_initiator_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
                ),
                local_responder_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
                ),
            ),
        )

        await self._device.power_on()

    async def scan_and_connect(
        self,
        slot_index: int,
        data_queue: queue.Queue,
        on_status: Callable[[str], None],
        on_disconnect: Callable[[], None],
        target_address: Optional[str] = None,
        exclude_addresses: Optional[list[str]] = None,
        accept_advertisement: Optional[Callable[[str, object], Optional[str]]] = None,
        scan_timeout: float = 15.0,
        connect_timeout: float = 15.0,
        stop_event: Optional[asyncio.Event] = None,
    ) -> Optional[str]:
        """Scan for an NSO GC controller, connect, pair, and init SW2 protocol.

        Args:
            slot_index: Controller slot (0-3)
            data_queue: Queue for input data (64-byte packets with 0x00 prefix)
            on_status: Status message callback
            on_disconnect: Callback for unexpected disconnect
            target_address: If set, connect directly to this MAC (skip scan)
            exclude_addresses: MACs to skip during scanning (other slots' controllers)
            scan_timeout: Seconds to scan before giving up
            connect_timeout: Seconds to wait for connection

        Returns:
            MAC address string on success, None on failure.
        """
        if not self._device:
            on_status("BLE not initialized")
            return None

        # Determine target MAC
        mac = target_address
        self.last_connection_mode = 'pair' if mac else None
        if not mac:
            on_status("Scanning for controller...")
            candidate = await self._scan(scan_timeout, exclude_addresses,
                                         accept_advertisement, stop_event)
            if not candidate:
                on_status("No controller found")
                return None
            mac, self.last_connection_mode = candidate

        # Prevent double-connecting
        if mac in self._connections:
            on_status("Already connected to this controller")
            return mac

        # Connect
        on_status("Connecting...")
        try:
            connection = await self._device.connect(
                Address(mac, Address.PUBLIC_DEVICE_ADDRESS),
                own_address_type=OwnAddressType.PUBLIC,
                connection_parameters_preferences={
                    HCI_LE_1M_PHY: ConnectionParametersPreferences(
                        connection_interval_min=7.5,
                        connection_interval_max=15.0,
                        max_latency=0,
                        supervision_timeout=5000,
                    ),
                    HCI_LE_2M_PHY: ConnectionParametersPreferences(
                        connection_interval_min=7.5,
                        connection_interval_max=15.0,
                        max_latency=0,
                        supervision_timeout=5000,
                    ),
                },
                timeout=connect_timeout,
            )
        except Exception as e:
            on_status(f"Connection failed: {e}")
            return None

        self._connections[mac] = connection

        # Track disconnection with an event, like the PoC
        disconnected = asyncio.Event()

        def _on_disconnection(reason):
            disconnected.set()
            self._connections.pop(mac, None)
            self._peers.pop(mac, None)
            on_status(f"BLE disconnected: {reason}")
            on_disconnect()

        connection.on("disconnection", _on_disconnection)

        # Handle security requests from controller
        async def _on_security_request(auth_req):
            try:
                await connection.pair()
            except (Exception, asyncio.CancelledError):
                pass

        if self.last_connection_mode == 'pair':
            connection.on("security_request",
                          lambda auth_req: asyncio.ensure_future(
                              _on_security_request(auth_req)))

            # SMP Legacy pairing is attempted only during explicit enrollment.
            on_status("SMP pairing...")
            try:
                await connection.pair()
            except (Exception, asyncio.CancelledError):
                # Continue without SMP — proprietary pairing may still work
                if disconnected.is_set():
                    self._connections.pop(mac, None)
                    on_status("Disconnected during pairing")
                    return None

        if disconnected.is_set():
            self._connections.pop(mac, None)
            on_status("Disconnected during pairing")
            return None

        # MTU exchange (SW2 input reports are 63 bytes)
        on_status("MTU exchange...")
        peer = Peer(connection)
        self._peers[mac] = peer
        try:
            await peer.request_mtu(512)
        except (Exception, asyncio.CancelledError):
            if disconnected.is_set():
                self._connections.pop(mac, None)
                self._peers.pop(mac, None)
                return None

        self._log_connection_params(connection, peer, on_status)

        if disconnected.is_set():
            self._connections.pop(mac, None)
            self._peers.pop(mac, None)
            return None

        # GATT discovery
        on_status("Discovering services...")
        await peer.discover_services()
        for service in peer.services:
            await service.discover_characteristics()
            for char in service.characteristics:
                await char.discover_descriptors()

        if disconnected.is_set():
            self._connections.pop(mac, None)
            return None

        # Input notification callback: translate BLE format to USB-compatible 64 bytes
        def _on_input(value: bytes):
            try:
                data_queue.put_nowait(translate_ble_to_usb(value))
            except queue.Full:
                pass

        # Run SW2 init sequence
        on_status("Initializing controller...")
        success = await sw2_init(
            peer=peer,
            connection=connection,
            device=self._device,
            slot_index=slot_index,
            on_input=_on_input,
            on_status=on_status,
            disconnected=disconnected,
            pairing=self.last_connection_mode == 'pair',
        )

        if not success or disconnected.is_set():
            self._connections.pop(mac, None)
            self._peers.pop(mac, None)
            if not disconnected.is_set():
                try:
                    await connection.disconnect()
                except Exception:
                    pass
            on_status("Controller init failed")
            return None

        return mac

    @staticmethod
    def _log_connection_params(connection, peer, on_status):
        """Log negotiated BLE connection parameters for latency diagnostics."""
        parts = []
        try:
            params = getattr(connection, 'parameters', None)
            if params:
                interval = getattr(params, 'connection_interval', None)
                if interval is not None:
                    parts.append(f"interval={interval:.1f}ms")
                latency = getattr(params, 'peripheral_latency',
                                  getattr(params, 'max_latency', None))
                if latency is not None:
                    parts.append(f"latency={latency}")
                sup_to = getattr(params, 'supervision_timeout', None)
                if sup_to is not None:
                    parts.append(f"sup_timeout={sup_to}")
        except Exception:
            pass
        try:
            phy = getattr(connection, 'phy', None)
            if phy:
                parts.append(f"PHY={phy}")
        except Exception:
            pass
        try:
            mtu = getattr(peer, 'mtu', None)
            if mtu:
                parts.append(f"MTU={mtu}")
        except Exception:
            pass
        if parts:
            msg = "BLE params: " + ", ".join(parts)
            on_status(msg)
            print(f"  [BLE] {msg}", file=__import__('sys').stderr)

    async def _scan(self, timeout: float,
                    exclude_addresses: Optional[list[str]] = None,
                    accept_advertisement: Optional[Callable[[str, object], Optional[str]]] = None,
                    stop_event: Optional[asyncio.Event] = None,
                    ) -> Optional[tuple[str, str]]:
        """Scan for NSO GC controllers, return first found MAC.

        Matches by Nintendo OUI prefix in the MAC address, mirroring
        the PoC's approach of matching by known MAC.
        """
        exclude = set(exclude_addresses or [])
        found_event = asyncio.Event()
        found_candidate = [None]

        def on_advertisement(advertisement):
            try:
                if found_event.is_set():
                    return
                # Bumble appends address type (for example "/P") to str(Address).
                # Persist and compare the six-octet MAC alone.
                addr_str = str(advertisement.address).split('/', 1)[0].upper()
                # Skip controllers that are already connected
                if addr_str in self._connections:
                    return
                # Skip controllers assigned to other slots
                if addr_str in exclude:
                    return
                if accept_advertisement is not None:
                    mode = accept_advertisement(addr_str, advertisement)
                else:
                    mode = 'pair' if any(addr_str.startswith(oui) for oui in _NINTENDO_OUIS) else None
                if mode in ('pair', 'reconnect'):
                    found_candidate[0] = (addr_str, mode)
                    found_event.set()
            except Exception:
                pass

        self._device.on("advertisement", on_advertisement)
        await self._device.start_scanning(filter_duplicates=False)

        waiters = [asyncio.create_task(found_event.wait())]
        if stop_event is not None:
            waiters.append(asyncio.create_task(stop_event.wait()))
        try:
            await asyncio.wait(waiters, timeout=timeout,
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in waiters:
                task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            await self._device.stop_scanning()

        return found_candidate[0]

    async def scan_only(self, scan_timeout: float = 10.0) -> list[dict]:
        """Run a full BLE scan and return all discovered devices.

        Returns a list of dicts with keys: address, name, rssi.
        Unlike _scan(), this captures ALL advertising devices, not just
        Nintendo OUI matches.
        """
        if not self._device:
            return []

        found: dict[str, dict] = {}

        def on_advertisement(advertisement):
            try:
                addr_str = str(advertisement.address).upper()
                # Skip devices already connected
                if addr_str in self._connections:
                    return
                rssi = getattr(advertisement, 'rssi', -999) or -999
                name = advertisement.data.get(0x09, b'').decode('utf-8', errors='replace') if hasattr(advertisement, 'data') else ''
                if not name:
                    name = getattr(advertisement, 'name', '') or ''
                # Keep the strongest signal if seen multiple times
                if addr_str not in found or rssi > found[addr_str].get('rssi', -999):
                    found[addr_str] = {
                        'address': addr_str,
                        'name': name,
                        'rssi': rssi,
                    }
            except Exception:
                pass

        self._device.on("advertisement", on_advertisement)
        await self._device.start_scanning(filter_duplicates=False)

        await asyncio.sleep(scan_timeout)

        await self._device.stop_scanning()

        return list(found.values())

    async def send_rumble(self, mac: str, packet: bytes) -> bool:
        """Send rumble packet to controller via ATT write (no response)."""
        peer = self._peers.get(mac)
        if not peer:
            return False
        try:
            from .sw2_protocol import H_OUT_CMD
            await peer.gatt_client.write_value(
                attribute=H_OUT_CMD, value=packet, with_response=False)
            return True
        except Exception:
            return False

    async def play_vibration_preset(self, mac: str, preset_id: int) -> bool:
        """Trigger a finite rumble clip on the NSO GameCube controller."""
        peer = self._peers.get(mac)
        if not peer:
            return False
        from .sw2_protocol import H_CMD_WRITE, build_vibration_preset
        try:
            await peer.gatt_client.write_value(
                attribute=H_CMD_WRITE,
                value=build_vibration_preset(preset_id),
                with_response=False,
            )
            return True
        except Exception:
            return False

    async def disconnect(self, mac_address: str):
        """Disconnect a specific controller."""
        self._peers.pop(mac_address, None)
        connection = self._connections.pop(mac_address, None)
        if connection:
            try:
                await connection.disconnect()
            except Exception:
                pass

    async def close(self):
        """Disconnect all controllers and close the HCI transport."""
        for mac in list(self._connections.keys()):
            await self.disconnect(mac)

        if self._transport:
            try:
                await self._transport.close()
            except Exception:
                pass
            self._transport = None
        self._device = None
