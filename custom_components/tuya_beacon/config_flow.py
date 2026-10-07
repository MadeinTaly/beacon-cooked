"""Configure a gateway from the Home Assistant UI."""
from urllib.parse import urlsplit
import voluptuous as vol
from aiohttp import ClientError, ClientResponseError
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .api import BeaconAPI
from .const import DOMAIN, CONF_GATEWAY_URL, CONF_TOKEN


class BeaconConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                parsed = urlsplit(user_input[CONF_GATEWAY_URL])
                if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                    raise ValueError('Invalid gateway URL')
                info = await BeaconAPI(async_get_clientsession(self.hass),
                                       user_input[CONF_GATEWAY_URL], user_input[CONF_TOKEN]).info()
                await self.async_set_unique_id(info['gateway_id'])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title='Tuya Beacon', data=user_input)
            except ClientResponseError as error:
                errors['base'] = 'invalid_auth' if error.status == 401 else 'cannot_connect'
            except (ClientError, TimeoutError):
                errors['base'] = 'cannot_connect'
            except (ValueError, KeyError):
                errors['base'] = 'invalid_gateway'
        return self.async_show_form(step_id='user', errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_GATEWAY_URL): str,
            vol.Required(CONF_TOKEN): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        }))
