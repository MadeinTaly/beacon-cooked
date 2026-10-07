"""Local Tuya Beacon gateway. State is the last command, never device feedback."""
import argparse
import hmac
import json
import logging
import math
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from codec import PAIR_KEY, encode, xxtea

LOG = logging.getLogger('tuya_beacon')
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

    def command(self, ocf, payload=b'', allow_disabled=False):
        result = subprocess.run(
            ['/usr/bin/hcitool', '-i', self.adapter, 'cmd', '0x08', hex(ocf)]
            + [hex(byte) for byte in payload], capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError('Bluetooth command failed: ' + result.stderr.strip())
        try:
            tail = result.stdout.split('> HCI Event:')[-1].splitlines()[1:]
            reply = bytes.fromhex(' '.join(tail))
            if len(reply) < 4 or reply[1:3] != (0x2000 | ocf).to_bytes(2, 'little'):
                raise ValueError('Unexpected opcode')
            status = reply[3]
        except ValueError as error:
            raise RuntimeError('Invalid HCI response') from error
        if status and not (allow_disabled and status == 0x0c):
            raise RuntimeError(f'Bluetooth command {ocf:#x}: status {status:#x}')

    def stop(self):
        self.command(0x0a, b'\0', allow_disabled=True)

    def prepare(self, sender):
        self.stop()
        self.command(0x05, sender[::-1])
        self.command(0x06, bytes.fromhex('200020000001000000000000000700'))
        self.command(0x09, b'\0' * 32)  # Empty scan response.

    def send(self, raw):
        if len(raw) != 31:
            raise ValueError('Invalid advertising frame')
        self.command(0x08, bytes([31]) + raw)
        self.command(0x0a, b'\x01')
        try:
            time.sleep(0.7)
        finally:
            self.stop()


class Gateway:
    def __init__(self, config, state_path, radio=None):
        self.config = config
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.saved = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.radio = radio or Radio(config.get('adapter', 'hci0'))
        self.lock = threading.Lock()
        for lamp in config['lights']:
            sender = bytes.fromhex(lamp['sender'].replace(':', ''))
            salt = bytes.fromhex(lamp['salt'])
            if len(sender) != 6 or sender[0] & 0xc0 != 0xc0 or len(salt) != 2:
                raise ValueError('Sender must be a static random MAC; salt must be 2 bytes')

    def info(self):
        with self.lock:
            return {'api_version': 1, 'gateway_id': self.config['gateway_id'],
                    'state_source': 'last_command', 'colors': COLORS,
                    'lights': [dict(id=x['id'], name=x['name'],
                                    state=self.saved.get(x['id'], {}).get('state', {}))
                               for x in self.config['lights']]}

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
            LOG.info('Transmitted %s for %s (%d frames)', 'pair' if pair else 'command', light_id, len(packets))
            return {'transmitted': True, 'device_acknowledged': False,
                    'state': saved.get('state', {})}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        LOG.info(fmt, *args)

    def respond(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        expected = 'Bearer ' + self.server.gateway.config['token']
        if not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.respond(401, {'error': 'Unauthorized'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path != '/v1/info':
            self.respond(404, {'error': 'Not found'})
            return
        self.respond(200, self.server.gateway.info())

    def do_POST(self):
        if not self.authorized():
            return
        match = re.fullmatch(r'/v1/lights/([a-zA-Z0-9_-]+)/(command|pair)', self.path)
        if not match:
            self.respond(404, {'error': 'Not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1024:
                raise ValueError('Invalid body size')
            self.connection.settimeout(5)
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected JSON object')
            self.respond(200, self.server.gateway.execute(match[1], body, match[2] == 'pair'))
        except KeyError:
            self.respond(404, {'error': 'Unknown light'})
        except (ValueError, TypeError) as error:
            self.respond(400, {'error': str(error)})
        except Exception:
            LOG.exception('Gateway command failed')
            self.respond(503, {'error': 'Bluetooth transmission failed'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/tuya-beacon/config.json')
    parser.add_argument('--state', default='/var/lib/tuya-beacon/state.json')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = json.loads(Path(args.config).read_text())
    gateway = Gateway(config, args.state)
    server = ThreadingHTTPServer((config.get('bind', '127.0.0.1'), config.get('port', 8787)), Handler)
    server.gateway = gateway
    server.serve_forever()


if __name__ == '__main__':
    main()
