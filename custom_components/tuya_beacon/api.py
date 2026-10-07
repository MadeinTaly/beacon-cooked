"""Client for a local or remote Beacon transmitter."""
from aiohttp import ClientSession, ClientTimeout


class BeaconAPI:
    def __init__(self, session: ClientSession, url: str, token: str):
        self.session = session
        self.url = url.rstrip('/')
        self.headers = {'Authorization': f'Bearer {token}'}

    async def info(self):
        async with self.session.get(self.url + '/v1/info', headers=self.headers,
                                    timeout=ClientTimeout(total=10)) as response:
            response.raise_for_status()
            data = await response.json()
            if data.get('api_version') != 1:
                raise ValueError('Unsupported gateway API')
            return data

    async def command(self, light_id, body, pair=False):
        action = 'pair' if pair else 'command'
        async with self.session.post(f'{self.url}/v1/lights/{light_id}/{action}',
                                     headers=self.headers, json=body,
                                     timeout=ClientTimeout(total=45)) as response:
            response.raise_for_status()
            return await response.json()
