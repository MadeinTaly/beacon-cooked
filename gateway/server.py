"""Optional HTTP/MQTT service for a remote Linux Bluetooth host."""
import argparse
import hmac
import json
import logging
import re
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
# Source checkout: share exactly the library shipped by HACS.
source = Path(__file__).resolve().parents[1] / 'custom_components' / 'tuya_beacon'
if source.is_dir():
    sys.path.insert(0, str(source))
from beacon.controller import Gateway, Radio, COLORS
LOG = logging.getLogger('beacon_cooked')


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
        match = re.fullmatch(r'/v1/lights/([a-zA-Z0-9_-]+)/(command|pair|confirm)', self.path)
        if not match and self.path not in ('/v1/discover', '/v1/enroll'):
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
            gateway = self.server.gateway
            if self.path == '/v1/discover':
                result = gateway.discover(body.get('seconds', 8))
            elif self.path == '/v1/enroll':
                result = gateway.enroll(body)
            elif match[2] == 'confirm':
                result = gateway.confirm(match[1], body)
            else:
                result = gateway.execute(match[1], body, match[2] == 'pair')
            self.respond(200, result)
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
    parser.add_argument('--stop-radio', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = json.loads(Path(args.config).read_text())
    if args.stop_radio:
        radio = Radio(config.get('adapter', 'hci0'))
        radio.stop()
        if radio.extended:
            radio.command(0x42, bytes.fromhex('000000000000'), allow_disabled=True)
        else:
            radio.command(0x0c, b'\0\0', allow_disabled=True)
        return
    gateway = Gateway(config, args.state, config_path=args.config)
    if config.get('mqtt', {}).get('enabled'):
        from mqtt_bridge import MQTTBridge
        gateway.mqtt = MQTTBridge(gateway, config['mqtt'])
        gateway.mqtt.start()
    server = ThreadingHTTPServer((config.get('bind', '127.0.0.1'), config.get('port', 8787)), Handler)
    server.gateway = gateway
    server.serve_forever()


if __name__ == '__main__':
    main()
