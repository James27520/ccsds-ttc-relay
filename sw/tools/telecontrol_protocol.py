"""Exact telecontrol frequency representation, shared by offline and host paths.

Legacy commands carry whole MHz. n256_khz_v1 keeps the same two uint16
fields, with independent 1 kHz LO offsets and operation codes marked by bit 7.
"""
from numbers import Integral

OPERATIONS = {'frequency': 0x01, 'enable': 0x21, 'stop': 0x22, 'status': 0x23}
N256_OPERATIONS = {name: version | 0x80 for name, version in OPERATIONS.items()}
N256_ENCODING = 'n256_khz_v1'
LO_BASE_HZ = {'rx': 1_979_500_000, 'tx': 2_169_500_000}
OFFSET_MIN_KHZ, OFFSET_MAX_KHZ = 100, 29_900


def integer(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return int(value)


def normalize_hz_request(*, rx_hz=None, tx_hz=None, air_seq, operation='frequency',
                         encoding=N256_ENCODING):
    """Validate exact LO Hz; stop/status have canonical ignored zero offsets."""
    if encoding != N256_ENCODING or operation not in N256_OPERATIONS:
        raise ValueError('Unknown telecontrol encoding or operation')
    air_seq = integer(air_seq, 0, 255, 'air_seq')
    values = {}
    for axis, supplied in (('rx', rx_hz), ('tx', tx_hz)):
        base = LO_BASE_HZ[axis]
        if operation in ('stop', 'status'):
            value = base
        else:
            value = integer(supplied, base + OFFSET_MIN_KHZ*1000,
                            base + OFFSET_MAX_KHZ*1000, axis+'_hz')
            if (value-base) % 1000:
                raise ValueError(axis+'_hz must be aligned to 1 kHz')
        values[axis+'_hz'] = value
    return dict(values, air_seq=air_seq, operation=operation, encoding=N256_ENCODING)


def wire_fields(requested):
    """Return (version, raw RX uint16, raw TX uint16, air sequence)."""
    operation = requested.get('operation', 'frequency')
    if ('encoding' in requested or 'rx_hz' in requested or 'tx_hz' in requested):
        request = normalize_hz_request(**requested)
        return (N256_OPERATIONS[operation],
                (request['rx_hz']-LO_BASE_HZ['rx'])//1000,
                (request['tx_hz']-LO_BASE_HZ['tx'])//1000, request['air_seq'])
    if operation not in OPERATIONS:
        raise ValueError('Unknown telecontrol operation')
    return (OPERATIONS[operation], integer(requested.get('rx_mhz'), 70, 6000, 'rx_mhz'),
            integer(requested.get('tx_mhz'), 70, 6000, 'tx_mhz'),
            integer(requested.get('air_seq'), 0, 255, 'air_seq'))


def frequency_fields(version, rx_raw, tx_raw):
    """Validate record fields without ever labelling a kHz offset as MHz.

    requested_*_hz remains available when an ACK adds its actual rx_hz/tx_hz.
    """
    if version in N256_OPERATIONS.values():
        operation = next(name for name, code in N256_OPERATIONS.items() if code == version)
        low, high = ((0, 0) if operation in ('stop', 'status') else
                     (OFFSET_MIN_KHZ, OFFSET_MAX_KHZ))
        rx = integer(rx_raw, low, high, 'rx_offset_khz')
        tx = integer(tx_raw, low, high, 'tx_offset_khz')
        rx_hz, tx_hz = LO_BASE_HZ['rx']+rx*1000, LO_BASE_HZ['tx']+tx*1000
        return dict(encoding=N256_ENCODING, rx_offset_khz=rx, tx_offset_khz=tx,
                    rx_hz=rx_hz, tx_hz=tx_hz, requested_rx_hz=rx_hz, requested_tx_hz=tx_hz)
    if version not in OPERATIONS.values():
        raise ValueError('Invalid operation provenance')
    return dict(rx_mhz=integer(rx_raw, 70, 6000, 'rx_mhz'),
                tx_mhz=integer(tx_raw, 70, 6000, 'tx_mhz'))
