"""Explicitly bind a virtual remote during the lamp's binding window."""
from aiohttp import ClientError
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(BeaconPairButton(coordinator, lamp) for lamp in coordinator.data['lights'])


class BeaconPairButton(CoordinatorEntity, ButtonEntity):
    _attr_has_entity_name = True
    _attr_translation_key = 'pair_remote'
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = 'mdi:bluetooth-connect'

    def __init__(self, coordinator, lamp):
        super().__init__(coordinator)
        self.light_id = lamp['id']
        unique = f"{coordinator.data['gateway_id']}_{self.light_id}"
        self._attr_unique_id = unique + '_pair'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, unique)})

    async def async_press(self):
        try:
            await self.coordinator.api.command(self.light_id, {'seconds': 15}, pair=True)
        except (ClientError, TimeoutError) as error:
            raise HomeAssistantError('Beacon remote binding transmission failed') from error
