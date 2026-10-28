"""Decode actual receiver IQ carrying experimental ATM1 binary telemetry.

AAAA | 96 | ATM1 payload | CCITT-FALSE(payload), MSB first; NOT complete
CCSDS. This offline tool never connects to a radio or transmits. IQ must be
actual sign-extended 12-bit complex receiver samples, not a TX manifest.
Sequence/uptime reset at PS boot; no unique boot ID or authentication exists.
"""
import argparse
import hashlib
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


def decode_capture_windows(raw, *, sample_rate_hz=2_500_000, symbol_rate=100_000,
                           expected_offset_hz=500_000, search_hz=20_000):
    """Search a finite receive record without knowing the sent snapshot.

    Half-overlapping windows avoid estimating one carrier across a long quiet
    interval. Matching physical frames in adjacent windows are merged within
    one symbol of timing uncertainty; repeated frames in a burst remain frames.
    All returned sample positions refer to the original IQ file.
    """
    import numpy as np
    if not raw or len(raw) % 4 or len(raw) > 64*1024*1024:
        raise ValueError('IQ file must contain complete I/Q pairs, up to 64 MiB')
    sps = phy._rates(sample_rate_hz, symbol_rate)
    iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2)
    if len(iq) < sps*48 or iq.min() < -2048 or iq.max() > 2047:
        raise ValueError('At least 48 symbols of sign-extended 12-bit I/Q required')
    width = max(65536, 2*FRAME_BYTES*8*sps + 2*phy.SPAN*sps)
    width = min(width, len(iq))
    starts = list(range(0, len(iq)-width+1, max(1, width//2)))
    if starts[-1] != len(iq)-width:
        starts.append(len(iq)-width)
    frames, windows = [], []
    for start in starts:
        report = decode_capture(raw[start*4:(start+width)*4],
                                sample_rate_hz=sample_rate_hz, symbol_rate=symbol_rate,
                                expected_offset_hz=expected_offset_hz, search_hz=search_hz)
        windows.append(dict(start_sample=start, samples=width,
                            valid_telemetry_count=report['valid_telemetry_count'],
                            carrier_offset_hz=report['carrier_offset_hz'],
                            rms_codes=report['rms_codes']))
        for frame in report['frames']:
            frame = dict(frame)
            frame['first_symbol_sample'] += start
            frame['sample_end_exclusive'] += start
            frame['window_start_sample'] = start
            if not any(old['payload_hex'] == frame['payload_hex'] and
                       abs(old['first_symbol_sample']-frame['first_symbol_sample']) <= sps
                       for old in frames):
                frames.append(frame)
    frames.sort(key=lambda f: f['first_symbol_sample'])
    snapshots, unique = [], set()
    for frame in frames:
        try:
            payload = bytes.fromhex(frame['payload_hex'])
            snapshot = parse_frame(b'\xaa\xaa\x60'+payload+frame['crc16'].to_bytes(2, 'big'))
        except (ValueError, KeyError, OverflowError):
            continue
        snapshot.update(first_symbol_sample=frame['first_symbol_sample'],
                        carrier_offset_hz=frame['carrier_offset_hz'], crc_valid=True)
        snapshots.append(snapshot)
        unique.add(payload)  # Full bytes, not just a sequence that can reset.
    return dict(format='EXPERIMENTAL_ATM1_RF', ccsds=False, samples=len(iq), bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), sample_rate_hz=sample_rate_hz,
                symbol_rate=symbol_rate, expected_offset_hz=expected_offset_hz,
                clip_components=int(np.count_nonzero((iq == -2048) | (iq == 2047))),
                rms_codes=float(np.sqrt(np.mean(np.sum(iq.astype(float)**2, axis=1)))),
                frames=frames, telemetry=snapshots, valid_frame_count=len(frames),
                valid_telemetry_count=len(snapshots), unique_snapshot_count=len(unique),
                windows=windows, ber=None,
                repetition_note='Overlapping detections merged; identical snapshots are not independent events',
                carrier_estimator='per-window square law; no estimate is evidence without CRC frames')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('iq', type=Path, help='receiver raw int16 LE I0,Q0,... (12-bit sign extended)')
    parser.add_argument('--sample-rate', type=int, default=2_500_000)
    parser.add_argument('--symbol-rate', type=int, default=100_000)
    parser.add_argument('--offset', type=float, default=500_000,
                        help='DAC RF minus receiver LO, e.g. +500kHz for the verified 90.5MHz / 90MHz bench point')
    parser.add_argument('--search-hz', type=float, default=20_000)
    args = parser.parse_args(argv)
    report = decode_capture_windows(args.iq.read_bytes(), sample_rate_hz=args.sample_rate,
                            symbol_rate=args.symbol_rate, expected_offset_hz=args.offset,
                            search_hz=args.search_hz)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['valid_telemetry_count'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
