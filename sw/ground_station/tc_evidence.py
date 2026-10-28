"""Offline correlation of one real ADC control transaction and its RF return.

This checks evidence supplied by the caller, not the authenticity of acquisition
logs or physical wiring. Only independently supplied relay diagnostics establish
SPI readback; an ATM1 ACK is never promoted to independent SPI evidence.
"""
import binascii
import math
import re

from .telemetry import TM1_FIELDS, parse_tm1
from sw.tools.telemetry_downlink import parse_frame

_U32 = (1 << 32)-1
_HZ_TOLERANCE = 10000
_SCALARS = ('events', 'network', 'armed', 'pending', 'decoded', 'applied', 'failures', 'spi_valid')


def _json_finite(value):
    """Reject non-JSON values and nonfinite floats even in report metadata."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_finite(item)
        return
    if type(value) is dict and all(type(k) is str for k in value):
        for item in value.values():
            _json_finite(item)
        return
    raise ValueError('Evidence contains a non-JSON or nonfinite value')


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(label+' has invalid integer type or range')
    return value


def _tm1(value, label):
    if type(value) is not dict or set(value) != set(TM1_FIELDS):
        raise ValueError(label+' must be the complete parse_tm1 result')
    if any(type(v) is not int for v in value.values()):
        raise ValueError(label+' fields must be integers, not bool/float/string')
    prefix = 'TM1 '+' '.join(f'{key}={value[key]}' for key in TM1_FIELDS)
    line = prefix+f' crc16={binascii.crc_hqx(prefix.encode("ascii"), 0xffff):04X}'
    checked = parse_tm1(line)
    # ATM1 stores these in uint16, but the RF_SET header and ACK parser use
    # 14 bits (adda_protocol.c:242,296,316,340), not the entire storage width.
    for key in ('s_udp_seq', 'a_udp_seq'):
        _integer(checked[key], 0, 0x3fff, label+'.'+key)
    return checked


def _flatten(snapshot):
    flat = {key: snapshot[key] for key in _SCALARS}
    flat['uptime_ms'] = snapshot['uptime_ms']
    for prefix, name in (('d', 'decoded_record'), ('s', 'send_record'), ('a', 'ack_record')):
        record = snapshot[name]
        for field in ('valid', 'event', 'origin', 'air_seq', 'rx_mhz', 'tx_mhz'):
            flat[prefix+'_'+field] = int(record[field])
    for field in ('udp_seq', 'count', 'rc'):
        flat['s_'+field] = snapshot['send_record'][field]
    for field in ('udp_seq', 'rc', 'rx_hz', 'tx_hz'):
        flat['a_'+field] = snapshot['ack_record'][field]
    return flat


def assess_transaction(requested, before, frozen, spi, rf_report, dac_sequence):
    """Return a JSON-compatible passed result, or raise ValueError on any gap.

    requested has rx_mhz/tx_mhz/air_seq; before/frozen are full TM1 dictionaries;
    spi is RelayConsole.diagnostics(); rf_report is decode_capture_windows().
    dac_sequence is the sender's sequence BEFORE the single tmsend request.
    Repeated physical frames count as frames, never as extra transactions.
    """
    for value in (requested, before, frozen, spi, rf_report, dac_sequence):
        _json_finite(value)
    if type(requested) is not dict or set(requested) != {'rx_mhz', 'tx_mhz', 'air_seq'}:
        raise ValueError('requested must specify rx_mhz, tx_mhz and air_seq')
    request = {key: _integer(requested[key], 0 if key == 'air_seq' else 70,
                            255 if key == 'air_seq' else 6000, key)
               for key in requested}
    sequence = _integer(dac_sequence, 0, _U32, 'dac_sequence')
    before, frozen = _tm1(before, 'before'), _tm1(frozen, 'frozen')
    if any(frozen[key] for key in ('network', 'armed', 'pending')):
        raise ValueError('frozen network, armed and pending must all be zero')
    if frozen['uptime_ms'] < before['uptime_ms']:
        raise ValueError('TM1 uptime regressed; boot continuity is not established')
    if (frozen['applied'] != before['applied']+1 or
            frozen['decoded'] < before['decoded']+1 or
            frozen['failures'] != before['failures']):
        raise ValueError('Expected one new applied command, a fresh decode and no new failure')
    for prefix in ('d', 's', 'a'):
        if frozen[prefix+'_valid'] != 1 or frozen[prefix+'_origin'] != 1:
            raise ValueError('All records must be valid ADC_NORMAL records')
        if any(frozen[prefix+'_'+key] != value for key, value in request.items()):
            raise ValueError('Record command does not match requested transaction')
    if not (before['events'] < frozen['d_event'] < frozen['s_event'] <
            frozen['a_event'] == frozen['events']):
        raise ValueError('Records must be fresh and ordered decoded < send < ACK')
    if (frozen['s_udp_seq'] != frozen['a_udp_seq'] or frozen['s_rc'] or
            frozen['a_rc'] or not 1 <= frozen['s_count'] <= 255):
        raise ValueError('UDP sequence, successful receipts or send count mismatch')
    if type(spi) is not dict:
        raise ValueError('Independent SPI diagnostics are missing')
    independent = {}
    ack = dict(udp_seq=frozen['a_udp_seq'], rc=frozen['a_rc'])
    for axis in ('rx', 'tx'):
        name = 'relay_'+axis+'_hz_readback'
        actual = _integer(spi.get(name), 70_000_000, 6_000_000_000, name)
        acknowledged = frozen['a_'+axis+'_hz']
        target = request[axis+'_mhz']*1_000_000
        if (abs(actual-target) > _HZ_TOLERANCE or
                abs(acknowledged-target) > _HZ_TOLERANCE or
                abs(actual-acknowledged) > _HZ_TOLERANCE):
            raise ValueError('Independent SPI / ACK frequency correlation failed: '+axis)
        independent[axis+'_hz'] = actual
        ack[axis+'_hz'] = acknowledged
    for key, maximum in (('relay_tx_atten_db_readback', 89), ('relay_rx_gain_db_readback', 76)):
        if key in spi:
            independent[key] = _integer(spi[key], 0, maximum, key)
    if type(rf_report) is not dict or type(rf_report.get('frames')) is not list or not rf_report['frames']:
        raise ValueError('Actual RF frame evidence is missing; telemetry summaries are insufficient')
    unique = {}
    for frame in rf_report['frames']:
        if type(frame) is not dict:
            raise ValueError('Malformed RF frame')
        text = frame.get('payload_hex')
        if type(text) is not str or re.fullmatch(r'[0-9a-fA-F]{192}', text) is None:
            raise ValueError('RF frame must contain exactly 96 payload bytes')
        checksum = _integer(frame.get('crc16'), 0, 65535, 'frame.crc16')
        payload = bytes.fromhex(text)
        # Never trust crc_valid, telemetry, or the report's aggregate counters.
        snapshot = parse_frame(b'\xaa\xaa\x60'+payload+checksum.to_bytes(2, 'big'))
        if snapshot['sequence'] != sequence:
            raise ValueError('RF snapshot has an old or unexpected DAC sequence')
        if not frozen['uptime_ms'] <= snapshot['uptime_ms'] <= frozen['uptime_ms']+120_000:
            raise ValueError('RF snapshot is older than frozen state or over 120 seconds later')
        flat = _flatten(snapshot)
        for key in TM1_FIELDS:
            if key != 'uptime_ms' and flat[key] != frozen[key]:
                raise ValueError('RF snapshot differs from frozen state: '+key)
        unique[payload] = snapshot
    if len(unique) != 1:
        raise ValueError('Single finite request must contain one unique ATM1 snapshot')
    snapshot = next(iter(unique.values()))
    return dict(passed=True, rf_source='actual_iq_crc_checked',
                transaction=dict(request, udp_seq=frozen['s_udp_seq'],
                                 decoded_event=frozen['d_event'], send_event=frozen['s_event'],
                                 ack_event=frozen['a_event']),
                physical_frame_count=len(rf_report['frames']), unique_snapshot_count=len(unique),
                dac_sequence=sequence, frozen_events=frozen['events'],
                decoded=frozen['decoded'], applied=frozen['applied'], failures=frozen['failures'],
                rf_uptime_ms=snapshot['uptime_ms'], ack=ack, spi=independent,
                spi_source='independent_relay_diagnostics',
                acquisition_authentication='caller must retain actual IQ and acquisition logs')
