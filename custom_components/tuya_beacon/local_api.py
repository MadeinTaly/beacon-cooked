"""Direct local USB Bluetooth control without an external gateway process."""
import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from aiohttp import ClientError
from .beacon.controller import Gateway, atomic_json
from .beacon.discovery import candidate


class LocalAPI:
    def __init__(self, hass, gateway):
        self.hass, self.gateway = hass, gateway

    async def _run(self, method, *args):
        try:
            return await self.hass.async_add_executor_job(method, *args)
        except (OSError, RuntimeError, ValueError) as error:
            raise ClientError('Local Bluetooth operation failed') from error

    async def info(self):
        await self._run(self.gateway.radio.probe)
        return await self._run(self.gateway.info)

    async def discover(self):
        from homeassistant.components import bluetooth
        from homeassistant.core import callback
        if 'bluetooth' not in self.hass.config.components or not bluetooth.async_scanner_count(self.hass, connectable=False):
            return await self._run(self.gateway.discover, 8)
        found = {}

        @callback
        def discovered(info, change):
            data = info.manufacturer_data.get(0xd007)
            if data is None or len(data) != 27:
                return
            try:
                address = bytes.fromhex(info.address.replace(':', ''))
            except ValueError:
                return
            item = candidate(address, bytes([30, 0xff, 7, 0xd0]) + data, info.rssi)
            if item:
                found[item['mac']] = item

        cancel = bluetooth.async_register_callback(self.hass, discovered,
                   {'manufacturer_id': 0xd007, 'connectable': False}, bluetooth.BluetoothScanningMode.ACTIVE)
        try:
            await asyncio.sleep(8)
        finally:
            cancel()
        def store():
            with self.gateway.lock:
                self.gateway.discovered = sorted(found.values(), key=lambda x: x['rssi'], reverse=True)
                self.gateway.discovered_at = time.monotonic()
                return {'devices': self.gateway.discovered}
        return await self._run(store)

    async def command(self, light_id, body, pair=False):
        return await self._run(self.gateway.execute, light_id, body, pair)

    async def enroll(self, mac, name):
        return await self._run(self.gateway.enroll, {'mac': mac, 'name': name})

    async def confirm(self, light_id, confirmed, effect=None):
        body = {'confirmed': confirmed}
        if effect is not None:
            body['effect'] = effect
        return await self._run(self.gateway.confirm, light_id, body)


def _create_local(hass, adapter):
    if not re.fullmatch(r'hci\d+', adapter):
        raise ValueError('Invalid adapter')
    root = Path(hass.config.path('.storage', 'beacon_cooked'))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    config_path = root / f'{adapter}-config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {
        'gateway_id': 'local-' + uuid.uuid4().hex, 'adapter': adapter, 'lights': []}
    gateway = Gateway(config, root / f'{adapter}-state.json', config_path=config_path)
    gateway.radio.probe()
    atomic_json(config_path, config)
    return LocalAPI(hass, gateway)


async def get_local_api(hass, adapter):
    state = hass.data.setdefault('beacon_cooked_local', {'lock': asyncio.Lock(), 'apis': {}})
    async with state['lock']:
        if adapter not in state['apis']:
            try:
                state['apis'][adapter] = await hass.async_add_executor_job(_create_local, hass, adapter)
            except (OSError, RuntimeError, AttributeError) as error:
                raise ClientError('Local USB Bluetooth is not accessible') from error
        return state['apis'][adapter]
