# Beacon Cooked

### Local Tuya Beacon control · Home Assistant · MQTT

![Beacon Cooked](docs/beacon-cooked.svg)

**Your Bluetooth lights, cooked locally.** An unofficial open-source gateway and
HACS integration for Tuya Beacon lights. Put Bluetooth on a Linux host, and control
the lights from Home Assistant on another machine.

[Install through HACS](https://my.home-assistant.io/redirect/hacs_repository/?owner=MadeinTaly&repository=beacon-cooked&category=integration)
· [First verified WRGB spotlight](docs/devices/wrgb-spotlight.md)
· [Report another device](https://github.com/MadeinTaly/beacon-cooked/issues/new)

Unofficial local control of Tuya Beacon lights through a network Bluetooth gateway.
Home Assistant and the Bluetooth USB adapter can run on different machines. No Tuya
cloud account or cloud API is used for commands.

## Status and supported hardware

Experimental version 0.2.0. Red and blue were physically confirmed on one AliExpress
WRGB spotlight using a virtual remote reconstructed from Tuya's public AK80x SDK.
The actual spotlight chipset and commercial model are not identified. This is **not**
support for every product advertised as Tuya Bluetooth or Tuya BLE Mesh.

Purple was physically confirmed using a CSR Bluetooth 4.0 USB adapter on
Proxmox, with commands originating inside the Home Assistant container in an LXC.
The original experiment used an Intel AX211 Bluetooth adapter.

Supported UI controls: on/off and eight named color effects. Saturation, RGB
brightness and white controls are not advertised: the examined SDK ignores HSV
saturation/value on the virtual remote path. Additional hues remain experimental.

The light state is **optimistic**: it is the last command sent, not device feedback.
Gateway reachability does not prove the lamp is powered or within radio range.

## Architecture

Home Assistant custom integration → authenticated HTTP API → Linux gateway → BLE advertisements.

The gateway can run on Proxmox, a Raspberry Pi or another Linux machine with a
dedicated Bluetooth adapter. HACS installs the integration, **not** the host gateway.
A standard ESPHome Bluetooth proxy is not an implemented transport in this version.
The adapter must support legacy BLE advertising and setting a static random address.

## Gateway installation

On a Debian-based gateway host, install `bluez` and enable Bluetooth. Copy
`gateway/server.py` and `gateway/codec.py` to `/opt/tuya-beacon/`, and the unit
`gateway/tuya-beacon.service` to `/etc/systemd/system/`.

Create `/etc/tuya-beacon/config.json`, readable only by root:

```json
{
  "gateway_id": "my-beacon-gateway",
  "adapter": "hci0",
  "bind": "192.168.1.10",
  "port": 8787,
  "token": "GENERATE_A_LONG_RANDOM_TOKEN",
  "lights": [
    {
      "id": "spotlight",
      "name": "Spotlight",
      "sender": "c2:00:00:00:00:01",
      "salt": "6172"
    }
  ]
}
```

Run `systemctl daemon-reload` and `systemctl enable --now tuya-beacon`.
The service uses legacy HCI commands and briefly enables advertising for each frame.
Its unit restricts filesystem writes and capabilities, but runs as root for HCI access.
Use a trusted LAN; HTTP tokens are not encrypted on the wire. HTTPS through a local
reverse proxy is supported by the integration's URL field. Do not expose the API publicly.

`gateway_id` and light IDs must stay stable. Sender addresses must be static random
MACs (first byte's two high bits set), unique for each virtual remote, with 2-byte salts.
Keep `/var/lib/tuya-beacon/state.json`: it reserves sequence counters before sending,
preventing counter reuse after crashes. Back it up together with the gateway configuration.

## Home Assistant installation

This repository follows the HACS custom integration layout. Once the repository is
available to HACS, add its URL under **HACS → Custom repositories → Integration**.
Alternatively copy `custom_components/tuya_beacon` into your HA configuration directory.

Restart Home Assistant, then add **Tuya Beacon** under **Settings → Devices & services**.
Enter the gateway URL (for example `http://192.168.1.10:8787`) and its token.
One light and one configuration button are created per configured virtual remote.

To bind a new remote, press **Bind virtual remote** and power-cycle the intended lamp
during the 15-second transmission window. Do not factory-reset a working lamp solely
to bind the remote. Binding is not acknowledged: test a color afterward. The SDK's
binding window and acceptance conditions vary by firmware.

### Multiple lamps

One remote can control multiple lamps that have been bound to it, as a group. Each
`lights` entry represents a **virtual remote group**, not an individually addressed
physical MAC. Independent control requires separate sender identities and selective
binding with only the intended lamp in its binding window. This arrangement has not
yet been physically tested with multiple lamps; a 20-lamp setup is not validated.

## API

All routes require `Authorization: Bearer TOKEN`.

- `GET /v1/info`: gateway identity, configured groups, colors, last command states.
- `POST /v1/lights/ID/command`: `{"on": true, "effect": "Purple"}` or `{"on": false}`.
- `POST /v1/lights/ID/pair`: `{"seconds": 15}`; sends only binding packets.
- `POST /v1/discover`: `{"seconds": 8}`; detects the observed Beacon advertisement
  format and returns MAC, RSSI and pairing indication. Generic Tuya BLE is not matched.
- `POST /v1/enroll`: `{"mac": "MAC_FROM_SCAN", "name": "My light"}`; creates a new
  virtual remote identity for a recently discovered device. This does **not** prove binding.
- `POST /v1/lights/ID/confirm`: `{"confirmed": true}`; records the user's physical
  confirmation. It is not a device acknowledgement.

Replies explicitly distinguish `transmitted` from `device_acknowledged` (always false).
Radio commands are serialized across groups and request bodies are bounded.

## MQTT (optional)

Install `python3-paho-mqtt` on the gateway and add this section to its configuration:

```json
"mqtt": {
  "enabled": true,
  "host": "YOUR_BROKER_HOST",
  "port": 1883,
  "prefix": "beacon_cooked",
  "discovery": false
}
```

Optional keys: `username`, `password`, `tls`. Restart the gateway after changing it.
Publish `{"state":"ON","effect":"Purple"}` to `beacon_cooked/spotlight/set`.
Last commanded state is retained at `beacon_cooked/spotlight/state`; gateway connection
status is retained at `beacon_cooked/availability` with a last will of `offline`.

Set `discovery: true` to use MQTT auto-discovery **instead of** the native HACS light.
Using both creates two entities controlling the same remote group. MQTT commands and
native HA commands share the radio lock and sequence counters.

## Discovery and onboarding status

The gateway exposes scan and enrollment APIs. The current HACS UI connects a gateway
and exposes its configured lights. A full graphical scan → select → bind → physically
verify wizard is a next step; it is not shipped in this release.

Initial factory pairing without the Tuya app has not been demonstrated. The examined
SDK accepts remote binding only in a particular device state; do not assume the remote
binding button replaces every manufacturer's initial provisioning procedure.

## Roadmap

- Guided discovery and binding from Home Assistant, with a physical color check.
- Identify and document more spotlight models; verify independent multi-lamp control.
- Verify brightness and white controls before exposing them in HA.
- Additional gateway platforms, including an ESP32 transmitter.

## Development

`python3 -m unittest discover -s tests -v` checks packet encoding, persisted counters,
invalid requests and radio failure behavior. `python3 -m compileall -q custom_components gateway`
checks Python syntax. Physical compatibility requires a real lamp test.

## Attribution

Protocol and codec reconstructed from the public
[Tuya IoTOS Beacon SDK AK80x](https://github.com/tuya/tuya-iotos-beacon-sdk-ak80x).
Its MIT copyright and license notice are preserved in `gateway/LICENSE-Tuya`.
This project is independent and is not endorsed by Tuya, Home Assistant or HACS.
