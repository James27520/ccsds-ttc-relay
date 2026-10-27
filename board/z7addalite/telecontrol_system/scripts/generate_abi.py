"""Generate both languages from the frozen ABI; does not assign BD addresses."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[1]
source = root / "abi" / "capture_abi.json"
abi = json.loads(source.read_text(encoding="utf-8"))
sha = hashlib.sha256(source.read_bytes()).hexdigest()
definitions = []
for reg in abi["registers"]:
    definitions.append(("TC_REG_" + reg["name"], int(reg["offset"], 0)))
for name, value in abi["constants"].items():
    definitions.append(("TC_" + name, int(value, 0)))
for group, items in abi["enums"].items():
    for name, value in items.items():
        definitions.append(("TC_" + group + "_" + name, value))
for name, value in abi["diagnostic_byte_index"].items():
    definitions.append(("TC_DIAG_BYTE_" + name, value))
assert len({name for name, _ in definitions}) == len(definitions)
assert len({int(r["offset"], 0) for r in abi["registers"]}) == len(abi["registers"])
assert all(int(r["offset"], 0) % 4 == 0 for r in abi["registers"])
header = ["/* Generated from capture_abi.json; SHA256 " + sha + " */",
          "#ifndef TELECONTROL_CAPTURE_ABI_H", "#define TELECONTROL_CAPTURE_ABI_H",
          "#include <stdint.h>"]
verilog = ["// Generated from capture_abi.json; SHA256 " + sha,
           "// Include inside the consuming module; constants are localparams."]
for name, value in definitions:
    header.append(f"#define {name} UINT32_C(0x{value:08X})")
    verilog.append(f"localparam [31:0] {name} = 32'h{value:08X};")
header.append("#endif")
(root / "abi" / "capture_abi.h").write_text("\n".join(header) + "\n", encoding="utf-8")
(root / "abi" / "capture_abi.vh").write_text("\n".join(verilog) + "\n", encoding="utf-8")
manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (source, root / "abi" / "capture_abi.h", root / "abi" / "capture_abi.vh")}
(root / "abi" / "sha256.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps(manifest, indent=2))
