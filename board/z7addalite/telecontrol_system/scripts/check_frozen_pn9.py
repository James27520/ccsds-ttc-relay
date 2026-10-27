"""Verify and copy frozen historical/synthetic PN9 fixtures. No device I/O."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
source = root / "sim/pn9_fixtures"
manifest = json.loads((source / "pn9_fixture_manifest.json").read_text(encoding="utf-8"))
expected = {"pn9_synthetic.mem", "pn9_recurrence.mem", *(f"pn9_real_{i:02d}.mem" for i in range(3))}
assert {entry["path"] for entry in manifest["files"]} == expected
args.output.mkdir(parents=True, exist_ok=True)
for entry in manifest["files"]:
    path = source / entry["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], path.name
    shutil.copyfile(path, args.output / path.name)
shutil.copyfile(source / "pn9_fixture_manifest.json", args.output / "pn9_fixture_manifest.json")
print("PASS frozen PN9 fixtures: 5 SHA256 verified; historical capture replay, not a new measurement")
