"""Tuya Beacon control through a network Bluetooth gateway."""
from datetime import timedelta
from aiohttp import ClientError
from homeassistant.const import Platform
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .api import BeaconAPI
from .const import CONF_GATEWAY_URL, CONF_TOKEN
import logging

PLATFORMS = [Platform.LIGHT, Platform.BUTTON]


class BeaconCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, logging.getLogger(__name__), name='Tuya Beacon',
                         config_entry=entry, update_interval=timedelta(seconds=15))
        self.api = BeaconAPI(async_get_clientsession(hass), entry.data[CONF_GATEWAY_URL], entry.data[CONF_TOKEN])

    async def _async_update_data(self):
        try:
            return await self.api.info()
        except (ClientError, TimeoutError, ValueError) as error:
            raise UpdateFailed('Cannot reach Beacon gateway') from error


async def async_setup_entry(hass, entry):
    if entry.title == 'Tuya Beacon':
        hass.config_entries.async_update_entry(entry, title='Beacon Cooked')
    coordinator = BeaconCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
