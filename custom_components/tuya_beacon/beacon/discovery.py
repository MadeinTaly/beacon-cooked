"""Decode the observed Tuya Beacon advertisements, not generic Tuya BLE."""
import socket
import struct
import time
from datetime import datetime, timezone
from .codec import ad_fields


def candidate(address, raw, rssi):
    try:
        manufacturer = ad_fields(raw).get(0xff, b'')
    except ValueError:
        return None
    if len(manufacturer) != 29 or manufacturer[:2] != b'\x07\xd0':
        return None
    payload = manufacturer[2:]
    if payload[0] not in (1, 4) or payload[1:7] != address:
        return None
    mac = address.hex(':').upper()
    return {'mac': mac, 'name': 'Tuya Beacon ' + address[-3:].hex().upper(),
            'protocol': 'tuya_beacon_xxtea_v1', 'profile': 'unverified_beacon',
            'identity_source': 'embedded_static_mac', 'manufacturer_id': '0xd007',
            'capabilities_verified': [],
            'pairing': payload[0] == 1, 'rssi': rssi,
            'last_seen': datetime.now(timezone.utc).isoformat()}


def reports(packet):
    """Parse bounded legacy LE Advertising Reports from a raw HCI socket."""
    if len(packet) < 5 or packet[:2] != b'\x04\x3e' or packet[3] not in (2, 13):
        return []
    count, offset, found = packet[4], 5, []
    for _ in range(count):
        if packet[3] == 13:
            if offset + 24 > len(packet):
                break
            address = packet[offset + 3:offset + 9][::-1]
            length = packet[offset + 23]
            end = offset + 24 + length
            if end > len(packet):
                break
            item = candidate(address, packet[offset + 24:end], struct.unpack('b', packet[offset + 13:offset + 14])[0])
            if item:
                found.append(item)
            offset = end
            continue
        if offset + 10 > len(packet):
            break
        address = packet[offset + 2:offset + 8][::-1]
        length = packet[offset + 8]
        end = offset + 9 + length
        if end >= len(packet):
            break
        rssi = struct.unpack('b', packet[end:end + 1])[0]
        item = candidate(address, packet[offset + 9:end], rssi)
        if item:
            found.append(item)
        offset = end + 1
    return found


def scan(radio, seconds):
    receiver = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
    try:
        receiver.bind((int(radio.adapter[3:]),))
        # HCI event packets, LE Meta Event only. SOL_HCI=0, HCI_FILTER=2.
        receiver.setsockopt(0, 2, struct.pack('<IIIH2x', 0x10, 0, 1 << 30, 0))
        radio.stop()
        if radio.extended:
            radio.command(0x42, bytes.fromhex('000000000000'), allow_disabled=True)
            radio.command(0x41, bytes.fromhex('0000010110001000'))
            radio.command(0x42, bytes.fromhex('010000000000'))
        else:
            radio.command(0x0c, b'\0\0', allow_disabled=True)
            radio.command(0x0b, bytes.fromhex('01100010000000'))
            radio.command(0x0c, b'\x01\0')
        deadline = time.monotonic() + seconds
        found = {}
        while time.monotonic() < deadline:
            receiver.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                for item in reports(receiver.recv(4096)):
                    found[item['mac']] = item
            except TimeoutError:
                break
        return sorted(found.values(), key=lambda x: x['rssi'], reverse=True)
    finally:
        try:
            if radio.extended:
                radio.command(0x42, bytes.fromhex('000000000000'), allow_disabled=True)
            else:
                radio.command(0x0c, b'\0\0', allow_disabled=True)
        finally:
            receiver.close()
