"""Verify leased firmware source boundaries, placement and offline fault tests."""
import hashlib
import json
import re
import struct


def verify(out, base, pinned, package):
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    symbols = (out/"symbols.txt").read_text()
    source = (out/"src/main.c").read_text()
    dis = (out/"disassembly.txt").read_text()
    elf = (out/"relay_remote.elf").read_bytes()
    eh = struct.unpack_from("<16sHHIIIIIHHHHHH", elf)
    loads = [s for i in range(eh[10]) if (s := struct.unpack_from("<IIIIIIII",elf,eh[5]+i*eh[9]))[0]==1]
    def symbol(name):
        return int(re.search(r"^([0-9a-f]+)\s+\w\s+"+re.escape(name)+r"$",symbols,re.M)[1],16)
    def word(address):
        for _, offset, va, _, fs, *_ in loads:
            if va<=address and address+4<=va+fs:
                return struct.unpack_from("<I",elf,offset+address-va)[0]
        raise ValueError("MMU address not file-backed")
    mmu = symbol("MMUTable")
    main_dis = dis.split("<main>:",1)[1].split("\n\n",1)[0]
    ddr = (base/"include/xparameters.h").read_text()
    low = int(re.search(r"#define XPAR_PS7_DDR_0_S_AXI_BASEADDR (0x[0-9A-Fa-f]+)",ddr)[1],16)
    high = int(re.search(r"#define XPAR_PS7_DDR_0_S_AXI_HIGHADDR (0x[0-9A-Fa-f]+)",ddr)[1],16)
    # Reconstruct exact intended main transformation independently from the
    # recorded artifact: all other existing sources remain byte-for-byte fixed.
    unchanged = [n for n in pinned["patched_sources_sha256"] if n!="main.c"]
    udp = (out/"src/relay_remote_udp.h").read_text()
    board = (out/"src/relay_remote_board.h").read_text()
    tests = {p.name:p.read_text() for p in (out/"tests").glob("*_results.txt")}
    checks = dict(
        fixed_rebuild_all_checks_pass=all(json.loads((out/"fixed_reference/offline_verification.json").read_text())["checks"].values()),
        existing_non_main_sources_unchanged=all(sha(out/"src"/n)==pinned["patched_sources_sha256"][n] for n in unchanged),
        new_headers_match_package=all(sha(out/"src"/p.name)==sha(p) for p in package.glob("*.h")),
        entry_0x04800000=eh[4]==0x04800000,
        all_loads_within_window=bool(loads) and all(0x04800000<=s[2] and s[2]+s[5]<=0x04c00000 and s[2]==s[3] for s in loads),
        disjoint_from_fixed_load_window=all(s[2]+s[5]<=0x04000000 or s[2]>=0x04400000 for s in loads),
        symbols_in_window=all(0x04800000<=symbol(n)<0x04c00000 for n in (
            "_vector_table","_boot","main","MMUTable","__bss_start","__bss_end","_heap_start","_heap_end","_stack_end","__undef_stack")),
        mmu_aligned=mmu%16384==0,
        identity_mappings_cover_image=all((word(mmu+i*4)&3)==2 and (word(mmu+i*4)&0xfff00000)==i<<20 for i in range(0x48,0x4c)),
        ddr_covers_image=low<=0x04800000 and high>=0x04bfffff,
        first_main_mmio_mute=bool(re.search(r"mov\s+r2, #2[\s\S]*?str\s+r2, \[r3, #16\][\s\S]*?<Xil_ICacheEnable>",main_dis)),
        startup_safe_levels=all(f"ad9361_set_tx_attenuation(ad9361_phy, {ch}, 89000)" in source for ch in (0,1)),
        pp_defaults_tx1_rx0=bool(re.search(r"1,\s*//pp_tx_swap_enable",source) and re.search(r"0,\s*//pp_rx_swap_enable",source)),
        legacy_packet_control_intact=all(sha(out/"src"/n)==pinned["base_sources_sha256"][n] for n in ("relay_rf_packet.h","relay_rf_control.h","relay_udp.h")),
        new_udp_selected='#include "relay_remote_udp.h"' in source and '#include "relay_udp.h"' not in source,
        bounded_main_poll=source.count("remote_tick(&remote_board);")==3 and "        remote_cli_poll();" in source and "cli_poll();" not in source.replace("remote_cli_poll();", ""),
        bounded_uart="unsigned budget=16;" in board and "while(budget-- &&" in board and "        cli_exec(" not in board,
        legacy_guarded="remote_board_legacy(&cmd)" in udp and "n==RELAY_RF_PACKET_SIZE && remote_u16(bytes)==0x0101u" in udp,
        udp_symbols_linked=all(re.search(r"\b"+n+r"\b",symbols) for n in ("udp_new","udp_bind","udp_recv","udp_sendto")),
        remote_native_groups_passed=tests.get("test_remote_results.txt", "").count("PASS:")>=12,
        board_native_groups_passed=tests.get("test_board_results.txt", "").count("PASS:")>=4,
        baseline_elf_unchanged=sha(base/"relay_udp.elf")==pinned["base_elf_sha256"],
    )
    result = dict(hardware_tested=False,checks=checks,elf_sha256=sha(out/"relay_remote.elf"),
        mmu_table=hex(mmu),stack_top=hex(symbol("__undef_stack")),ddr_bounds=[hex(low),hex(high)],
        load_segments=[dict(virtual=hex(s[2]),physical=hex(s[3]),file_size=s[4],memory_size=s[5],flags=s[6],
            payload_sha256=hashlib.sha256(elf[s[1]:s[1]+s[4]]).hexdigest()) for s in loads],
        placement_scope="Offline known DDR identity map only; not a warm-load safety guarantee",
        warnings=[line for p in [*(out/"obj").glob("*.log"),out/"link.log"] for line in p.read_text().splitlines() if "warning:" in line])
    (out/"offline_verification.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    if not all(checks.values()):
        raise RuntimeError("Offline verification failed: "+str(checks))
    print("PASS:",len(checks),"remote source/placement/fault-test checks")
    return result
