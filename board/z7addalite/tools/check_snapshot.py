"""Check a frozen PS DDR snapshot independently from the board C checker.

PN9/checker checks apply only to ADC internal training mode 0x14=0x05.
Normal samples are never inverted and are described without claiming reception.
The caller must bind the binary to its UART source/channel/epoch record.
"""
import argparse
import array
import hashlib
import json
from pathlib import Path
import sys


def analyze(data, kind):
    if len(data) != 262144:
        raise ValueError("Expected exactly 131072 little-endian signed 16-bit samples")
    samples = array.array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    invalid = sum(not -8192 <= x <= 8191 for x in samples)
    result = dict(kind=kind, samples=len(samples), invalid_sign_extension=invalid,
                  minimum=min(samples), maximum=max(samples), unique_codes=len(set(samples)),
                  first=list(samples[:8]), last=list(samples[-8:]),
                  sha256=hashlib.sha256(data).hexdigest())
    if kind == "pn9":
        # Independent 511-state successor table: AD9643 15 bits/sample, /4.
        successor = {}
        for seed in range(1, 512):
            state, word = seed, 0
            for _ in range(60):
                bit = ((state >> 8) ^ (state >> 4)) & 1
                state = ((state << 1) | bit) & 511
                word = ((word << 1) | bit) & 0x3fff
            successor[seed] = word
        normalized = [(s & 0x3fff) ^ 0x3fff for s in samples]
        bad_words = sum(any(((w >> i) & 1) != (((w >> (i+9)) ^ (w >> (i+5))) & 1)
                            for i in range(5)) for w in normalized)
        mismatches = sum(successor.get(a & 511) != b for a,b in zip(normalized,normalized[1:]))
        zero_states = sum((w & 511) == 0 for w in normalized)
        toggles = 0
        for a,b in zip(normalized,normalized[1:]):
            toggles |= a ^ b
        result.update(pn9_mismatches=mismatches, invalid_pn_words=bad_words,
                      zero_states=zero_states, toggle_mask=hex(toggles), step_bits=60)
        result["pass"] = invalid == mismatches == bad_words == zero_states == 0 and toggles == 0x3fff
    elif kind == "checker":
        raw = {x & 0x3fff for x in samples}
        result["pass"] = invalid == 0 and raw in ({0x1555}, {0x2aaa})
    else:
        result["pass"] = invalid == 0
        result["scope"] = "Sample format only; no external signal or decoded command proven"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--kind", choices=("pn9", "checker", "normal"), required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.binary.read_bytes(), args.kind)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text+"\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["pass"] else 1)
