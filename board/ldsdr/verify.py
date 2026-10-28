"""Verify rebuilt source hashes, linked placement and native fault-test output."""
import hashlib
import json
import re
import struct


def verify(out, base, pinned):
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    symbols = (out/"symbols.txt").read_text()
    layout = (out/"elf_layout.txt").read_text()
    dis = (out/"disassembly.txt").read_text()
    source = (out/"src/main.c").read_text()
    elf = (out/"relay_fixed.elf").read_bytes()
    eh = struct.unpack_from("<16sHHIIIIIHHHHHH", elf)
    segments = [struct.unpack_from("<IIIIIIII", elf, eh[5]+i*eh[9]) for i in range(eh[10])]
    loads = [s for s in segments if s[0] == 1]
    def symbol(name):
        return int(re.search(r"^([0-9a-f]+)\s+\w\s+"+re.escape(name)+r"$", symbols, re.M)[1], 16)
    def word(address):
        for typ, offset, va, pa, fs, ms, flags, align in loads:
            if va <= address and address+4 <= va+fs:
                return struct.unpack_from("<I", elf, offset+address-va)[0]
        raise ValueError("MMU address not file-backed")
    mmu = symbol("MMUTable")
    ddr = (base/"include/xparameters.h").read_text()
    low = int(re.search(r"#define XPAR_PS7_DDR_0_S_AXI_BASEADDR (0x[0-9A-Fa-f]+)", ddr)[1], 16)
    high = int(re.search(r"#define XPAR_PS7_DDR_0_S_AXI_HIGHADDR (0x[0-9A-Fa-f]+)", ddr)[1], 16)
    main_dis = dis.split("<main>:", 1)[1].split("\n\n", 1)[0]
    checks = dict(
        runtime_load_payloads_match_fixed=[list((s[2],s[3],s[4],s[5],s[6],s[7],hashlib.sha256(elf[s[1]:s[1]+s[4]]).hexdigest())) for s in loads]==pinned["reference_load_segments"],
        sources_match_verified_fixed=all(sha(out/"src"/n)==h for n,h in pinned["patched_sources_sha256"].items()),
        entry_0x04000000=eh[4]==0x04000000,
        all_loads_within_window=bool(loads) and all(0x04000000<=s[2] and s[2]+s[5]<=0x04400000 and s[2]==s[3] for s in loads),
        text_mmu_bss_heap_stacks_in_window=all(0x04000000<=symbol(n)<0x04400000 for n in (
            "_vector_table", "_boot", "main", "MMUTable", "__bss_start", "__bss_end", "_heap_start", "_heap_end", "_stack_end", "__undef_stack")),
        ddr_covers_image=low<=0x04000000 and high>=0x043fffff,
        identity_mappings_cover_image=all((word(mmu+i*4)&3)==2 and (word(mmu+i*4)&0xfff00000)==i<<20 for i in range(0x40,0x44)),
        first_main_mmio_mute=bool(re.search(r"mov\s+r2, #2[\s\S]*?str\s+r2, \[r3, #16\][\s\S]*?<Xil_ICacheEnable>", main_dis)),
        startup_tx89=all(f"ad9361_set_tx_attenuation(ad9361_phy, {ch}, 89000)" in source for ch in (0,1)),
        pp_defaults_tx1_rx0=bool(re.search(r"1,\s*//pp_tx_swap_enable",source) and re.search(r"0,\s*//pp_rx_swap_enable",source)),
        no_unknown_phy_or_ch2_writes="AXI_REG_WRITE(PHY_MODE" not in source and "AXI_REG_WRITE(I_DELAY_EN" not in source,
        udp_handler_packet_control_unchanged=all(sha(out/"src"/n)==pinned["base_sources_sha256"][n] for n in ("relay_udp.h","relay_rf_packet.h","relay_rf_control.h")),
        udp_symbols_linked=all(re.search(r"\b"+n+r"\b",symbols) for n in ("udp_new","udp_bind","udp_recv","udp_sendto")),
        udp_poll_kept="while (1) { cli_poll(); if (probe_ready) relay_udp_poll(); }" in source,
        native_fault_groups_passed=(out/"tests/results.txt").read_text().count("PASS:")==6,
        baseline_elf_unchanged=sha(base/"relay_udp.elf")==pinned["base_elf_sha256"],
    )
    result = dict(hardware_tested=False, checks=checks, elf_sha256=sha(out/"relay_fixed.elf"),
                  mmu_table=hex(mmu), ddr_bounds=[hex(low),hex(high)],
                  placement_scope="Known DDR/identity mapping verified offline; actual active TTBR/cache/IRQ must be checked separately",
                  warnings=[line for p in list((out/"obj").glob("*.log"))+[out/"link.log"] for line in p.read_text().splitlines() if "warning:" in line])
    (out/"offline_verification.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    if not all(checks.values()):
        raise RuntimeError("Offline verification failed: "+str(checks))
    print("PASS:",len(checks),"source/layout checks and six native fault groups")
    return result
