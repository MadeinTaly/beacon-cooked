# How Beacon Cooked distinguishes devices

Detection, identity and control compatibility are separate checks.

1. **Protocol fingerprint:** manufacturer bytes `07 d0`, exact observed payload
   length, advertisement header `01` or `04`, and a six-byte embedded MAC matching
   the advertiser. Arbitrary Tuya BLE devices are not accepted just by brand name.
2. **Physical identity:** the embedded static MAC identifies a candidate across
   scans, along with its latest RSSI and pairing indication. A MAC does not identify
   a commercial model, LED layout, firmware version or chipset.
3. **Verified profile:** the first WRGB spotlight has owner-confirmed red, blue and
   purple commands. New candidates start with `unverified_beacon` and an empty
   `capabilities_verified` list. They do not inherit the first lamp's compatibility.
4. **Control identity:** each enrolled physical MAC receives its own randomly
   generated static remote sender address, salt, persisted counter and logical ID.
   Physical MAC metadata is not an individually addressed command destination on
   this pathway. Separate control depends on binding those remote identities to the
   intended lamps, with other lamps outside their remote-binding windows.

Initial factory provisioning and multiple independently bound lamps still require
physical validation. A successful HCI transmission is not confirmation that a lamp
accepted a command. Pairing detection is not confirmation of a completed association.

The gateway API returns protocol, profile, physical MAC and verified capabilities
separately. Home Assistant exposes these as light attributes and uses stable gateway
and remote IDs for entity registration. The public compatibility record contains no
private credentials or owner-specific MAC address.
