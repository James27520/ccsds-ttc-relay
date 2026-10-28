"""Decode actual receiver IQ carrying experimental ATM1 binary telemetry.

AAAA | 96 | ATM1 payload | CCITT-FALSE(payload), MSB first; NOT complete
CCSDS. This offline tool never connects to a radio or transmits. IQ must be
actual sign-extended 12-bit complex receiver samples, not a TX manifest.
Sequence/uptime reset at PS boot; no unique boot ID or authentication exists.
"""
import argparse
import json
from pathlib import Path
import struct
try:
    from . import rf_text_link as phy
except ImportError:
    import rf_text_link as phy

PAYLOAD_BYTES, FRAME_BYTES, BURST_BYTES = 96, 101, 420
RF_CENTER_HZ = 90_500_000
ORIGINS = {0: 'NONE', 1: 'ADC_NORMAL', 2: 'ADC_TEST', 3: 'SYNTHETIC', 4: 'UART_NETTEST'}


def parse_payload(payload):
    """Validate the complete snapshot before returning any values."""
    if not isinstance(payload, bytes) or len(payload) != PAYLOAD_BYTES:
        raise ValueError('ATM1 payload must contain exactly 96 bytes')
    if payload[:4] != b'ATM1' or payload[4] != 1:
        raise ValueError('Unsupported experimental telemetry magic/version')
    flags = payload[5]
    if flags & 0xc0 or payload[6:8] != b'\0\0' or payload[92:] != b'\0'*4 or payload[55]:
        raise ValueError('Nonzero reserved fields')
    seq, uptime, events, decoded, applied, failures = struct.unpack_from('>6I', payload, 8)
    result = dict(protocol='EXPERIMENTAL_ATM1', ccsds=False, sequence=seq,
                  uptime_ms=uptime, events=events, decoded=decoded, applied=applied,
                  failures=failures, network=flags & 1, armed=(flags >> 1) & 1,
                  pending=(flags >> 2) & 1, spi_valid=0,
                  boot_identity=None, sequence_scope='since PS initialization; may repeat after reboot')
    for name, offset, valid_bit, size in [('decoded_record', 32, 3, 10),
                                        ('send_record', 42, 4, 18),
                                        ('ack_record', 60, 5, 32)]:
        valid = bool(flags & (1 << valid_bit))
        event, origin, air_seq, rx, tx = struct.unpack_from('>IBBHH', payload, offset)
        if not valid:
            if any(payload[offset:offset+size]):
                raise ValueError('Invalid record must be zeroed')
        elif origin not in range(1, 5) or not 70 <= rx <= 6000 or not 70 <= tx <= 6000:
            raise ValueError('Invalid record provenance/frequency')
        record = dict(valid=valid, event=event, origin=origin, origin_name=ORIGINS[origin],
                      air_seq=air_seq, rx_mhz=rx, tx_mhz=tx)
        result[name] = record
    transaction, count, rc = struct.unpack_from('>HBxi', payload, 52)
    result['send_record'].update(udp_seq=transaction, count=count, rc=rc,
                                 evidence='local UDP transport acceptance only')
    transaction, rc, rx_hz, tx_hz = struct.unpack_from('>HiQQ', payload, 70)
    if result['ack_record']['valid'] and rc != 0:
        raise ValueError('ATM1 ACK record must be a matched successful ACK')
    result['ack_record'].update(udp_seq=transaction, rc=rc, rx_hz=rx_hz, tx_hz=tx_hz,
                                evidence='matched remote ACK; not independent SPI readback')
    return result


def parse_frame(frame):
    if len(frame) != FRAME_BYTES or frame[:3] != b'\xaa\xaa\x60':
        raise ValueError('Wrong outer frame')
    payload = frame[3:-2]
    if phy.crc16(payload) != int.from_bytes(frame[-2:], 'big'):
        raise ValueError('CRC mismatch')
    return parse_payload(payload)


def decode_capture(raw, *, sample_rate_hz=2_500_000, symbol_rate=100_000,
                   expected_offset_hz=500_000, search_hz=20_000):
    """Blind PHY decode; no expected telemetry, UART state, or TX fixture input."""
    report = phy.decode(raw, sample_rate_hz=sample_rate_hz, symbol_rate=symbol_rate,
                        expected_offset_hz=expected_offset_hz, search_hz=search_hz)
    snapshots = []
    for frame in report['frames']:
        if not frame.get('crc_valid'):
            continue
        try:
            snapshot = parse_payload(bytes.fromhex(frame['payload_hex']))
        except (ValueError, KeyError):
            continue
        snapshot.update(first_symbol_sample=frame['first_symbol_sample'],
                        carrier_offset_hz=frame['carrier_offset_hz'], crc_valid=True)
        snapshots.append(snapshot)
    report.update(format='EXPERIMENTAL_ATM1_RF', ccsds=False, telemetry=snapshots,
                  valid_telemetry_count=len(snapshots),
                  repetition_note='Repeated identical snapshots are not independent events')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iq', type=Path, help='receiver raw int16 LE I0,Q0,... (12-bit sign extended)')
    parser.add_argument('--sample-rate', type=int, default=2_500_000)
    parser.add_argument('--symbol-rate', type=int, default=100_000)
    parser.add_argument('--offset', type=float, default=500_000,
                        help='DAC 90.5MHz minus receiver LO, e.g. +500kHz for 90MHz LO; hardware unverified')
    parser.add_argument('--search-hz', type=float, default=20_000)
    args = parser.parse_args(argv)
    report = decode_capture(args.iq.read_bytes(), sample_rate_hz=args.sample_rate,
                            symbol_rate=args.symbol_rate, expected_offset_hz=args.offset,
                            search_hz=args.search_hz)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['valid_telemetry_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
