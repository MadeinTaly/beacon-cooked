"""Discover, bind and physically verify Beacon lights from Home Assistant."""
from urllib.parse import urlsplit
from pathlib import Path
import voluptuous as vol
from aiohttp import ClientError, ClientResponseError
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api import get_api
from .beacon.controller import COLORS
from .const import DOMAIN, CONF_GATEWAY_URL, CONF_TOKEN


def choices(key, values):
    return selector.SelectSelector(selector.SelectSelectorConfig(options=values, translation_key=key))


class DeviceWizard:
    """Shared setup and options wizard; never equate transmission with binding."""

    async def async_step_menu(self, user_input=None):
        return self.async_show_menu(step_id='menu', menu_options=['scan', 'known_devices', 'finish'])

    async def async_step_scan(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._devices = (await self._api.discover())['devices']
                if self._devices:
                    return await self.async_step_select_device()
                errors['base'] = 'no_devices'
            except (ClientError, TimeoutError, ValueError, KeyError):
                errors['base'] = 'cannot_scan'
        return self.async_show_form(step_id='scan', errors=errors, data_schema=vol.Schema({}))

    async def async_step_select_device(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._lamp = await self._api.enroll(user_input['device'], user_input['name'])
                return await self.async_step_bind()
            except (ClientError, TimeoutError, ValueError):
                errors['base'] = 'cannot_enroll'
        choices = {x['mac']: f"{x['mac']} ({x['rssi']} dBm)" for x in self._devices}
        return self.async_show_form(step_id='select_device', errors=errors, data_schema=vol.Schema({
            vol.Required('device'): vol.In(choices),
            vol.Required('name', default='Beacon light'): str,
        }))

    async def async_step_known_devices(self, user_input=None):
        errors = {}
        try:
            info = await self._api.info()
            lights = info['lights']
            if not lights:
                return await self.async_step_scan()
            if user_input is not None:
                self._lamp = next(x for x in lights if x['id'] == user_input['device'])
                if user_input['action'] == 'bind':
                    return await self.async_step_bind()
                return await self.async_step_test()
        except (ClientError, TimeoutError, ValueError, KeyError, StopIteration):
            return self.async_abort(reason='cannot_connect')
        return self.async_show_form(step_id='known_devices', errors=errors, data_schema=vol.Schema({
            vol.Required('device'): vol.In({x['id']: x['name'] for x in lights}),
            vol.Required('action', default='test'): choices('action', ['test', 'bind']),
        }))

    async def async_step_bind(self, user_input=None):
        errors = {}
        if user_input is not None:
            if not user_input['only_target']:
                errors['base'] = 'isolate_target'
                return self.async_show_form(step_id='bind', errors=errors,
                    data_schema=vol.Schema({vol.Required('only_target', default=False): bool}),
                    description_placeholders={'name': self._lamp['name']})
            try:
                await self._api.command(self._lamp['id'], {'seconds': 15}, pair=True)
                return await self.async_step_test()
            except (ClientError, TimeoutError):
                errors['base'] = 'cannot_bind'
        return self.async_show_form(step_id='bind', errors=errors,
                                    data_schema=vol.Schema({vol.Required('only_target', default=False): bool}),
                                    description_placeholders={'name': self._lamp['name']})

    async def async_step_test(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                self._test_effect = user_input['effect']
                await self._api.command(self._lamp['id'], {'on': True, 'effect': self._test_effect})
                return await self.async_step_verify()
            except (ClientError, TimeoutError):
                errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='test', errors=errors,
                                    description_placeholders={'name': self._lamp['name']},
                                    data_schema=vol.Schema({vol.Required('effect', default='Blue'): vol.In(list(COLORS))}))

    async def async_step_verify(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input['result'] == 'retry':
                return await self.async_step_bind()
            if user_input['result'] == 'another_color':
                return await self.async_step_test()
            if user_input['result'] == 'cancel':
                return await self.async_step_menu()
            try:
                await self._api.confirm(self._lamp['id'], True, self._test_effect)
                return await self.async_step_added()
            except (ClientError, TimeoutError):
                errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='verify', errors=errors,
                                    description_placeholders={'name': self._lamp['name'], 'color': self._test_effect},
                                    data_schema=vol.Schema({vol.Required('result'): choices('result', ['confirmed', 'retry', 'another_color', 'cancel'])}))

    async def async_step_added(self, user_input=None):
        if user_input is not None:
            if user_input['next'] == 'another':
                return await self.async_step_scan()
            return await self.async_step_finish()
        return self.async_show_form(step_id='added',
                                    description_placeholders={'name': self._lamp['name']},
                                    data_schema=vol.Schema({vol.Required('next', default='finish'): choices('next', ['finish', 'another'])}))


class BeaconConfigFlow(DeviceWizard, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return BeaconOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return await (self.async_step_local() if user_input['connection_type'] == 'local' else self.async_step_remote())
        return self.async_show_form(step_id='user', data_schema=vol.Schema({
            vol.Required('connection_type', default='local'): choices('connection_type', ['local', 'remote']),
        }))

    async def async_step_local(self, user_input=None):
        errors = {}
        adapters = await self.hass.async_add_executor_job(lambda: sorted(p.name for p in Path('/sys/class/bluetooth').glob('hci*')))
        if user_input is not None:
            try:
                self._settings = {'connection_type': 'local', 'adapter': user_input['adapter']}
                self._api = await get_api(self.hass, self._settings)
                info = await self._api.info()
                await self.async_set_unique_id(info['gateway_id'])
                self._abort_if_unique_id_configured()
                return await self.async_step_menu()
            except (ClientError, TimeoutError, ValueError):
                errors['base'] = 'local_unavailable'
        elif not adapters:
            errors['base'] = 'no_local_adapter'
        return self.async_show_form(step_id='local', errors=errors,
                                    data_schema=vol.Schema({vol.Required('adapter', default=adapters[0] if adapters else 'hci0'): vol.In(adapters) if adapters else str}))

    async def async_step_remote(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                parsed = urlsplit(user_input[CONF_GATEWAY_URL])
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                    raise ValueError('Invalid Bluetooth host URL')
                user_input['connection_type'] = 'remote'
                self._api = await get_api(self.hass, user_input)
                info = await self._api.info()
                await self.async_set_unique_id(info['gateway_id'])
                self._abort_if_unique_id_configured()
                self._settings = user_input
                return await self.async_step_menu()
            except ClientResponseError as error:
                errors['base'] = 'invalid_auth' if error.status == 401 else 'cannot_connect'
            except (ClientError, TimeoutError):
                errors['base'] = 'cannot_connect'
            except (ValueError, KeyError):
                errors['base'] = 'invalid_gateway'
        return self.async_show_form(step_id='remote', errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_GATEWAY_URL): str,
            vol.Required(CONF_TOKEN): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        }))

    async def async_step_finish(self, user_input=None):
        return self.async_create_entry(title='Beacon Cooked', data=self._settings)


class BeaconOptionsFlow(DeviceWizard, config_entries.OptionsFlow):
    def __init__(self, entry):
        self._settings = entry.data

    async def async_step_init(self, user_input=None):
        self._api = await get_api(self.hass, self._settings)
        return await self.async_step_menu()

    async def async_step_finish(self, user_input=None):
        return self.async_create_entry(title='', data={'revision': self.config_entry.options.get('revision', 0) + 1})
