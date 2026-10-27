"""Analyze an int16 LE capture with the existing host C receiver; no device I/O.

The file itself cannot establish ADC_NORMAL provenance. This tool never submits
the decoded command to a board or authorizes automatic forwarding.
"""
import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path

import numpy as np


class Command(ct.Structure):
    _fields_ = [("version", ct.c_uint8), ("rx_mhz", ct.c_uint16),
                ("tx_mhz", ct.c_uint16), ("seq", ct.c_uint8)]


class Frame(ct.Structure):
    _fields_ = [("command", Command), ("body", ct.c_uint8 * 8),
                ("bit_offset", ct.c_size_t), ("asm_errors", ct.c_uint),
                ("inverted", ct.c_uint), ("path_metric", ct.c_uint),
                ("end_state", ct.c_uint)]


class Stats(ct.Structure):
    _fields_ = [("carrier_hz", ct.c_double), ("carrier_phase", ct.c_double),
                ("input_rms", ct.c_double), ("symbol_candidates", ct.c_size_t),
                ("timing_trials", ct.c_uint)]


def load_receiver(path):
    lib = ct.CDLL(str(Path(path).resolve()))
    lib.adda_receive.argtypes = [ct.POINTER(ct.c_int16), ct.c_size_t,
                                ct.POINTER(Frame), ct.POINTER(Stats)]
    lib.adda_receive.restype = ct.c_int
    return lib


def analyze_samples(samples, lib):
    x = np.asarray(samples)
    if x.ndim != 1 or x.dtype.kind != "i" or x.dtype.itemsize != 2:
        raise ValueError("Expected a one-dimensional signed int16 sample array")
    if not 65536 <= x.size <= 262144:
        raise ValueError("Receiver accepts 65536..262144 samples; baseline is131072")
    x = np.ascontiguousarray(x, dtype=np.int16)
    y = x.astype(np.float64)
    invalid = int(np.count_nonzero((x < -8192) | (x > 8191)))
    result = dict(source="OFFLINE_FILE; ADC provenance not established", samples=int(x.size),
                  sample_rate_hz=31250000, minimum=int(x.min()), maximum=int(x.max()),
                  mean=float(y.mean()), ac_rms=float(np.std(y)),
                  rail_samples=int(np.count_nonzero((x == -8192) | (x == 8191))),
                  invalid_sign_extension=invalid, decode_attempted=False, valid_frame=False,
                  command=None, hardware_command_sent=False)
    if invalid:
        return result
    frame, stats = Frame(), Stats()
    rc = lib.adda_receive(x.ctypes.data_as(ct.POINTER(ct.c_int16)), x.size,
                          ct.byref(frame), ct.byref(stats))
    if rc < 0:
        raise RuntimeError("C receiver failed: rc=" + str(rc))
    result.update(decode_attempted=True, decode_rc=rc, valid_frame=rc == 1,
                  square_law_carrier_hz=stats.carrier_hz,
                  timing_trials=stats.timing_trials)
    if rc == 1:
        result.update(command=dict(version=frame.command.version, rx_mhz=frame.command.rx_mhz,
                                   tx_mhz=frame.command.tx_mhz, seq=frame.command.seq),
                      body_hex=bytes(frame.body).hex(), asm_errors=frame.asm_errors,
                      inverted=frame.inverted, path_metric=frame.path_metric,
                      crc_valid=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--samples", required=True, type=Path)
    ap.add_argument("--library", required=True, type=Path,
                    help="host library built from the matching adda_receiver/demod/protocol sources")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.out.exists():
        ap.error("Result file already exists")
    size = args.samples.stat().st_size
    if size % 2 or not 131072 <= size <= 524288:
        ap.error("Expected65536..262144 little-endian int16 samples")
    raw = args.samples.read_bytes()
    result = analyze_samples(np.frombuffer(raw, dtype="<i2"), load_receiver(args.library))
    result.update(input_sha256=hashlib.sha256(raw).hexdigest(),
                  library_sha256=hashlib.sha256(args.library.read_bytes()).hexdigest())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if not result["invalid_sign_extension"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
