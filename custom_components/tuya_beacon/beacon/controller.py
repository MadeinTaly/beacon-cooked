"""Local Tuya Beacon gateway. State is the last command, never device feedback."""
import argparse
import hmac
import json
import logging
import math
import re
import secrets
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .codec import PAIR_KEY, encode, xxtea
from .discovery import scan

LOG = logging.getLogger('beacon_cooked')
TARGET = bytes.fromhex('eeeeeeeeee00')
COLORS = {'Red': 0, 'Orange': 30, 'Yellow': 60, 'Green': 120,
          'Cyan': 180, 'Blue': 240, 'Purple': 270, 'Magenta': 300}


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as file:
        json.dump(value, file)
        file.flush()
        import os
        os.fsync(file.fileno())
    temporary.replace(path)


class Radio:
    def __init__(self, adapter):
        if not re.fullmatch(r'hci\d+', adapter):
            raise ValueError('Invalid adapter')
        self.adapter = adapter
        self.extended = None

    def command(self, ocf, payload=b'', allow_disabled=False):
        opcode = 0x2000 | ocf
        with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI) as channel:
            channel.bind((int(self.adapter[3:]),))
            channel.setsockopt(0, 2, struct.pack('<IIIH2x', 0x10, (1 << 14) | (1 << 15), 0, opcode))
            channel.settimeout(5)
            channel.send(b'\x01' + opcode.to_bytes(2, 'little') + bytes([len(payload)]) + payload)
            deadline = time.monotonic() + 5
            while True:
                channel.settimeout(max(0.01, deadline - time.monotonic()))
                packet = channel.recv(512)
                if len(packet) >= 7 and packet[:2] == b'\x04\x0e' and packet[4:6] == opcode.to_bytes(2, 'little'):
                    status = packet[6]
                    reply = packet[7:]
                    break
                if len(packet) >= 7 and packet[:2] == b'\x04\x0f' and packet[5:7] == opcode.to_bytes(2, 'little') and packet[3]:
                    status, reply = packet[3], b''
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('Bluetooth command timed out')
        if status and not (allow_disabled and status == 0x0c):
            raise RuntimeError(f'Bluetooth command {ocf:#x}: status {status:#x}')
        return reply

    def probe(self):
        self.command(0x03)

    def detect_mode(self):
        if self.extended is None:
            self.probe()
            try:
                supported = self.command(0x3b)
                self.extended = bool(supported and supported[0])
            except RuntimeError:
                self.extended = False

    def stop(self):
        self.detect_mode()
        if self.extended:
            self.command(0x39, b'\0\0', allow_disabled=True)
        else:
            self.command(0x0a, b'\0', allow_disabled=True)

    def prepare(self, sender):
        self.stop()
        if self.extended:
            self.command(0x36, bytes.fromhex('011300200000200000070100000000000000007f0100010000'))
            self.command(0x35, b'\x01' + sender[::-1])
            return
        self.command(0x05, sender[::-1])
        self.command(0x06, bytes.fromhex('200020000001000000000000000700'))
        self.command(0x09, b'\0' * 32)  # Empty scan response.

    def send(self, raw):
        if len(raw) != 31:
            raise ValueError('Invalid advertising frame')
        if self.extended:
            self.command(0x37, bytes([1, 3, 1, 31]) + raw)
            self.command(0x39, bytes.fromhex('010101000000'))
        else:
            self.command(0x08, bytes([31]) + raw)
            self.command(0x0a, b'\x01')
        try:
            time.sleep(0.7)
        finally:
            self.stop()


