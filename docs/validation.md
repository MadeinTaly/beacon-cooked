# Validation — v0.3.1

Tested on 2026-10-07. Stable scope: control of the already associated, verified
AliExpress WRGB spotlight using the Linux Bluetooth service and native Home Assistant
integration or MQTT. Stability here does not establish support for unknown Tuya devices.

## Automated checks

- Nine codec/discovery/gateway/MQTT unit tests passed.
- Six wizard tests passed inside Home Assistant 2026.9.3, including the complete
  discovery → selection → binding → color test → confirmation software flow with
  a simulated API, cancellation and isolation checks.
- Python compilation, JSON parsing and installer shell syntax passed.
- Real end-to-end tests passed from inside the HA Docker container in an LXC:
  HA light services → authenticated HTTP → CSR Bluetooth 4.0 HCI transmission;
  actual HA options wizard → color test → cancellation → save/reload;
  actual discovery wizard → HCI scan; MQTT broker → shared transmission path.
- Invalid HTTP credentials and invalid color commands were rejected.
- The same real end-to-end suite passed after restarting the Bluetooth service.
  Persisted counters advanced and the original commanded state was restored.
- HACS downloaded the tagged integration into the real installation.

The automated discovery scan ran with the lamp out of pairing mode. It verifies
execution and the no-device path, not fresh physical discovery or association.
Successful HCI commands and optimistic state are not lamp acknowledgements.

## Physical observations

The owner previously confirmed red, blue and purple on the actual spotlight.
Blue was also confirmed after a command from the real HA configuration wizard.
A raw local Intel AX211 probe and extended-advertising transmission succeeded;
the remote CSR adapter uses legacy advertising.

## Not physically validated end to end

- Fresh factory activation without the Tuya app.
- First association through the new discovery wizard.
- Complete local-USB onboarding inside Home Assistant with an exposed adapter.
- Independent control of multiple physical lamps.
- Brightness, saturation and white channels. These are not advertised as controls.

## Repeat the real-system checks

Run `python scripts/e2e.py` in a Python environment with access to the HA and
Bluetooth-host APIs. Set `HA_URL`, `HA_TOKEN`, `BEACON_URL`, `BEACON_TOKEN`,
`BEACON_LIGHT_ID` and `HA_LIGHT_ENTITY` privately in the environment. When multiple
Beacon Cooked hosts are configured, also set `HA_CONFIG_ENTRY`. Optional MQTT
validation uses `MQTT_HOST`, `MQTT_PORT` and `MQTT_PREFIX` and requires paho-mqtt.
This script operates an already configured light; it does not confirm physical
output or bind additional remotes.
