"""Exercise an installed HA integration and real remote radio; changes light colors.

Required environment: HA_URL, HA_TOKEN, BEACON_URL, BEACON_TOKEN,
BEACON_LIGHT_ID, HA_LIGHT_ENTITY. Optional: MQTT_HOST, MQTT_PREFIX, MQTT_PORT.
No physical acknowledgement is inferred from successful commands.
"""
import json
import os
import time
import urllib.error
import urllib.request


def request(base, token, path, body=None):
    req = urllib.request.Request(base.rstrip('/') + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def main():
    ha_url, ha_token = os.environ['HA_URL'], os.environ['HA_TOKEN']
    beacon_url, beacon_token = os.environ['BEACON_URL'], os.environ['BEACON_TOKEN']
    light_id, entity = os.environ['BEACON_LIGHT_ID'], os.environ['HA_LIGHT_ENTITY']
    def ha(path, body=None):
        return request(ha_url, ha_token, path, body)
    def beacon(path, body=None):
        return request(beacon_url, beacon_token, path, body)
    def light():
        return next(x for x in beacon('/v1/info')['lights'] if x['id'] == light_id)
    def wait_state(expected):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if all(light()['state'].get(k) == v for k, v in expected.items()):
                return
            time.sleep(0.5)
        raise AssertionError('Command state did not reach expected value')
    info = beacon('/v1/info')
    assert info['state_source'] == 'last_command'
    original = dict(light()['state'])
    try:
        try:
            request(beacon_url, 'invalid-test-token', '/v1/info')
            raise AssertionError('Invalid token accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 401
        try:
            beacon(f'/v1/lights/{light_id}/command', {'effect': 'Unknown'})
            raise AssertionError('Invalid color accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
        print('PASS: HTTP authentication and command validation')
        for service, expected in [('turn_off', {'on': False}),
                                  ('turn_on', {'on': True, 'effect': 'Purple'}),
                                  ('turn_on', {'on': True, 'effect': 'Blue'})]:
            body = {'entity_id': entity}
            if 'effect' in expected:
                body['effect'] = expected['effect']
            ha('/api/services/light/' + service, body)
            wait_state(expected)
        print('PASS: HA native light services -> HTTP -> real Bluetooth driver')
        entries = [x for x in ha('/api/config/config_entries/entry') if x['domain'] == 'tuya_beacon']
        entry_id = os.environ.get('HA_CONFIG_ENTRY')
        if not entry_id:
            assert len(entries) == 1, 'Set HA_CONFIG_ENTRY when multiple Bluetooth hosts are configured'
            entry_id = entries[0]['entry_id']
        flow = ha('/api/config/config_entries/options/flow', {'handler': entry_id})
        path = '/api/config/config_entries/options/flow/' + flow['flow_id']
        for body, step in [({'next_step_id': 'known_devices'}, 'known_devices'),
                           ({'device': light_id, 'action': 'test'}, 'test'),
                           ({'effect': 'Blue'}, 'verify'),
                           ({'result': 'cancel'}, 'menu')]:
            result = ha(path, body)
            assert result['step_id'] == step and not result.get('errors')
        result = ha(path, {'next_step_id': 'finish'})
        assert result['type'] == 'create_entry'
        print('PASS: real HA options wizard, color test, cancel, save and reload')
        flow = ha('/api/config/config_entries/options/flow', {'handler': entry_id})
        path = '/api/config/config_entries/options/flow/' + flow['flow_id']
        ha(path, {'next_step_id': 'scan'})
        result = ha(path, {})
        assert result['step_id'] in ('scan', 'select_device')
        assert not result.get('errors') or result['errors'] == {'base': 'no_devices'}
        # Abort the scan flow without creating, binding or confirming a light.
        req = urllib.request.Request(ha_url.rstrip('/') + path, method='DELETE',
            headers={'Authorization': 'Bearer ' + ha_token})
        with urllib.request.urlopen(req, timeout=15):
            pass
        print('PASS: real HA discovery wizard -> real HCI scan (no association inferred)')
        if os.environ.get('MQTT_HOST'):
            import paho.mqtt.client as mqtt
            client = mqtt.Client(client_id='beacon-cooked-e2e')
            client.connect(os.environ['MQTT_HOST'], int(os.environ.get('MQTT_PORT', '1883')), 60)
            client.loop_start()
            try:
                topic = os.environ.get('MQTT_PREFIX', 'beacon_cooked') + '/' + light_id + '/set'
                result = client.publish(topic, json.dumps({'state': 'ON', 'effect': 'Purple'}), qos=1)
                result.wait_for_publish(timeout=10)
                wait_state({'on': True, 'effect': 'Purple'})
            finally:
                client.disconnect()
                client.loop_stop()
            print('PASS: MQTT broker -> shared real Bluetooth command path')
    finally:
        if original:
            beacon(f'/v1/lights/{light_id}/command', original)
    print('Original commanded state restored. Physical output is not measured by this test.')


if __name__ == '__main__':
    main()
