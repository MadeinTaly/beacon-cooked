import json
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from mqtt_bridge import MQTTBridge


class MQTTTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MQTTBridge.__new__(MQTTBridge)
        self.bridge.commands = queue.Queue(maxsize=2)

    def message(self, body):
        return SimpleNamespace(topic='beacon_cooked/lamp/set', payload=json.dumps(body).encode())

    def test_standard_light_command(self):
        self.bridge.on_message(None, None, self.message({'state': 'ON', 'effect': 'Purple'}))
        self.assertEqual(self.bridge.commands.get_nowait(), ('lamp', {'on': True, 'effect': 'Purple'}))

    def test_invalid_commands_not_queued(self):
        for body in ({'state': 'invalid'}, {'brightness': 100}, ['ON']):
            self.bridge.on_message(None, None, self.message(body))
        self.assertTrue(self.bridge.commands.empty())

    def test_new_confirmed_light_is_discoverable_without_restart(self):
        published = []
        self.bridge.prefix = 'beacon_cooked'
        self.bridge.config = {'discovery': True}
        self.bridge.gateway = SimpleNamespace(config={'gateway_id': 'host'}, saved={})
        self.bridge.client = SimpleNamespace(publish=lambda *args, **kwargs: published.append(args))
        lamp = {'id': 'lamp', 'name': 'New light', 'association': 'unverified'}
        self.bridge.register_light(lamp)
        self.assertEqual(published, [])
        lamp['association'] = 'user_confirmed'
        self.bridge.register_light(lamp)
        self.assertEqual(published[-1][0], 'homeassistant/light/beacon_cooked/host_lamp/config')
        discovery = json.loads(published[-1][1])
        self.assertEqual(discovery['command_topic'], 'beacon_cooked/lamp/set')
        self.assertIn('Blue', discovery['effect_list'])
