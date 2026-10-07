"""Optional MQTT transport using the same serialized radio command path."""
import json
import logging
import queue
import threading

LOG = logging.getLogger('beacon_cooked.mqtt')


class MQTTBridge:
    def __init__(self, gateway, config):
        import paho.mqtt.client as mqtt
        self.gateway = gateway
        self.config = config
        self.prefix = config.get('prefix', 'beacon_cooked').rstrip('/')
        self.commands = queue.Queue(maxsize=32)
        self.client = mqtt.Client(client_id='beacon-cooked-' + gateway.config['gateway_id'])
        if config.get('username'):
            self.client.username_pw_set(config['username'], config.get('password'))
        if config.get('tls'):
            self.client.tls_set()
        self.client.will_set(self.prefix + '/availability', 'offline', retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        self.client.connect_async(self.config['host'], self.config.get('port', 1883), 60)
        self.client.loop_start()
        threading.Thread(target=self.worker, daemon=True, name='beacon-mqtt').start()

    def publish_state(self, lamp):
        state = self.gateway.saved.get(lamp['id'], {}).get('state', {})
        data = {'state_source': 'last_command', 'device_acknowledged': False}
        if 'on' in state:
            data['state'] = 'ON' if state['on'] else 'OFF'
        if 'effect' in state:
            data['effect'] = state['effect']
        self.client.publish(f"{self.prefix}/{lamp['id']}/state", json.dumps(data), retain=True)

    def on_connect(self, client, userdata, flags, rc, properties=None):
        if rc != 0:
            LOG.error('MQTT connection refused: %s', rc)
            return
        client.subscribe(self.prefix + '/+/set')
        client.publish(self.prefix + '/availability', 'online', retain=True)
        for lamp in self.gateway.config['lights']:
            self.register_light(lamp)

    def register_light(self, lamp):
        if lamp.get('association') == 'unverified':
            return
        self.publish_state(lamp)
        if self.config.get('discovery', False):
            from server import COLORS
            unique = self.gateway.config['gateway_id'] + '_' + lamp['id']
            data = {'name': lamp['name'], 'unique_id': 'beacon_cooked_' + unique,
                    'schema': 'json', 'command_topic': f"{self.prefix}/{lamp['id']}/set",
                    'state_topic': f"{self.prefix}/{lamp['id']}/state",
                    'availability_topic': self.prefix + '/availability',
                    'effect': True, 'effect_list': list(COLORS),
                    'supported_color_modes': ['onoff'],
                    'device': {'identifiers': ['beacon_cooked_' + unique],
                               'name': lamp['name'], 'model': 'Tuya Beacon virtual remote group',
                               'manufacturer': 'Tuya compatible'}}
            self.client.publish(f"homeassistant/light/beacon_cooked/{unique}/config", json.dumps(data), retain=True)

    def on_message(self, client, userdata, message):
        if len(message.payload) > 1024:
            return
        try:
            body = json.loads(message.payload)
            if not isinstance(body, dict) or set(body) - {'state', 'effect'}:
                raise ValueError('Expected state and/or effect')
            command = {}
            if 'state' in body:
                if body['state'] not in ('ON', 'OFF'):
                    raise ValueError('state must be ON or OFF')
                command['on'] = body['state'] == 'ON'
            if 'effect' in body:
                command['effect'] = body['effect']
            self.commands.put_nowait((message.topic.split('/')[-2], command))
        except (ValueError, UnicodeError, queue.Full):
            LOG.warning('Invalid MQTT command or command queue full')

    def worker(self):
        while True:
            lamp_id, command = self.commands.get()
            try:
                self.gateway.execute(lamp_id, command)
            except Exception:
                LOG.exception('MQTT transmission failed for %s', lamp_id)
            finally:
                self.commands.task_done()
