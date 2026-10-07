import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from codec import decode, xxtea, PAIR_KEY
from server import Gateway


class FakeRadio:
    def __init__(self, fail=False):
        self.frames = []
        self.fail = fail
        self.stopped = False
    def prepare(self, sender):
        pass
    def send(self, frame):
        self.frames.append(frame)
        if self.fail:
            raise RuntimeError('radio unavailable')
    def stop(self):
        self.stopped = True


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state.json'
        self.config = {'gateway_id': 'test', 'lights': [{'id': 'lamp', 'name': 'Lamp',
                       'sender': 'c2:00:00:00:00:01', 'salt': '6172'}]}
        self.key = xxtea(bytes.fromhex('617200000001') + b'TuyaIoT-OS', PAIR_KEY)

    def test_purple_and_counter_survive_restart(self):
        radio = FakeRadio()
        gateway = Gateway(self.config, self.path, radio)
        result = gateway.execute('lamp', {'on': True, 'effect': 'Purple'})
        frames = [decode(frame, self.key) for frame in radio.frames]
        self.assertEqual(frames[2]['params'][:14], '0b0004010e6464')
        self.assertEqual([x['sequence'] for x in frames], [20000, 20001, 20002])
        self.assertFalse(result['device_acknowledged'])
        second = FakeRadio()
        Gateway(self.config, self.path, second).execute('lamp', {'on': False})
        self.assertEqual(decode(second.frames[0], self.key)['sequence'], 20003)
        self.assertTrue(radio.stopped)

    def test_failure_reserves_counter_without_changing_state(self):
        radio = FakeRadio(fail=True)
        gateway = Gateway(self.config, self.path, radio)
        with self.assertRaises(RuntimeError):
            gateway.execute('lamp', {'on': True})
        saved = json.loads(self.path.read_text())['lamp']
        self.assertEqual(saved['counter'], 20003)
        self.assertNotIn('state', saved)
        self.assertTrue(radio.stopped)

    def test_invalid_requests_never_transmit(self):
        radio = FakeRadio()
        gateway = Gateway(self.config, self.path, radio)
        for body in ({'on': 'yes'}, {'effect': 'Unknown'}, {}, {'brightness': 50}):
            with self.assertRaises(ValueError):
                gateway.execute('lamp', body)
        with self.assertRaises(ValueError):
            gateway.execute('lamp', {'seconds': float('nan')}, pair=True)
        self.assertEqual(radio.frames, [])
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
