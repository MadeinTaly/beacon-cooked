import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from discovery import candidate, reports


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.mac = bytes.fromhex('dc2350000001')
        self.raw = b'\x1e\xff\x07\xd0\x01' + self.mac + b'\0' * 20

    def test_pairing_report(self):
        record = b'\x03\x01' + self.mac[::-1] + bytes([len(self.raw)]) + self.raw + b'\xb0'
        packet = b'\x04\x3e' + bytes([len(record) + 2]) + b'\x02\x01' + record
        found = reports(packet)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['mac'], 'DC:23:50:00:00:01')
        self.assertEqual(found[0]['rssi'], -80)
        self.assertTrue(found[0]['pairing'])

    def test_reject_mismatch_or_truncation(self):
        self.assertIsNone(candidate(b'\0' * 6, self.raw, -80))
        self.assertIsNone(candidate(self.mac, self.raw[:-1], -80))
        self.assertEqual(reports(b'\x04\x3e\x10\x02\x01'), [])


if __name__ == '__main__':
    unittest.main()
