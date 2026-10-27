"""Generate deterministic synthetic ADC data for the A9 algorithm self-test.

This fixture is never an ADC capture and must never cause a UDP command.
The external V2 golden CADU is pulse-shaped by the existing TX reference.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=Path(__file__).resolve().parents[4] / "sw/ccsds/ccsds_tm_tx.py")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "generated")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("tx_reference", args.reference)
    tx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tx)
    cadu = "1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50"
    bits = np.unpackbits(np.frombuffer(bytes.fromhex(cadu), dtype=np.uint8))
    symbols = np.tile(1.0 - 2.0 * bits.astype(float), 9)
    up = np.zeros(len(symbols) * 25)
    up[::25] = symbols
    bb = np.convolve(up, tx.srrc(.35, 25, 8), "same")
    count = 131072
    n = np.arange(count)
    positions = (n + 107193) * (2.5e6 / 31.25e6)
    envelope = np.interp(positions, np.arange(len(bb)), bb)
    envelope *= 3000 / max(abs(bb))
    carrier = 6750000.0 + 17321.0
    signal = envelope * np.cos(2 * np.pi * carrier * n / 31.25e6 + 1.7)
    rms = np.sqrt(np.mean(signal ** 2))
    noise = np.random.default_rng(2).normal(0, rms / 10**(12 / 20), count)
    samples = np.clip(np.rint(signal + noise + 137), -8192, 8191).astype("<i2")
    args.output.mkdir(parents=True, exist_ok=True)
    binary = samples.tobytes()
    (args.output / "synthetic_adc_i16le.bin").write_bytes(binary)
    header = """#ifndef WAVEFORM_FIXTURE_H
#define WAVEFORM_FIXTURE_H
#include <stdint.h>
#define WAVEFORM_FIXTURE_COUNT 131072u
#define WAVEFORM_FIXTURE_RX_MHZ 100u
#define WAVEFORM_FIXTURE_TX_MHZ 2450u
#define WAVEFORM_FIXTURE_SEQ 0u
/* SYNTHETIC source: never forward its decoded command to the relay. */
extern const int16_t waveform_fixture[WAVEFORM_FIXTURE_COUNT];
#endif
"""
    (args.output / "waveform_fixture.h").write_text(header, encoding="ascii")
    with (args.output / "waveform_fixture.c").open("w", encoding="ascii") as f:
        f.write('/* Generated synthetic fixture; not measured ADC data. */\n')
        f.write('#include "waveform_fixture.h"\n')
        f.write('const int16_t waveform_fixture[WAVEFORM_FIXTURE_COUNT] = {\n')
        for i in range(0, count, 16):
            f.write("    " + ",".join(str(int(x)) for x in samples[i:i+16]) + ",\n")
        f.write("};\n")
    metadata = dict(source="synthetic", sample_count=count, sample_rate_hz=31250000,
                    carrier_hz=carrier, symbol_rate=100000, cadu=cadu,
                    expected=dict(rx_mhz=100, tx_mhz=2450, seq=0), snr_db=12,
                    adc_binary_sha256=hashlib.sha256(binary).hexdigest(),
                    tx_reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                    numpy_version=np.__version__, network_side_effects_allowed=False)
    (args.output / "manifest.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
