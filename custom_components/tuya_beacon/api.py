"""Client for a local or remote Beacon transmitter."""
from aiohttp import ClientSession, ClientTimeout


async def get_api(hass, data):
    if data.get('connection_type', 'remote') == 'local':
        from .local_api import get_local_api
        return await get_local_api(hass, data['adapter'])
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    return BeaconAPI(async_get_clientsession(hass), data['gateway_url'], data['token'])


class BeaconAPI:
    def __init__(self, session: ClientSession, url: str, token: str):
        self.session = session
        self.url = url.rstrip('/')
        self.headers = {'Authorization': f'Bearer {token}'}

    async def info(self):
        async with self.session.get(self.url + '/v1/info', headers=self.headers,
                                    timeout=ClientTimeout(total=45)) as response:
            response.raise_for_status()
            data = await response.json()
            if data.get('api_version') != 1:
                raise ValueError('Unsupported gateway API')
            return data

    async def post(self, path, body):
        async with self.session.post(f'{self.url}{path}',
                                     headers=self.headers, json=body,
                                     timeout=ClientTimeout(total=45)) as response:
            response.raise_for_status()
            return await response.json()

    async def command(self, light_id, body, pair=False):
        action = 'pair' if pair else 'command'
        return await self.post(f'/v1/lights/{light_id}/{action}', body)

    async def discover(self):
        return await self.post('/v1/discover', {'seconds': 8})

    async def enroll(self, mac, name):
        return await self.post('/v1/enroll', {'mac': mac, 'name': name})

    async def confirm(self, light_id, confirmed, effect=None):
        body = {'confirmed': confirmed}
        if effect is not None:
            body['effect'] = effect
        return await self.post(f'/v1/lights/{light_id}/confirm', body)
