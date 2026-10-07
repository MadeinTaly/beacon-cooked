# First verified device: AliExpress Tuya Bluetooth WRGB spotlight

| Field | Observed value |
|---|---|
| Product type | WRGB LED spotlight |
| Seller / exact model | Not identified |
| Mobile application | Tuya |
| Radio protocol | Tuya Beacon, nonconnectable device advertisements |
| Advertisement signature | Manufacturer bytes `07 d0`, followed by `01` or `04` and the device MAC |
| Control frames | Base64 address in local name; 16-byte XXTEA block in AD type `0x07` |
| Working control path | Associated virtual Bluetooth remote |
| Lamp chipset / firmware version | Unknown |
| Physically verified colors | Red, blue, purple |
| Gateway hardware verified | Intel AX211; CSR Bluetooth 4.0 USB adapter `0a12:0001` |
| Deployment verified | Proxmox host Bluetooth → LAN → HA Docker container inside LXC |
| Date | 2026-10-07 |

The light still accepted the virtual remote after the user triggered pairing and
waited for blinking to end. This does not prove a complete factory reset occurred.

On/off commands are implemented; independent physical confirmation of off is still
needed. Other named hues are generated using the same verified packet format, but
were not individually physically checked. White, brightness and saturation are not
advertised as supported controls in this release.

WRGB describes the LEDs reported by the owner. It does not establish independent
white-channel control through the reverse-engineered remote pathway.

Compatibility matching is based on packet structure, not solely the Tuya name, MAC
prefix or USB adapter. A device with a similar advertisement remains a candidate
until control has been physically confirmed.
