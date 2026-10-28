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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--host-cc", required=True, type=Path)
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
    run(fixed_command, out/"fixed_rebuild.log")
    shutil.copytree(fixed/"src", out/"src")
    (out/"obj").mkdir(); (out/"tests").mkdir()
    for header in HERE.glob("*.h"):
        shutil.copy2(header, out/"src"/header.name)
    source = (out/"src/main.c").read_text(encoding="utf-8")
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
    pinned = json.loads((FIXED/"baseline.json").read_text())
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
                  "-Wno-unused-function", "-I"+str(out/"src"), "-I"+str(HERE/"tests/mocks"), test, "-o", executable]
        run(native, out/"tests"/(test.stem+"_compile.log"))
        run([executable], out/"tests"/(test.stem+"_results.txt")); test_commands.append(list(map(str,native)))
    if sha(base/"relay_udp.elf") != pinned["base_elf_sha256"]:
        raise ValueError("Frozen baseline changed")
    manifest = dict(artifact="LDSDR leased remote forwarding v1", hardware_tested=False,
        base=str(base), output=str(out), elf_sha256=sha(elf), fixed_rebuild_command=list(map(str,fixed_command)),
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
    verify(out,base,pinned,HERE)
    print("BUILT",elf,"SHA256",sha(elf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