class Gateway:
    def __init__(self, config, state_path, radio=None, config_path=None):
        self.config = config
        self.config_path = Path(config_path) if config_path else None
        self.discovered = []
        self.discovered_at = 0
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.saved = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.radio = radio or Radio(config.get('adapter', 'hci0'))
        self.lock = threading.Lock()
        senders = set()
        identities = set()
        for lamp in config['lights']:
            sender = bytes.fromhex(lamp['sender'].replace(':', ''))
            salt = bytes.fromhex(lamp['salt'])
            if len(sender) != 6 or sender[0] & 0xc0 != 0xc0 or len(salt) != 2:
                raise ValueError('Sender must be a static random MAC; salt must be 2 bytes')
            if sender in senders or lamp['id'] in identities:
                raise ValueError('Each virtual remote must have a unique sender and ID')
            senders.add(sender)
            identities.add(lamp['id'])

    def info(self):
        with self.lock:
            return {'api_version': 1, 'gateway_id': self.config['gateway_id'],
                    'state_source': 'last_command', 'colors': COLORS,
                    'name': 'Beacon Cooked', 'discovered': self.discovered,
                    'lights': [dict(id=x['id'], name=x['name'],
                                    mac=x.get('mac'), association=x.get('association', 'previously_configured'),
                                    model=x.get('model', 'Beacon virtual remote group'),
                                    profile=x.get('profile', 'unverified_beacon'),
                                    protocol='tuya_beacon_xxtea_v1',
                                    capabilities_verified=x.get('capabilities_verified', []),
                                    state=self.saved.get(x['id'], {}).get('state', {}))
                               for x in self.config['lights']]}

    def save_config(self):
        if self.config_path:
            atomic_json(self.config_path, self.config)

    def discover(self, seconds=8):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 15:
            raise ValueError('Scan duration must be 1–15 seconds')
        with self.lock:
            self.discovered = scan(self.radio, seconds)
            self.discovered_at = time.monotonic()
            return {'devices': self.discovered}

    def enroll(self, body):
        mac, name = body.get('mac', ''), body.get('name', '')
        if not isinstance(mac, str) or not isinstance(name, str):
            raise ValueError('Device MAC and name must be strings')
        mac, name = mac.upper(), name.strip()
        if not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', mac) or not 1 <= len(name) <= 80:
            raise ValueError('Select a discovered device and enter its name')
        with self.lock:
            if time.monotonic() - self.discovered_at > 300 or not any(x['mac'] == mac for x in self.discovered):
                raise ValueError('Device scan expired; scan again')
            lamp = next((x for x in self.config['lights'] if x.get('mac') == mac), None)
            if lamp is None:
                while True:
                    sender = bytes([0xc2]) + secrets.token_bytes(5)
                    if all(sender.hex(':') != x['sender'].lower() for x in self.config['lights']):
                        break
                lamp = {'id': mac.replace(':', '').lower(), 'mac': mac, 'name': name,
                        'sender': sender.hex(':'), 'salt': secrets.token_hex(2),
                        'profile': 'unverified_beacon', 'capabilities_verified': [],
                        'association': 'unverified'}
                self.config['lights'].append(lamp)
            else:
                lamp['name'] = name
            self.save_config()
            return {'id': lamp['id'], 'name': lamp['name'], 'association': lamp.get('association', 'unverified')}

    def confirm(self, light_id, body):
        if type(body.get('confirmed')) is not bool:
            raise ValueError('confirmed must be boolean')
        if 'effect' in body and body['effect'] not in COLORS:
            raise ValueError('Unknown color')
        with self.lock:
            lamp = next((x for x in self.config['lights'] if x['id'] == light_id), None)
            if lamp is None:
                raise KeyError('Unknown light')
            lamp['association'] = 'user_confirmed' if body['confirmed'] else 'unverified'
            if body['confirmed'] and body.get('effect'):
                capability = 'color:' + body['effect'].lower()
                if capability not in lamp.setdefault('capabilities_verified', []):
                    lamp['capabilities_verified'].append(capability)
                if lamp.get('profile', 'unverified_beacon') == 'unverified_beacon':
                    lamp['profile'] = 'beacon_control_verified'
            self.save_config()
            if getattr(self, 'mqtt', None) and body['confirmed']:
                self.mqtt.register_light(lamp)
            return {'association': lamp['association']}

    def execute(self, light_id, body, pair=False):
        lamp = next((x for x in self.config['lights'] if x['id'] == light_id), None)
        if lamp is None:
            raise KeyError('Unknown light')
        if pair:
            seconds = body.get('seconds', 15)
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 1 <= seconds <= 30:
                raise ValueError('Pairing duration must be 1–30 seconds')
        else:
            if not body or set(body) - {'on', 'effect'}:
                raise ValueError('Expected on and/or effect')
            if 'on' in body and type(body['on']) is not bool:
                raise ValueError('on must be boolean')
            if 'effect' in body and body['effect'] not in COLORS:
                raise ValueError('Unknown color')
        with self.lock:
            saved = self.saved.setdefault(light_id, {})
            sequence = max(saved.get('counter', 20000), 20000)
            count = math.ceil(seconds / 0.7) if pair else 3
            if sequence + count >= 1 << 24:
                raise RuntimeError('Sequence counter exhausted')
            saved['counter'] = sequence + count
            atomic_json(self.state_path, self.saved)  # Reserve before transmitting.
            sender = bytes.fromhex(lamp['sender'].replace(':', ''))
            salt = bytes.fromhex(lamp['salt'])
            key = xxtea(salt + sender[2:6] + b'TuyaIoT-OS', PAIR_KEY)
            packets = []
            if pair:
                for offset in range(count):
                    packets.append(encode(TARGET, 8, sequence + offset,
                                          b'\x03\x00\x01' + salt + b'\0' * 4, PAIR_KEY))
            else:
                if 'on' in body:
                    packets.append(encode(TARGET, 7, sequence, b'\x01\x01\x01' + bytes([body['on']]), key))
                if 'effect' in body:
                    packets.append(encode(TARGET, 7, sequence + 1, bytes.fromhex('02040101'), key))
                    params = bytes.fromhex('0b0004') + COLORS[body['effect']].to_bytes(2, 'big') + b'\x64\x64'
                    packets.append(encode(TARGET, 7, sequence + 2, params, key))
            try:
                self.radio.prepare(sender)
                for packet in packets:
                    self.radio.send(packet)
            finally:
                self.radio.stop()
            if not pair:
                saved.setdefault('state', {}).update(body)
                atomic_json(self.state_path, self.saved)
                if getattr(self, 'mqtt', None):
                    self.mqtt.publish_state(lamp)
            LOG.info('Transmitted %s for %s (%d frames)', 'pair' if pair else 'command', light_id, len(packets))
            return {'transmitted': True, 'device_acknowledged': False,
                    'state': saved.get('state', {})}
