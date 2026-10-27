"""Offline AD9643-specific PN9/other-channel checkerboard ILA validation.

Reference: ADI hdl_2016_r1 axi_ad9643_pnmon.v, not a generic 14-bit PN9
packer. Each sample carries the lower 14 bits of a 15-bit PN segment.
This checker does not open hardware, change capture files, or search formats
until one happens to fit. The ADC output mode is taken from verified readback.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re

REFERENCE_URL = "https://raw.githubusercontent.com/analogdevicesinc/hdl/hdl_2016_r1/library/axi_ad9643/axi_ad9643_pnmon.v"
REFERENCE_SHA256 = "b12552c1d93c5b0b665558586c7b66ebbf2d0ac6121778c53e8822c071f9e168"


def normalize_mask(output_mode):
    # ADI driver uses mode00 for its reference PN test and the reference
    # monitor XORs bit13. Mode bit0 adds the offset-binary/twos MSB change;
    # bit2 is the documented AD9643 test-pattern inversion quirk.
    if output_mode not in (0x00, 0x01, 0x04, 0x05):
        raise ValueError("PN check supports enabled binary/twos output modes 00/01/04/05 only")
    return (0 if output_mode & 1 else 0x2000) ^ (0x3fff if output_mode & 4 else 0)


def advance(state, count):
    """Shift MSB-first PN9: new bit=state[8]^state[4]; return generated bits."""
    output = 0
    for _ in range(count):
        bit = ((state >> 8) ^ (state >> 4)) & 1
        state = ((state << 1) | bit) & 0x1ff
        output = (output << 1) | bit
    return output


def next_normalized(word):
    return advance(word & 0x1ff, 15) & 0x3fff


def check_channel(raw, output_mode):
    mask = normalize_mask(output_mode)
    values = [word ^ mask for word in raw]
    examples = []
    errors = 0
    zero_states = sum((word & 0x1ff) == 0 for word in values)
    invalid_words = sum(any(((word >> bit) & 1) != (((word >> (bit+9)) ^ (word >> (bit+5))) & 1)
                            for bit in range(5)) for word in values)
    toggled = 0
    for index, (previous, current) in enumerate(zip(values, values[1:]), 1):
        expected = next_normalized(previous)
        toggled |= previous ^ current
        if expected != current:
            errors += 1
            if len(examples) < 8:
                examples.append({"index": index, "previous_raw": f"0x{raw[index-1]:04x}",
                                 "expected_raw": f"0x{expected ^ mask:04x}",
                                 "actual_raw": f"0x{raw[index]:04x}"})
    return {"samples": len(raw), "transitions": max(0, len(raw)-1),
            "normalization_xor": f"0x{mask:04x}", "mismatches": errors,
            "zero_lfsr_states": zero_states, "bit_toggle_mask": f"0x{toggled:04x}",
            "invalid_pn_words": invalid_words,
            "unique_codes": len(set(raw)), "first_raw": raw[:16], "mismatch_examples": examples,
            "pn9_match": len(raw) >= 512 and errors == 0 and zero_states == 0 and invalid_words == 0 and toggled == 0x3fff}


def parse_number(text, radix, width):
    if text is None:
        raise ValueError("missing CSV cell")
    token = text.strip().replace("_", "")
    patterns = {"HEX": (r"(?:0[xX])?[0-9a-fA-F]+", 16), "BIN": (r"[01]+", 2),
                "UNSIGNED": (r"[0-9]+", 10)}
    if radix not in patterns:
        raise ValueError(f"unsupported radix {radix!r}; unsigned raw probes required")
    pattern, base = patterns[radix]
    if not re.fullmatch(pattern, token):
        raise ValueError(f"unknown/X/Z/invalid CSV value: {text!r}")
    value = int(token, base)
    if not 0 <= value < 1 << width:
        raise ValueError(f"value outside {width}-bit unsigned width")
    return value


def read_vectors(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        def column(fragment):
            found = [name for name in columns if fragment in name]
            if len(found) != 1:
                raise ValueError(f"expected one {fragment} column, got {found}")
            return found[0]
        words = column("captured_words")
        counter = column("vector_count")
        status = column("status")
        diag = column("diagnostic_snapshot")
        radix = next(reader, None)
        if not radix or radix.get(words) not in ("HEX", "BIN", "UNSIGNED"):
            raise ValueError("missing Vivado radix row")
        vectors, counters, statuses, diagnostics = [], [], [], []
        for lineno, row in enumerate(reader, 3):
            if None in row or any(row.get(name) is None for name in columns):
                raise ValueError(f"malformed CSV row {lineno}")
            value = parse_number(row[words], radix[words], 112)
            vectors.extend((value >> (14*k)) & 0x3fff for k in range(8))
            counters.append(parse_number(row[counter], radix[counter], 32))
            statuses.append(parse_number(row[status], radix[status], 8))
            diagnostics.append(parse_number(row[diag], radix[diag], 112))
    if len(counters) < 128:
        raise ValueError("need at least 128 vectors / 512 samples per channel")
    return vectors, counters, statuses, diagnostics


def analyze(path):
    vectors, counters, statuses, diagnostics = read_vectors(path)
    if len(set(diagnostics)) != 1:
        raise ValueError("diagnostic bundle changes during capture")
    diag = diagnostics[0]
    fields = [(diag >> (8*k)) & 255 for k in range(14)]
    ident, a_mode, b_mode, a_test, b_test, divide, phase, delay, a_index, b_index, error, passed, marker, variant = fields
    checks = {"id": ident == 0x82, "A_PN9": a_test & 0x8f == 0x06,
              "B_checker": b_test & 0x8f == 0x04, "divide_phase": divide & 0x3f == 0,
              "clock_phase": phase & 0xa0 == 0, "clock_delay": delay & 0x9f == 0,
              "A_index": a_index & 3 == 1, "B_index": b_index & 3 == 2,
              "all_reads_passed": error == 0 and passed == 10 and marker == 0xa1,
              "DDR125_variant": variant == 0x7d,
              "ready_entire_capture": set(statuses) == {0xdb}}
    # Mask reserved/open bits exactly as the configuration readback gate does.
    a_mode &= 0x17
    b_mode &= 0x17
    normalize_mask(a_mode)
    normalize_mask(b_mode)
    checks["contiguous_vector_counter"] = all(((b-a) & 0xffffffff) == 1 for a,b in zip(counters,counters[1:]))
    if not all(checks.values()):
        return {"pass": False, "reason": "capture provenance/readiness/counter check failed", "checks": checks,
                "diagnostic_hex": f"0x{diag:028x}", "source": str(path.resolve())}
    candidates = []
    for parity in (0, 1):
        a = vectors[parity::2]
        b = vectors[1-parity::2]
        pn = check_channel(a, a_mode)
        checker = set(b) == {0x1555, 0x2aaa} and all((x ^ y) == 0x3fff for x,y in zip(b,b[1:]))
        candidates.append({"A_raw_word_parity": parity, **pn, "B_checker_match": checker})
    matches = [c for c in candidates if c["pn9_match"] and c["B_checker_match"]]
    return {"source": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "pass": len(matches) == 1, "capture_rows": len(counters), "raw_words": len(vectors),
            "channel_A_parity": matches[0]["A_raw_word_parity"] if len(matches) == 1 else None,
            "checks": checks, "diagnostic_hex": f"0x{diag:028x}",
            "A_output_mode": f"0x{a_mode:02x}", "B_output_mode": f"0x{b_mode:02x}",
            "candidates": candidates, "reference": REFERENCE_URL, "reference_sha256": REFERENCE_SHA256,
            "nominal_adc_fs_hz": 125000000, "nominal_vector_fs_hz": 31250000, "rate_is_measured": False,
            "boundary": "Internal AD9643 PN9/checkerboard test only; no analog/RF, absolute frequency or normal-mode guarantee"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.capture)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["pass"] else 1)
