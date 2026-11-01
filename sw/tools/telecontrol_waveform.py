"""Generate offline V2 reference IQ; no hardware or transmission operations."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

try:
    from .telecontrol_protocol import OPERATIONS, N256_ENCODING, wire_fields, frequency_fields
except ImportError:
    from telecontrol_protocol import OPERATIONS, N256_ENCODING, wire_fields, frequency_fields

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ccsds"))
from ccsds_tm_tx import build_cadu, crc16, srrc

FS = 2_500_000
SYMBOL_RATE = 100_000
SPS = FS // SYMBOL_RATE
BETA = 0.35
SPAN = 8
OFFSET_HZ = 500_000
FRAME_SAMPLES = 160 * SPS


def _integer(value, low, high, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{name} must be in {low}..{high}")
    return int(value)


def _amplitude(value):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("amplitude must satisfy 0 < amplitude <= 1")
    value = float(value)
    if not np.isfinite(value) or not 0 < value <= 1:
        raise ValueError("amplitude must satisfy 0 < amplitude <= 1")
    return value


def build_body(rx=None, tx=None, seq=None, operation='frequency', *,
               rx_hz=None, tx_hz=None, encoding=None):
    """Return the eight-byte V2 body, including big-endian CRC16."""
    if encoding is not None or rx_hz is not None or tx_hz is not None:
        if rx is not None or tx is not None:
            raise ValueError('Do not mix legacy MHz and exact Hz fields')
        requested = dict(rx_hz=rx_hz, tx_hz=tx_hz, air_seq=seq,
                         operation=operation, encoding=N256_ENCODING if encoding is None else encoding)
    else:
        requested = dict(rx_mhz=rx, tx_mhz=tx, air_seq=seq, operation=operation)
    version, rx_raw, tx_raw, seq = wire_fields(requested)
    body = struct.pack("<BHHB", version, rx_raw, tx_raw, seq)
    return body + struct.pack(">H", crc16(body))


def _quantize(signal, amplitude):
    amplitude = _amplitude(amplitude)
    signal = signal / np.max(np.abs(signal)) * amplitude
    return np.rint(np.column_stack((signal.real, signal.imag)) * 32767).astype("<i2")


def command_iq(rx=None, tx=None, seq=None, amplitude=0.1, operation='frequency', *,
               rx_hz=None, tx_hz=None, encoding=None):
    """Return one periodically shaped command frame as (4000, 2) int16 I/Q."""
    bits, _ = build_cadu(build_body(rx, tx, seq, operation, rx_hz=rx_hz,
                                  tx_hz=tx_hz, encoding=encoding), randomize_data=True)
    symbols = np.where(bits == 0, 1.0, -1.0)
    up = np.zeros(3 * FRAME_SAMPLES)
    up[::SPS] = np.tile(symbols, 3)
    shaped = np.convolve(up, srrc(BETA, SPS, span=SPAN), mode="same")
    bb = shaped[FRAME_SAMPLES:2 * FRAME_SAMPLES]
    phase = np.exp(2j * np.pi * OFFSET_HZ * np.arange(FRAME_SAMPLES) / FS)
    return _quantize(bb * phase, amplitude)


def tone_iq(amplitude=0.1):
    """Return one +500 kHz complex tone block as (4000, 2) int16 I/Q."""
    phase = np.exp(2j * np.pi * OFFSET_HZ * np.arange(FRAME_SAMPLES) / FS)
    return _quantize(phase, amplitude)


def make_manifest(mode, iq, amplitude, rx=None, tx=None, seq=None, operation='frequency', *,
                  rx_hz=None, tx_hz=None, encoding=None):
    raw = iq.astype("<i2", copy=False).tobytes(order="C")
    body = build_body(rx, tx, seq, operation, rx_hz=rx_hz, tx_hz=tx_hz,
                      encoding=encoding) if mode == "cmd" else None
    bits = build_cadu(body)[0] if body is not None else None
    frequencies = {'rx_mhz': rx, 'tx_mhz': tx}
    if body is not None and body[0] & 0x80:
        version, rx_raw, tx_raw, _ = struct.unpack('<BHHB', body[:6])
        frequencies = dict(frequency_fields(version, rx_raw, tx_raw), command_version=version)
    return {
        "source": "OFFLINE_REFERENCE", "mode": mode, "operation": operation,
        "sample_rate_hz": FS, "symbol_rate_sym_s": SYMBOL_RATE,
        "srrc_beta": BETA, "srrc_span_symbols": SPAN,
        "complex_offset_hz": OFFSET_HZ,
        "nominal_carrier": {"lo_hz": 100_000_000, "center_hz": 100_500_000,
                            "note": "Nominal convention only; board support is not established."},
        "amplitude": _amplitude(amplitude),
        "amplitude_units": "normalized complex peak; int16 scale 32767; not RF power",
        **frequencies, "seq": seq,
        "body_hex": body.hex() if body is not None else None,
        "frame_hex": np.packbits(bits).tobytes().hex() if bits is not None else None,
        "frame_bits": len(bits) if bits is not None else None,
        "complex_samples": len(iq), "byte_count": len(raw),
        "block_duration_seconds": len(iq) / FS,
        "dtype": "signed int16 little-endian", "channel_order": "I0,Q0,I1,Q1,...",
        "iq_file": "iq_s16le.bin", "sha256": hashlib.sha256(raw).hexdigest(),
        "shaping": "three repeated frames, center frame retained" if body else "complex exponential",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("cmd", "tone"))
    parser.add_argument("--rx", type=int)
    parser.add_argument("--tx", type=int)
    parser.add_argument("--rx-hz", type=int, help="n256 receiver LO in exact Hz")
    parser.add_argument("--tx-hz", type=int, help="n256 transmitter LO in exact Hz")
    parser.add_argument("--encoding", choices=(N256_ENCODING,))
    parser.add_argument("--operation", choices=tuple(OPERATIONS), default='frequency')
    parser.add_argument("--seq", type=int)
    parser.add_argument("--amplitude", type=float, default=0.1)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    args = parser.parse_args(argv)
    try:
        _amplitude(args.amplitude)
        frequency_args = dict(rx=args.rx, tx=args.tx, seq=args.seq, operation=args.operation,
                              rx_hz=args.rx_hz, tx_hz=args.tx_hz, encoding=args.encoding)
        if args.mode == "cmd":
            iq = command_iq(amplitude=args.amplitude, **frequency_args)
        else:
            if (any(x is not None for x in (args.rx, args.tx, args.seq, args.rx_hz,
                                           args.tx_hz, args.encoding)) or args.operation != 'frequency'):
                raise ValueError("tone does not accept command fields")
            iq = tone_iq(args.amplitude)
        manifest = make_manifest(args.mode, iq, args.amplitude, **frequency_args)
        args.out.mkdir(parents=True, exist_ok=False)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    (args.out / "iq_s16le.bin").write_bytes(iq.tobytes(order="C"))
    (args.out / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"OFFLINE_REFERENCE: {len(iq)} complex samples written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
