"""Pass generated IQ through an ideal sampling model and the existing C receiver.

This tests software compatibility only, without board/network access. Linear
interpolation is not a model of the actual DAC, ADC front end or RF level.
"""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

import telecontrol_waveform as tx

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "capture_analysis", ROOT / "board/z7addalite/tools/analyze_adc_capture.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def sampled_rf(iq, offset=0, invert=False, seed=0):
    count, fs = 131072, 31_250_000.0
    t = (np.arange(count) + offset) / fs
    position = (t * tx.FS) % len(iq)
    source = iq[:, 0].astype(float) + 1j * iq[:, 1].astype(float)
    source = np.concatenate((source, source[:1]))
    # Ideal100 MHz quadrature upconversion; 100.5 MHz aliases to6.75 MHz.
    envelope = np.interp(position, np.arange(len(source)), source)
    wave = np.real(envelope * np.exp(2j * np.pi * 100_000_000 * t))
    wave *= (-1 if invert else 1) * 3000 / np.max(abs(source))
    noise = np.random.default_rng(seed).normal(0, np.std(wave) / 10, count)
    return np.clip(np.rint(wave + noise + 137), -8192, 8191).astype("<i2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Output directory must be new")
    args.out.mkdir(parents=True)
    lib = analysis.load_receiver(args.library)
    rows = []
    vectors = [(100, 2450, 0), (120, 1000, 1), (2400, 2450, 7),
               (900, 1000, 80), (901, 1000, 81), (901, 1001, 82)]
    for v, command in enumerate(vectors):
        iq = tx.command_iq(*command)
        for k, (offset, invert) in enumerate(((0, False), (49499, True))):
            x = sampled_rf(iq, offset, invert, 100*v+k)
            got = analysis.analyze_samples(x, lib)
            expected = dict(version=1, rx_mhz=command[0], tx_mhz=command[1], seq=command[2])
            ok = got["valid_frame"] and got["command"] == expected
            rows.append(dict(name=f"command{v}_profile{k}", expected=expected, passed=ok, result=got))
            if v == 3 and k == 0:
                (args.out / "synthetic_adc_s16le.bin").write_bytes(x.tobytes())
    negatives = {
        "complex_tone": sampled_rf(tx.tone_iq()),
        "zero": np.zeros(131072, dtype=np.int16),
        "noise": np.rint(np.random.default_rng(123).normal(0, 900, 131072)).astype(np.int16),
        "invalid_format": np.full(131072, 10000, dtype=np.int16),
    }
    for name, x in negatives.items():
        got = analysis.analyze_samples(x, lib)
        ok = not got["valid_frame"]
        if name == "invalid_format":
            ok = ok and not got["decode_attempted"] and got["invalid_sign_extension"] == len(x)
        rows.append(dict(name=name, passed=ok, result=got))
    result = dict(scope="offline ideal model; no hardware or RF acceptance", tests=len(rows),
                  passed=sum(row["passed"] for row in rows), rows=rows)
    (args.out / "results.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    for row in rows:
        print("PASS" if row["passed"] else "FAIL", row["name"], row["result"]["command"])
    return 0 if result["passed"] == result["tests"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
