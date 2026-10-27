"""Make offline training fixtures from independent ADI equations + real ILA CSV.

This never reads hardware. No fixture is fabricated and labeled as a capture.
"""
import argparse
import shutil
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from analyze_adc_pn9 import analyze, read_vectors

REFERENCE = ROOT / "reference/axi_ad9643_pnmon_2016_r1.v"
REFERENCE_SHA = "b12552c1d93c5b0b665558586c7b66ebbf2d0ac6121778c53e8822c071f9e168"


def reference_equations(reference):
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == REFERENCE_SHA
    body = reference.read_text().split("function [29:0] pn9;", 1)[1].split("endfunction", 1)[0]
    equations = [(int(index), [int(bit) for bit in re.findall(r"din\[\s*(\d+)\]", expression)])
                 for index, expression in re.findall(r"dout\[\s*(\d+)\]\s*=\s*([^;]+);", body)]
    assert sorted(index for index, _ in equations) == list(range(30))
    def pn30(value):
        result = 0
        for index, bits in equations:
            output = 0
            for bit in bits:
                output ^= value >> bit & 1
            result |= output << index
        return result
    return pn30


def packed(raw):
    return sum(word << (14*k) for k, word in enumerate(raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    parser.add_argument("--output", type=Path, default=ROOT / "sim/pn9_generated")
    parser.add_argument("--capture", type=Path, action="append", default=[],
                        help="optional original CSV; supply exactly three in 00/01/02 order")
    args = parser.parse_args()
    if args.capture and len(args.capture) != 3:
        parser.error("--capture requires exactly three CSV files")
    target = args.output
    target.mkdir(parents=True, exist_ok=True)
    oracle = reference_equations(args.reference)
    manifest = {"reference": "reference/axi_ad9643_pnmon_2016_r1.v", "reference_sha256": REFERENCE_SHA,
                "synthetic": [], "real_captures": []}
    # Independent oracle checks every nonzero PN state against DUT's function.
    cases = [(state << 14) | ((oracle(state) >> 15) & 0x3fff) for state in range(1, 512)]
    (target / "pn9_recurrence.mem").write_text("".join(f"{case:07x}\n" for case in cases))
    state, raw_a = 0x1ff, []
    for _ in range(4096*2):
        state = oracle(state)
        raw_a.extend([((state >> 15) & 0x3fff) ^ 0x3fff, (state & 0x3fff) ^ 0x3fff])
    vectors = []
    for row in range(4096):
        words = []
        for sample in range(4):
            words += [raw_a[row*4+sample], 0x1555 if sample % 2 == 0 else 0x2aaa]
        vectors.append(packed(words))
    output = target / "pn9_synthetic.mem"
    output.write_text("".join(f"{word:028x}\n" for word in vectors))
    manifest["synthetic"].append({"path": output.name, "vectors": len(vectors), "seed": "0x1ff",
                                  "oracle": "ADI expanded 30-bit equations, two 14-bit samples per 30 bits"})
    archived = json.loads((ROOT / "sim/pn9_fixtures/pn9_fixture_manifest.json").read_text(encoding="utf-8"))
    historical = [entry for entry in archived["files"] if entry["path"].startswith("pn9_real_")]
    for index, frozen_entry in enumerate(historical):
        entry = frozen_entry["provenance"]
        output = target / f"pn9_real_{index:02d}.mem"
        fixture = ROOT / "sim/pn9_fixtures" / frozen_entry["path"]
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == frozen_entry["sha256"]
        words = fixture.read_text(encoding="ascii").splitlines()
        assert len(words) == 4096 and all(re.fullmatch(r"[0-9a-f]{28}", word) for word in words)
        if args.capture:
            capture = args.capture[index]
            result = analyze(capture)
            assert result["pass"] and result["channel_A_parity"] == 0
            assert result["sha256"] == entry["source_csv_sha256"], "CSV provenance mismatch"
            raw, _, _, _ = read_vectors(capture)
            assert words == [f"{packed(raw[row:row+8]):028x}" for row in range(0, len(raw), 8)]
        shutil.copyfile(fixture, output)
        manifest["real_captures"].append({**entry, "path": output.name,
                                          "csv_rechecked": bool(args.capture)})
    for path in sorted(target.glob("*.mem")):
        manifest.setdefault("fixtures", []).append({"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    (target / "pn9_fixture_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("PASS PN9 fixtures: 511 reference states, 4096 synthetic vectors, 3 x 4096 archived historical capture vectors (SHA verified)")


if __name__ == "__main__":
    main()
