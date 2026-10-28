"""Rebuild the small RX-IQ patch using an external, hash-pinned UDP build cache.

No hardware I/O. The baseline is read-only; all generated files go to --out.
This adapts the verified isolated build commands, not a standalone BSP builder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_hash(path, expected):
    if sha(path) != expected:
        raise ValueError(f"Baseline/package hash mismatch: {path}")


def apply_patch(root, patch):
    """Apply our exact unified hunks; no fuzzy matching, shell or Git writes."""
    lines = patch.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        old = re.fullmatch(r"--- a/src/([A-Za-z0-9_.]+)\n", lines[index])
        if not old or lines[index+1] != f"+++ b/src/{old[1]}\n":
            raise ValueError("Unexpected patch file header")
        path = root / "src" / old[1]
        original = path.read_text(encoding="utf-8").splitlines(keepends=True)
        output, position = [], 0
        index += 2
        while index < len(lines) and not lines[index].startswith("--- a/src/"):
            hunk = re.match(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", lines[index])
            if not hunk:
                raise ValueError("Unexpected patch hunk")
            start = int(hunk[1])-1
            if start < position:
                raise ValueError("Overlapping patch hunk")
            output.extend(original[position:start]); position = start; index += 1
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- a/src/")):
                operation, content = lines[index][0], lines[index][1:]
                if operation in " -":
                    if position >= len(original) or original[position] != content:
                        raise ValueError(f"Patch context mismatch: {path}:{position+1}")
                    position += 1
                if operation in " +":
                    output.append(content)
                elif operation != "-":
                    raise ValueError("Unsupported patch operation")
                index += 1
        output.extend(original[position:])
        path.write_text("".join(output), encoding="utf-8", newline="\n")


def run(command, log):
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    log.write_text(result.stdout+result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed; inspect {log}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="complete known UDP build cache")
    parser.add_argument("--out", required=True, type=Path, help="new output directory")
    parser.add_argument("--compiler", type=Path, help="ARM compiler; defaults to base build_manifest gcc")
    parser.add_argument("--host-cc", required=True, type=Path, help="native C compiler for offline mocks")
    args = parser.parse_args()
    base, out = args.base.resolve(), args.out.resolve()
    if out == base or base in out.parents or out == HERE or HERE in out.parents:
        parser.error("Output must be outside both baseline and source package")
    if out.exists():
        parser.error("Output directory must be new")
    pinned = json.loads((HERE/"baseline.json").read_text())
    require_hash(base/"relay_udp.elf", pinned["base_elf_sha256"])
    require_hash(base/"lib/libxil.a", pinned["base_libxil_sha256"])
    require_hash(base/"include/xparameters.h", pinned["base_xparameters_sha256"])
    for name, expected in pinned["base_sources_sha256"].items():
        require_hash(base/"src"/name, expected)
    for name, expected in pinned["reused_objects_sha256"].items():
        require_hash(base/"obj"/name, expected)
    require_hash(HERE/"relay_fixed.patch", pinned["patch_sha256"])
    require_hash(HERE/"relay_fixed.ld", pinned["linker_script_sha256"])
    for name, expected in pinned["headers_sha256"].items():
        require_hash(HERE/"headers"/name, expected)
    gcc = args.compiler or Path(json.loads((base/"build_manifest.json").read_text())["gcc"])
    gcc = gcc.resolve()
    if not gcc.is_file() or not args.host_cc.is_file():
        parser.error("Compiler path does not exist")
    out.mkdir(parents=True)
    for folder in ("src", "obj", "tests"):
        (out/folder).mkdir()
    for name in pinned["base_sources_sha256"]:
        shutil.copy2(base/"src"/name, out/"src"/name)
    apply_patch(out, (HERE/"relay_fixed.patch").read_text(encoding="utf-8"))
    for name in pinned["headers_sha256"]:
        shutil.copy2(HERE/"headers"/name, out/"src"/name)
    for name, expected in pinned["patched_sources_sha256"].items():
        require_hash(out/"src"/name, expected)
    shutil.copy2(HERE/"relay_fixed.ld", out/"relay_fixed.ld")
    # Same RF compile/link commands as the verified isolated fixed build.
    flags = ["-mcpu=cortex-a9", "-mfpu=vfpv3", "-mfloat-abi=hard", "-O1", "-g", "-fcommon",
             "-ffunction-sections", "-fdata-sections", "-DPROCESSOR_LITTLE_ENDIAN", "-Wall",
             "-Wextra", "-Wno-unused-function", "-I"+str(out/"src"), "-I"+str(base/"include")]
    lw = base/"deps/ThirdParty/sw_services/lwip202/src"
    flags += ["-I"+str(base/"generated"), "-I"+str(lw/"lwip-2.0.2/src/include"),
              "-I"+str(lw/"contrib/ports/xilinx/include")]
    commands, objects = [], []
    for src in sorted((out/"src").glob("*.c")):
        obj = out/"obj"/(src.stem+".o")
        command = [str(gcc), *flags, "-c", str(src), "-o", str(obj)]
        run(command, out/"obj"/(src.stem+".log"))
        commands.append(command); objects.append(obj)
    reused = [base/"obj"/name for name in pinned["reused_objects_sha256"]]
    elf = out/"relay_fixed.elf"
    link = [str(gcc), *flags, "-specs="+str(base/"Xilinx.spec"), "-Wl,-T,"+str(out/"relay_fixed.ld"),
            "-Wl,-Map,"+str(out/"relay_fixed.map"), "-Wl,--gc-sections", "-Wl,-u,_vector_table",
            "-o", str(elf), *map(str, objects+reused), "-L"+str(base/"lib"),
            "-Wl,--start-group", "-lxil", "-lm", "-lc", "-lgcc", "-Wl,--end-group"]
    run(link, out/"link.log")
    for tool, options, output in [("readelf", ["-h", "-l"], "elf_layout.txt"),
                                   ("nm", ["-n"], "symbols.txt"),
                                   ("objdump", ["-d"], "disassembly.txt"),
                                   ("size", [], "size.txt")]:
        suffix = ".exe" if gcc.suffix.lower() == ".exe" else ""
        run([str(gcc.with_name("arm-none-eabi-"+tool+suffix)), *options, str(elf)], out/output)
    native = [str(args.host_cc.resolve()), "-std=c11", "-Wall", "-Wextra", "-Werror",
              "-I"+str(out/"src"), str(HERE/"tests/test_iqswap.c"),
              "-o", str(out/"tests/test_iqswap.exe")]
    run(native, out/"tests/compile.log")
    run([str(out/"tests/test_iqswap.exe")], out/"tests/results.txt")
    require_hash(base/"relay_udp.elf", pinned["base_elf_sha256"])
    manifest = dict(artifact="LDSDR RX0/TX1 fixed default", hardware_tested=False,
                    base=str(base), output=str(out), elf_sha256=sha(elf),
                    reference_elf_sha256=pinned["reference_fixed_elf_sha256"],
                    reference_hash_matches=sha(elf)==pinned["reference_fixed_elf_sha256"],
                    hash_note="Absolute source paths in DWARF can change ELF byte hash; verify source/placement separately",
                    source_sha256={p.name:sha(p) for p in (out/"src").iterdir()},
                    baseline_elf_unchanged=True, compile_commands=commands, link_command=link,
                    native_test_command=native, linker_script_sha256=sha(out/"relay_fixed.ld"))
    (out/"build_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    from verify import verify
    verify(out, base, pinned)
    print("BUILT", elf, "SHA256", sha(elf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
