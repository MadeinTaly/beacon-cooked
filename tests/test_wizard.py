"""Wizard behavior tests; run in a Home Assistant Python environment."""
import importlib.util
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HAS_HA = importlib.util.find_spec('homeassistant') is not None
if HAS_HA:
    from aiohttp import ClientError
    from custom_components.tuya_beacon.config_flow import DeviceWizard
else:
    DeviceWizard = object


class FakeAPI:
    def __init__(self):
        self.calls = []
    async def command(self, light_id, body, pair=False):
        self.calls.append(('command', light_id, body, pair))
    async def confirm(self, light_id, confirmed, effect=None):
        self.calls.append(('confirm', light_id, confirmed, effect))
    async def discover(self):
        return {'devices': []}


class FakeWizard(DeviceWizard):
    def __init__(self):
        self._api = FakeAPI()
        self._lamp = {'id': 'lamp', 'name': 'Test light'}
        self._test_effect = 'Blue'
    def async_show_form(self, **kwargs):
        return {'type': 'form', **kwargs}
    def async_show_menu(self, **kwargs):
        return {'type': 'menu', **kwargs}


@unittest.skipUnless(HAS_HA, 'Requires Home Assistant; exercised in HA container')
class WizardTests(unittest.IsolatedAsyncioTestCase):
    async def test_binding_requires_isolation_confirmation(self):
        flow = FakeWizard()
        result = await flow.async_step_bind({'only_target': False})
        self.assertEqual(result['errors']['base'], 'isolate_target')
        self.assertEqual(flow._api.calls, [])

    async def test_transmission_requires_separate_physical_confirmation(self):
        flow = FakeWizard()
        result = await flow.async_step_test({'effect': 'Purple'})
        self.assertEqual(result['step_id'], 'verify')
        self.assertEqual(flow._api.calls, [('command', 'lamp', {'on': True, 'effect': 'Purple'}, False)])
        result = await flow.async_step_verify({'result': 'confirmed'})
        self.assertEqual(result['step_id'], 'added')
        self.assertEqual(flow._api.calls[-1], ('confirm', 'lamp', True, 'Purple'))

    async def test_retry_never_marks_device_associated(self):
        flow = FakeWizard()
        result = await flow.async_step_verify({'result': 'retry'})
        self.assertEqual(result['step_id'], 'bind')
        self.assertEqual(flow._api.calls, [])

    async def test_empty_scan_does_not_create_device(self):
        flow = FakeWizard()
        result = await flow.async_step_scan({})
        self.assertEqual(result['errors']['base'], 'no_devices')
        self.assertEqual(flow._api.calls, [])
