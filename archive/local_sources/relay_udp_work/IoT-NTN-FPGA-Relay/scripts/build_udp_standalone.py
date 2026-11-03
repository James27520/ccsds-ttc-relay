"""Build the LDSDR UDP app with installed ARM GCC and the archived SDK BSP.

This is an explicit GEM0 software overlay for the existing LDSDR MIO wiring,
not a regenerated BSP/HDF. Initial hardware tests preserve the running PS/PL
configuration. Cold boot requires a matching PS initialization/FSBL.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "IoT-NTN-FPGA-Relay"
SOURCE_URL = "https://codeload.github.com/Xilinx/embeddedsw/zip/refs/tags/xilinx-v2018.3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path,
                        default=Path("D:/RelayTools/work/relay_udp2026"))
    parser.add_argument("--gcc", type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    candidates = sorted(Path("D:/STM32CubeIDE_1.16.1").glob(
        "**/tools/bin/arm-none-eabi-gcc.exe"))
    gcc = args.gcc or (candidates[0] if candidates else None)
    if not gcc or not gcc.exists():
        parser.error("ARM GCC missing; pass --gcc <arm-none-eabi-gcc.exe>")
    archive = build / "embeddedsw-xilinx-v2018.3.zip"
    if not archive.exists():
        print("Downloading Xilinx embeddedsw 2018.3 sources", flush=True)
        urllib.request.urlretrieve(SOURCE_URL, archive)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            rel = Path(*Path(name).parts[1:])
            if ".." in rel.parts:
                raise ValueError("Unsafe source archive member")
            if name.endswith("/") or not rel.as_posix().startswith((
                    "ThirdParty/sw_services/lwip202/",
                    "XilinxProcessorIPLib/drivers/emacps/")):
                continue
            dest = build / "deps" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                dest.write_bytes(z.read(name))
    app = build / "src"
    inc = build / "include"
    for src, dst in [(ROOT / "vendor_sdk/9361/src", app),
                     (ROOT / "vendor_sdk/9361_bsp/ps7_cortexa9_0/include", inc),
                     (ROOT / "vendor_sdk/9361_bsp/ps7_cortexa9_0/lib", build / "lib")]:
        shutil.copytree(src, dst, dirs_exist_ok=True)
    for src in (REPO / "ps").glob("relay_*.h"):
        shutil.copy2(src, app / src.name)
    text = (inc / "xparameters.h").read_text()
    overlay = """
/* LDSDR GEM0 overlay: MIO16..27 RGMII, MIO52..53 MDIO; IO PLL 1 GHz. */
#define XPAR_XEMACPS_NUM_INSTANCES 1
#define XPAR_XEMACPS_0_DEVICE_ID 0
#define XPAR_XEMACPS_0_BASEADDR 0xE000B000U
#define XPAR_XEMACPS_0_HIGHADDR 0xE000BFFFU
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_1000MBPS_DIV0 8
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_1000MBPS_DIV1 1
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_100MBPS_DIV0 8
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_100MBPS_DIV1 5
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_10MBPS_DIV0 8
#define XPAR_PS7_ETHERNET_0_ENET_SLCR_10MBPS_DIV1 50
"""
    at = text.rfind("#endif")
    (inc / "xparameters.h").write_text(text[:at] + overlay + text[at:])
    (inc / "xlwipconfig.h").write_text("""
#define XLWIP_CONFIG_INCLUDE_GEM 1
#define XLWIP_CONFIG_N_TX_DESC 64
#define XLWIP_CONFIG_N_RX_DESC 64
#define CONFIG_LINKSPEED_AUTODETECT 1
""")
    (inc / "lwipopts.h").write_text("""
#ifndef RELAY_LWIPOPTS_H
#define RELAY_LWIPOPTS_H
#define NO_SYS 1
#define SYS_LIGHTWEIGHT_PROT 1
#define LWIP_SOCKET 0
#define LWIP_NETCONN 0
#define LWIP_TIMERS 0
#define LWIP_TCP 0
#define LWIP_UDP 1
#define LWIP_IPV4 1
#define LWIP_IPV6 0
#define LWIP_DHCP 0
#define LWIP_AUTOIP 0
#define LWIP_DNS 0
#define LWIP_IGMP 0
#define LWIP_STATS 0
#define MEM_ALIGNMENT 32
#define MEM_SIZE (128 * 1024)
#define PBUF_POOL_SIZE 128
#define PBUF_POOL_BUFSIZE 1600
#define MEMP_NUM_UDP_PCB 4
#define ARP_QUEUEING 1
#define LWIP_NETIF_LINK_CALLBACK 1
#define CHECKSUM_GEN_IP 1
#define CHECKSUM_GEN_UDP 1
#define CHECKSUM_CHECK_IP 1
#define CHECKSUM_CHECK_UDP 1
#endif
""")
    generated = build / "generated"
    generated.mkdir(exist_ok=True)
    # Rebuild this BSP unit against the installed newlib: old xil_printf.o
    # references a ctype ABI symbol removed from modern ARM GNU libraries.
    shutil.copy2(ROOT / "vendor_sdk/9361_bsp/ps7_cortexa9_0/libsrc/standalone_v6_8/src/xil_printf.c",
                 generated / "xil_printf.c")
    (generated / "gem_config.c").write_text("""
