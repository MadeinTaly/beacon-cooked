"""Tuya Beacon AK80x codec reconstructed from the official GCC 6.3 LTO SDK.

The virtual remote pathway was verified physically on a Tuya Beacon spotlight.
The phone application's device-specific key has not been recovered.
The radio command payload is a big-endian XXTEA block in a 128-bit UUID AD.
"""
import base64
import struct

MASK = 0xffffffff
DELTA = 0x9e3779b9
PAIR_KEY = b'jngwRugsvwtGN00a'


def xxtea(block, key, decrypt=False):
    if len(block) != 16 or len(key) != 16:
        raise ValueError('Block and key must each be 16 bytes')
    v = list(struct.unpack('>4I', block))
    k = struct.unpack('>4I', key)
    def mix(z, y, total, p, e):
        return (((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^
                ((total ^ y) + (k[(p & 3) ^ e] ^ z))) & MASK
    if decrypt:
        total = 19 * DELTA & MASK
        y = v[0]
        for _ in range(19):
            e = total >> 2 & 3
            for p in range(3, 0, -1):
                z = v[p - 1]
                v[p] = (v[p] - mix(z, y, total, p, e)) & MASK
                y = v[p]
            z = v[-1]
            v[0] = (v[0] - mix(z, y, total, 0, e)) & MASK
            y = v[0]
            total = (total - DELTA) & MASK
    else:
        total = 0
        z = v[-1]
        for _ in range(19):
            total = (total + DELTA) & MASK
            e = total >> 2 & 3
            for p in range(3):
                y = v[p + 1]
                v[p] = (v[p] + mix(z, y, total, p, e)) & MASK
                z = v[p]
            y = v[0]
            v[-1] = (v[-1] + mix(z, y, total, 3, e)) & MASK
            z = v[-1]
    return struct.pack('>4I', *v)


def crc(data):
    value = 0
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value ^ 0x8380) << 1 if value & 0x8000 else value << 1) & MASK
    return value >> 8 & 255


def ad_fields(raw):
    offset = 0
    fields = {}
    while offset < len(raw):
        length = raw[offset]
        if not length:
            break
        if offset + length >= len(raw):
            raise ValueError('Truncated advertising field')
        fields[raw[offset + 1]] = raw[offset + 2:offset + 1 + length]
        offset += length + 1
    return fields


def decode(raw, key):
    fields = ad_fields(raw)
    mac = base64.b64decode(fields[9], validate=True)
    plain = xxtea(fields[7], key, decrypt=True)
    if len(mac) != 6 or plain[1] != crc(mac) or plain[14] != crc(plain[1:14]):
        raise ValueError('Key or frame validation failed')
    return {'mac': mac.hex(':'), 'command': plain[0],
            'sequence': int.from_bytes(plain[2:5], 'big'),
            'params': plain[5:14].hex(), 'tp': plain[15],
            'plaintext': plain.hex()}


def encode(mac, command, sequence, params, key, tp=0):
    if len(mac) != 6 or len(params) > 9 or not 0 <= sequence < 1 << 24:
        raise ValueError('Invalid address, parameters or sequence')
    plain = bytes([command, crc(mac)]) + sequence.to_bytes(3, 'big')
    plain += params.ljust(9, b'\0')
    plain += bytes([crc(plain[1:14]), tp])
    return b'\x02\x01\x01\x09\x09' + base64.b64encode(mac) + b'\x11\x07' + xxtea(plain, key)


if __name__ == '__main__':
    mac = bytes.fromhex('dc23509fa49a')
    # SDK DP 11: HSV, H=0, S=100, V=100 (red). This is a synthetic test key.
    raw = encode(mac, 7, 123, bytes.fromhex('0b000400006464'), PAIR_KEY)
    decoded = decode(raw, PAIR_KEY)
    assert decoded['sequence'] == 123 and decoded['command'] == 7
    assert ad_fields(raw)[9] == b'3CNQn6Sa'
    assert xxtea(xxtea(bytes(range(16)), PAIR_KEY), PAIR_KEY, True) == bytes(range(16))
    print('Synthetic codec checks passed; device key still unverified.')
