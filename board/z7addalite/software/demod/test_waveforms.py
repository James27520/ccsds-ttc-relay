"""Synthetic real-ADC tests, never device measurements or an RF calibration.

Uses the existing repository SRRC pulse shape and independently hardcoded V2
CADUs. Linear interpolation models a smooth transmitter envelope, not the ADDA
analog chain, clock jitter, or decimation noise folding. No network/device I/O.
"""
import ctypes as ct
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--reference", type=Path, default=HERE.parents[3] / "sw/ccsds/ccsds_tm_tx.py",
                    help="existing sw/ccsds/ccsds_tm_tx.py source")
parser.add_argument("--library", type=Path, default=HERE / "build/adda_receiver.dll")
parser.add_argument("--results", type=Path, default=HERE / "build/waveform_test_results.json")
args = parser.parse_args()
spec = importlib.util.spec_from_file_location("tx_reference", args.reference)
tx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tx)

GOLDEN = [
    (100, 2450, 0, "1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50"),
    (120, 1000, 1, "1acffc1dbcd902e425bf7178a92646027b434d99"),
    (2400, 2450, 7, "1acffc1dbcd90178796fe89c0b3894fb8771de0a"),
]


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


def waveform(bits, count, offset, cfo, phase, snr, seed, ppm=0, cyclic_block=False):
    # A source clock independent of the ADC clock; 25 samples/symbol at TX.
    source_symbols = np.tile(1.0 - 2.0 * bits.astype(float), 1 if cyclic_block else 9)
    up = np.zeros(len(source_symbols) * 25)
    up[::25] = source_symbols
    bb = np.convolve(up, tx.srrc(.35, 25, 8), "same")
    if cyclic_block:
        # The supplied transmitter generates one same-filtered block and loops
        # it; retain its boundary transients instead of hiding them in the model.
        bb = np.tile(bb, 9)
    positions = (np.arange(count) + offset + 100000) * (2.5e6 / 31.25e6) * (1 + ppm * 1e-6)
    env = np.interp(positions, np.arange(len(bb)), bb)
    env *= 3000 / max(abs(bb))
    n = np.arange(count)
    signal = env * np.cos(2 * np.pi * (6.75e6 + cfo) * n / 31.25e6 + phase)
    rms = np.sqrt(np.mean(signal ** 2))
    noise = np.random.default_rng(seed).normal(0, rms / (10 ** (snr / 20)), count)
    return np.clip(np.rint(signal + noise + 137), -8192, 8191).astype(np.int16)


def main():
    lib = ct.CDLL(str(args.library.resolve()))
    lib.adda_receive.argtypes = [ct.POINTER(ct.c_int16), ct.c_size_t,
                                 ct.POINTER(Frame), ct.POINTER(Stats)]
    lib.adda_receive.restype = ct.c_int
    rows = []

    def receive(name, x, expected, actual_fc=None):
        x = np.ascontiguousarray(x, dtype=np.int16)
        frame, stats = Frame(), Stats()
        start = time.perf_counter()
        rc = lib.adda_receive(x.ctypes.data_as(ct.POINTER(ct.c_int16)), len(x),
                              ct.byref(frame), ct.byref(stats))
        elapsed = (time.perf_counter() - start) * 1000
        recovered = (frame.command.rx_mhz, frame.command.tx_mhz, frame.command.seq) if rc == 1 else None
        passed = (rc == 1 and recovered == expected) if expected else rc == 0
        rows.append(dict(name=name, pass_=passed, rc=rc, expected=expected,
                         recovered=recovered, carrier_hz=stats.carrier_hz,
                         carrier_error_hz=None if actual_fc is None else stats.carrier_hz - actual_fc,
                         timing_trials=stats.timing_trials, host_ms=elapsed,
                         body=bytes(frame.body).hex() if rc == 1 else None))
        print(f"{'PASS' if passed else 'FAIL'} {name}: rc={rc}, fields={recovered}, fc={stats.carrier_hz:.2f}")

    profiles = [(0, .1, 0, 20, 0), (17321, 1.7, 7193, 12, 0),
                (-22123, -2.2, 29471, 8, 50), (31337, 2.9, 49499, 10, -50)]
    for v, (rx, freq, seq, hex_frame) in enumerate(GOLDEN):
        bits = np.unpackbits(np.frombuffer(bytes.fromhex(hex_frame), dtype=np.uint8))
        for p, (cfo, phase, offset, snr, ppm) in enumerate(profiles):
            for invert in (0, 1):
                x = waveform(bits, 131072, offset, cfo, phase + invert * np.pi,
                             snr, v * 100 + p * 2 + invert, ppm)
                receive(f"golden{v+1}_profile{p}_polarity{invert}", x, (rx, freq, seq), 6.75e6 + cfo)

    bits = np.unpackbits(np.frombuffer(bytes.fromhex(GOLDEN[0][3]), dtype=np.uint8))
    for timing in range(16):
        x = waveform(bits, 131072, timing * 312.5 / 16, -27311, .7,
                     8, 500 + timing, cyclic_block=True)
        receive(f"cyclic_block_timing{timing}", x, GOLDEN[0][:3], 6.75e6 - 27311)

    receive("all_zero", np.zeros(131072, dtype=np.int16), None)
    receive("constant", np.full(131072, 1234, dtype=np.int16), None)
    receive("noise", np.random.default_rng(82).normal(0, 1000, 131072).astype(np.int16), None)
    n = np.arange(131072)
    receive("unmodulated_tone", np.rint(2000*np.cos(2*np.pi*6.75e6*n/31.25e6)).astype(np.int16), None)

    # Invalid CRC still has a perfectly valid convolutionally coded waveform.
    body = bytes.fromhex("01640092090077aa")
    corrupt_bits, _ = tx.build_cadu(body, randomize_data=True)
    receive("bad_crc_waveform", waveform(corrupt_bits, 131072, 1234, 10000, .4, 20, 21), None)

    result = dict(kind="synthetic host C waveform tests, not hardware", tests=len(rows),
                  passed=sum(r["pass_"] for r in rows), rows=rows)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(json.dumps(result, indent=2), encoding="utf-8")
    assert result["passed"] == result["tests"], result


if __name__ == "__main__":
    main()
