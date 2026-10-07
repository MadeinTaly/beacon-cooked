"""Expose the verified on/off and hue commands as a light with color effects."""
from aiohttp import ClientError
from homeassistant.components.light import ATTR_EFFECT, ColorMode, LightEntity, LightEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(BeaconLight(coordinator, lamp) for lamp in coordinator.data['lights'])


class BeaconLight(CoordinatorEntity, LightEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_assumed_state = True

    def __init__(self, coordinator, lamp):
        super().__init__(coordinator)
        self.light_id = lamp['id']
        self.device_mac = lamp.get('mac')
        self.profile = lamp.get('profile', 'unverified_beacon')
        self.capabilities_verified = lamp.get('capabilities_verified', [])
        unique = f"{coordinator.data['gateway_id']}_{self.light_id}"
        self._attr_unique_id = unique
        self._attr_effect_list = list(coordinator.data['colors'])
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, unique)}, name=lamp['name'],
                                           manufacturer='Tuya compatible', model=lamp.get('model', 'Beacon virtual remote group'))

    @property
    def state_data(self):
        return next((x['state'] for x in self.coordinator.data['lights'] if x['id'] == self.light_id), {})

    @property
    def is_on(self):
        return self.state_data.get('on')

    @property
    def effect(self):
        return self.state_data.get('effect')

    @property
    def extra_state_attributes(self):
        return {'state_source': 'last_command', 'device_acknowledged': False,
                'device_mac': self.device_mac, 'device_profile': self.profile,
                'protocol': 'tuya_beacon_xxtea_v1',
                'capabilities_verified': self.capabilities_verified}

    async def _send(self, body):
        try:
            await self.coordinator.api.command(self.light_id, body)
            await self.coordinator.async_request_refresh()
        except (ClientError, TimeoutError, ValueError) as error:
            raise HomeAssistantError('Beacon gateway transmission failed') from error

    async def async_turn_on(self, **kwargs):
        body = {'on': True}
        if ATTR_EFFECT in kwargs:
            body['effect'] = kwargs[ATTR_EFFECT]
        await self._send(body)

    async def async_turn_off(self, **kwargs):
        await self._send({'on': False})
