"""Offline RAM firmware build. Rebuild/verify fixed first, then add leased UDP.

Uses only the immutable hash-pinned external UDP dependencies. No hardware I/O.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
FIXED = HERE.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    p = subprocess.run(list(map(str, command)), capture_output=True, text=True, errors="replace")
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError(f"Command failed: {log}")
    return p.stdout


def replace_exact(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Unexpected fixed source context: {old}")
    return source.replace(old, new)


def dual_board_source(source):
    source = source.replace("relay_set_mode(", "relay_dual_set_mode(")
    source = replace_exact(source, "(Xil_In32(R_RELAY_MODE)&3u)==mode ? 0 : -1",
                           "relay_dual_matches(mode) ? 0 : -1")
    return replace_exact(source, "v->mode=(uint8_t)(Xil_In32(R_RELAY_MODE)&3u);",
                         "v->mode=(uint8_t)(Xil_In32(R_RELAY_MODE)&3u);\n"
                         "    if(!relay_dual_matches(v->mode)) return -1;")


def use_fixed_reference(reference, fixed, base, pinned):
    """Verify runtime payloads and inputs, independently of ELF debug paths."""
    import struct
    verification = json.loads((reference/"offline_verification.json").read_text())
    image = (reference/"relay_fixed.elf").read_bytes()
    if not verification["checks"] or not all(verification["checks"].values()) or sha(reference/"relay_fixed.elf") != verification["elf_sha256"]:
        raise ValueError("Unverified fixed image")
    eh = struct.unpack_from("<16sHHIIIIIHHHHHH", image)
    segments = []
    for i in range(eh[10]):
        kind, offset, va, pa, fs, ms, flags, align = struct.unpack_from("<8I", image, eh[5]+i*eh[9])
        if kind == 1:
            segments.append([va, pa, fs, ms, flags, align, hashlib.sha256(image[offset:offset+fs]).hexdigest()])
    if segments != pinned["reference_load_segments"] or eh[4] != 0x04000000:
        raise ValueError("Fixed load payload mismatch")
    if {p.name for p in (reference/"src").iterdir()} != set(pinned["patched_sources_sha256"]):
        raise ValueError("Unexpected fixed source set")
    inputs = [(reference/"src"/n, h) for n,h in pinned["patched_sources_sha256"].items()]
    inputs += [(base/"obj"/n, h) for n,h in pinned["reused_objects_sha256"].items()]
    inputs += [(base/"relay_udp.elf", pinned["base_elf_sha256"]),
               (base/"lib/libxil.a", pinned["base_libxil_sha256"]),
               (base/"include/xparameters.h", pinned["base_xparameters_sha256"]),
               (FIXED/"relay_fixed.ld", pinned["linker_script_sha256"])]
    for path, digest in inputs:
        if sha(path) != digest:
            raise ValueError("Fixed input changed: "+str(path))
    shutil.copytree(reference/"src", fixed/"src")
    shutil.copy2(reference/"offline_verification.json", fixed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--host-cc", required=True, type=Path)
    parser.add_argument("--dual-path", action="store_true",
                        help="Use only with the six-line PL (CH2_CTRL at base+0x2c)")
    parser.add_argument("--fixed-reference", type=Path, help="Existing verified fixed build")
    args = parser.parse_args()
    base, out = args.base.resolve(), args.out.resolve()
    # A parent output would also be dangerous: never place the build around its
    # inputs. Existing/frozen paths are rejected, never deleted or overwritten.
    for protected in (base, FIXED):
        if out == protected or protected in out.parents or out in protected.parents:
            parser.error("Output must be disjoint from baseline and source package")
    if out.exists():
        parser.error("Output directory must be new")
    compiler = (args.compiler or Path(json.loads((base/"build_manifest.json").read_text())["gcc"])).resolve()
    if not compiler.is_file() or not args.host_cc.is_file():
        parser.error("Compiler does not exist")
    out.mkdir(parents=True)
    fixed = out / "fixed_reference"
    fixed_command = [sys.executable, "-B", FIXED/"rebuild.py", "--base", base,
                     "--out", fixed, "--compiler", compiler, "--host-cc", args.host_cc.resolve()]
    pinned = json.loads((FIXED/"baseline.json").read_text())
    if args.fixed_reference:
        ref = args.fixed_reference.resolve()
        if ref == out or ref in out.parents or out in ref.parents:
            parser.error("Reference and output must be disjoint")
        use_fixed_reference(ref, fixed, base, pinned)
    else:
        run(fixed_command, out/"fixed_rebuild.log")
    shutil.copytree(fixed/"src", out/"src")
    (out/"obj").mkdir(); (out/"tests").mkdir()
    for header in HERE.glob("*.h"):
        shutil.copy2(header, out/"src"/header.name)
    source = (out/"src/main.c").read_text(encoding="utf-8")
    if args.dual_path:
        shutil.copy2(HERE/"dual/relay_dual_mode.h", out/"src")
        board = out/"src/relay_remote_board.h"
        board.write_text(dual_board_source(board.read_text()), encoding="utf-8", newline="\n")
        source = replace_exact(source, '#include "relay_reg.h"',
            '#include "relay_reg.h"\n#include "relay_dual_mode.h"')
        # Keep the verified first MMIO store to CH1; immediately mute CH2 as well.
        source = source.replace('relay_set_mode(RELAY_MODE_MUTE);', 'relay_dual_set_mode(RELAY_MODE_MUTE);')
        source = replace_exact(source, 'relay_dual_set_mode(RELAY_MODE_MUTE);\n    Xil_ICacheEnable();',
            'relay_set_mode(RELAY_MODE_MUTE);\n    relay_dual_set_mode(RELAY_MODE_MUTE);\n    Xil_ICacheEnable();')
    source = replace_exact(source, '#include "relay_udp.h"', '#include "relay_remote_udp.h"')
    source = replace_exact(source,
        '    if (probe_ready && relay_udp_init() != 0) {',
        '    remote_board_init();\n    if (probe_ready && relay_udp_init() != 0) {')
    source = replace_exact(source,
        '    while (1) { cli_poll(); if (probe_ready) relay_udp_poll(); }',
        '    while (1) {\n'
        '        remote_tick(&remote_board);\n'
        '        remote_cli_poll();\n'
        '        remote_tick(&remote_board);\n'
        '        if (probe_ready) relay_udp_poll();\n'
        '        remote_tick(&remote_board);\n'
        '    }')
    source = replace_exact(source,
        'RELAY_DIAG UDP5005 v1 start MUTED txatt=89000mdB auto=0',
        'RELAY_REMOTE UDP5005 v1 start MUTED txatt=89000mdB lease_max_ms=300000')
    # Do not advertise legacy CLI write commands in the new image.
    source = replace_exact(source, '    cli_help();\n    cli_stat();',
        '    printf("REMOTE UART: status | stop | mode 2; leased UDP enables output\\r\\n");')
    (out/"src/main.c").write_text(source, encoding="utf-8", newline="\n")
    linker = replace_exact((FIXED/"relay_fixed.ld").read_text(),
        "ORIGIN = 0x04000000, LENGTH = 0x00400000",
        "ORIGIN = 0x04800000, LENGTH = 0x00400000")
    (out/"relay_remote.ld").write_text(linker, encoding="utf-8", newline="\n")
    flags = ["-mcpu=cortex-a9", "-mfpu=vfpv3", "-mfloat-abi=hard", "-O1", "-g", "-fcommon",
             "-ffunction-sections", "-fdata-sections", "-DPROCESSOR_LITTLE_ENDIAN", "-Wall",
             "-Wextra", "-Wno-unused-function", "-I"+str(out/"src"), "-I"+str(base/"include")]
    lw = base/"deps/ThirdParty/sw_services/lwip202/src"
    flags += ["-I"+str(base/"generated"), "-I"+str(lw/"lwip-2.0.2/src/include"),
              "-I"+str(lw/"contrib/ports/xilinx/include")]
    commands, objects = [], []
    for src in sorted((out/"src").glob("*.c")):
        obj = out/"obj"/(src.stem+".o")
        command = [compiler, *flags, "-c", src, "-o", obj]
        run(command, out/"obj"/(src.stem+".log")); commands.append(list(map(str, command))); objects.append(obj)
    reused = [base/"obj"/name for name in pinned["reused_objects_sha256"]]
    elf = out/"relay_remote.elf"
    link = [compiler, *flags, "-specs="+str(base/"Xilinx.spec"), "-Wl,-T,"+str(out/"relay_remote.ld"),
            "-Wl,-Map,"+str(out/"relay_remote.map"), "-Wl,--gc-sections", "-Wl,-u,_vector_table",
            "-o", elf, *objects, *reused, "-L"+str(base/"lib"),
            "-Wl,--start-group", "-lxil", "-lm", "-lc", "-lgcc", "-Wl,--end-group"]
    run(link, out/"link.log")
    for tool, options, output in [("readelf", ["-h", "-l"], "elf_layout.txt"),
                                   ("nm", ["-n"], "symbols.txt"),
                                   ("objdump", ["-d"], "disassembly.txt"), ("size", [], "size.txt")]:
        suffix = ".exe" if compiler.suffix.lower() == ".exe" else ""
        run([compiler.with_name("arm-none-eabi-"+tool+suffix), *options, elf], out/output)
    test_commands = []
    for test in sorted((HERE/"tests").glob("test_*.c")):
        executable = out/"tests"/(test.stem+".exe")
        native = [args.host_cc.resolve(), "-std=c11", "-Wall", "-Wextra", "-Werror",
                  *(["-DRELAY_DUAL_PATH"] if args.dual_path else []),
                  "-Wno-unused-function", "-I"+str(out/"src"), "-I"+str(HERE/"tests/mocks"), test, "-o", executable]
        run(native, out/"tests"/(test.stem+"_compile.log"))
        run([executable], out/"tests"/(test.stem+"_results.txt")); test_commands.append(list(map(str,native)))
    if sha(base/"relay_udp.elf") != pinned["base_elf_sha256"]:
        raise ValueError("Frozen baseline changed")
    manifest = dict(artifact="LDSDR leased remote forwarding v1", hardware_tested=False,
        base=str(base), output=str(out), elf_sha256=sha(elf), dual_path=args.dual_path,
        fixed_rebuild_command=None if args.fixed_reference else list(map(str,fixed_command)),
        fixed_reference=str(args.fixed_reference.resolve()) if args.fixed_reference else None,
        fixed_verification=json.loads((fixed/"offline_verification.json").read_text()),
        compile_commands=commands, link_command=list(map(str,link)), native_test_commands=test_commands,
        source_sha256={p.name:sha(p) for p in (out/"src").iterdir()},
        package_sha256={str(p.relative_to(HERE)):sha(p) for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts},
        link_base="0x04800000", link_limit_exclusive="0x04c00000",
        hardware_contract="Existing initialized PS/DDR/PL; no COM, JTAG, network or download during build",
        placement_scope="Offline range/MMU checks only; actual active TTBR/cache/IRQ must be checked before hardware loading",
        protocol="docs/remote-relay-control.md", baseline_elf_unchanged=True)
    (out/"build_manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    from verify import verify
    verify(out,base,pinned,HERE, dual_board_source if args.dual_path else None)
    print("BUILT",elf,"SHA256",sha(elf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