#include "xemacps.h"
#include "netif/xtopology.h"
#include "xparameters.h"
XEmacPs_Config XEmacPs_ConfigTable[] = {{0, 0xE000B000U, 0}};
int xtopology_n_emacs = 1;
struct xtopology_t xtopology[] = {
    {0xE000B000U, xemac_type_emacps, 0, 0, XPAR_SCUGIC_0_CPU_BASEADDR, 54}
};
""")
    # Keep code/heap/stack away from the legacy JTAG mailbox at 0x003F0000.
    linker = (app / "lscript.ld").read_text()
    linker = linker.replace("ORIGIN = 0x100000, LENGTH = 0x1FF00000",
                            "ORIGIN = 0x01000000, LENGTH = 0x1F000000")
    linker = linker.replace("_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;",
                            "_STACK_SIZE = 0x10000;")
    linker = linker.replace("_HEAP_SIZE = DEFINED(_HEAP_SIZE) ? _HEAP_SIZE : 0x2000;",
                            "_HEAP_SIZE = 0x80000;")
    linker = linker.replace("_IRQ_STACK_SIZE = DEFINED(_IRQ_STACK_SIZE) ? _IRQ_STACK_SIZE : 1024;",
                            "_IRQ_STACK_SIZE = 0x2000;")
    (build / "udp.ld").write_text(linker)
    (build / "Xilinx.spec").write_text("*startfile:\ncrti%O%s crtbegin%O%s\n")
    lw = build / "deps/ThirdParty/sw_services/lwip202/src"
    core = lw / "lwip-2.0.2/src"
    port = lw / "contrib/ports/xilinx"
    emac = build / "deps/XilinxProcessorIPLib/drivers/emacps/src"
    # Match the IPv4 callback signature used by this lwIP 2.0.2 release.
    adapter = port / "netif/xemacpsif.c"
    contents = adapter.read_text()
    contents = contents.replace(
        "static err_t xemacpsif_output(struct netif *netif, struct pbuf *p,\n\t\tip_addr_t *ipaddr)",
        "static err_t xemacpsif_output(struct netif *netif, struct pbuf *p,\n\t\tconst ip_addr_t *ipaddr)")
    adapter.write_text(contents)
    cpu_header = port / "include/arch/cpu.h"
    contents = cpu_header.read_text()
    if "#undef BYTE_ORDER" not in contents:
        contents = contents.replace("#ifdef PROCESSOR_LITTLE_ENDIAN",
            "#ifdef BYTE_ORDER\n#undef BYTE_ORDER\n#endif\n\n#ifdef PROCESSOR_LITTLE_ENDIAN")
        cpu_header.write_text(contents)
    include_dirs = [inc, emac, core / "include", port / "include", app]
    flags = ["-mcpu=cortex-a9", "-mfpu=vfpv3", "-mfloat-abi=hard",
             "-O1", "-g", "-fcommon", "-ffunction-sections", "-fdata-sections",
             "-DPROCESSOR_LITTLE_ENDIAN", "-Wall", "-Wno-unused-function"]
    flags += ["-I" + str(p) for p in include_dirs]
    sources = list(app.glob("*.c")) + [p for p in emac.glob("*.c")
                                           if p.name != "xemacps_g.c"]
    sources += list((core / "core").glob("*.c"))
    sources += list((core / "core/ipv4").glob("*.c"))
    sources += [core / "netif/ethernet.c",
                port / "sys_arch_raw.c", port / "netif/xadapter.c",
                port / "netif/xpqueue.c", generated / "gem_config.c",
                generated / "xil_printf.c"]
    sources += list((port / "netif").glob("xemacpsif*.c"))
    objects = build / "obj"
    objects.mkdir(exist_ok=True)

    def compile_one(src):
        obj = objects / (src.stem + "_" + hashlib.sha1(
            str(src).encode()).hexdigest()[:8] + ".o")
        proc = subprocess.run([str(gcc), *flags, "-c", str(src), "-o", str(obj)],
                              capture_output=True, text=True, errors="replace")
        (objects / (obj.stem + ".log")).write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError(f"{src.name}:\n{proc.stdout}{proc.stderr}")
        return obj

    print(f"Building {len(sources)} C files with {gcc}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        objs = list(pool.map(compile_one, sources))
    elf = build / "relay_udp.elf"
    cmd = [str(gcc), *flags, "-specs=" + str(build / "Xilinx.spec"),
           "-Wl,-T," + str(build / "udp.ld"),
           "-Wl,-Map," + str(build / "relay_udp.map"), "-Wl,--gc-sections",
           "-Wl,-u,_vector_table", "-o", str(elf)]
    cmd += [str(p) for p in objs]
    cmd += ["-L" + str(build / "lib"), "-Wl,--start-group", "-lxil", "-lm",
            "-lc", "-lgcc", "-Wl,--end-group"]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    (build / "link.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(proc.stdout + proc.stderr)
    manifest = {"source_url": SOURCE_URL,
                "source_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "gcc": str(gcc), "elf": str(elf),
                "elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
                "source_adaptations": ["xil_printf rebuilt for current newlib",
                                       "IPv4 output callback const signature",
                                       "BYTE_ORDER redefinition guard"],
                "hardware_contract": "Existing LDSDR PL; GEM0 MIO16..27 and MDIO52..53 initialized before ELF"}
    (build / "build_manifest.json").write_text(json.dumps(manifest, indent=2))
    subprocess.run([str(gcc.with_name("arm-none-eabi-size.exe")), str(elf)], check=True)
    print("BUILT", elf, flush=True)


if __name__ == "__main__":
    main()
