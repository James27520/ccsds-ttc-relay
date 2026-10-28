"""Generate offline V2 reference IQ; no hardware or transmission operations."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ccsds"))
from ccsds_tm_tx import build_cadu, crc16, srrc

FS = 2_500_000
SYMBOL_RATE = 100_000
SPS = FS // SYMBOL_RATE
BETA = 0.35
SPAN = 8
OFFSET_HZ = 500_000
FRAME_SAMPLES = 160 * SPS
OPERATIONS = {'frequency': 0x01, 'enable': 0x21, 'stop': 0x22, 'status': 0x23}


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


def build_body(rx, tx, seq, operation='frequency'):
    """Return the eight-byte V2 body, including big-endian CRC16."""
    rx = _integer(rx, 70, 6000, "rx")
    tx = _integer(tx, 70, 6000, "tx")
    seq = _integer(seq, 0, 255, "seq")
    if operation not in OPERATIONS:
        raise ValueError('Unknown telecontrol operation')
    body = struct.pack("<BHHB", OPERATIONS[operation], rx, tx, seq)
    return body + struct.pack(">H", crc16(body))


def _quantize(signal, amplitude):
    amplitude = _amplitude(amplitude)
    signal = signal / np.max(np.abs(signal)) * amplitude
    return np.rint(np.column_stack((signal.real, signal.imag)) * 32767).astype("<i2")


def command_iq(rx, tx, seq, amplitude=0.1, operation='frequency'):
    """Return one periodically shaped command frame as (4000, 2) int16 I/Q."""
    bits, _ = build_cadu(build_body(rx, tx, seq, operation), randomize_data=True)
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


def make_manifest(mode, iq, amplitude, rx=None, tx=None, seq=None, operation='frequency'):
    raw = iq.astype("<i2", copy=False).tobytes(order="C")
    body = build_body(rx, tx, seq, operation) if mode == "cmd" else None
    bits = build_cadu(body)[0] if body is not None else None
    return {
        "source": "OFFLINE_REFERENCE", "mode": mode, "operation": operation,
        "sample_rate_hz": FS, "symbol_rate_sym_s": SYMBOL_RATE,
        "srrc_beta": BETA, "srrc_span_symbols": SPAN,
        "complex_offset_hz": OFFSET_HZ,
        "nominal_carrier": {"lo_hz": 100_000_000, "center_hz": 100_500_000,
                            "note": "Nominal convention only; board support is not established."},
        "amplitude": _amplitude(amplitude),
        "amplitude_units": "normalized complex peak; int16 scale 32767; not RF power",
        "rx_mhz": rx, "tx_mhz": tx, "seq": seq,
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
    parser.add_argument("--seq", type=int)
    parser.add_argument("--amplitude", type=float, default=0.1)
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    args = parser.parse_args(argv)
    try:
        _amplitude(args.amplitude)
        if args.mode == "cmd":
            if any(x is None for x in (args.rx, args.tx, args.seq)):
                raise ValueError("cmd requires --rx, --tx and --seq")
            iq = command_iq(args.rx, args.tx, args.seq, args.amplitude)
        else:
            if any(x is not None for x in (args.rx, args.tx, args.seq)):
                raise ValueError("tone does not accept --rx, --tx or --seq")
            iq = tone_iq(args.amplitude)
        manifest = make_manifest(args.mode, iq, args.amplitude, args.rx, args.tx, args.seq)
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
