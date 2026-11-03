"""Build a separate opt-in LDSDR business Doppler ELF. No device access."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import struct
import re

HERE=Path(__file__).resolve().parent
CORE=HERE.parents[1]/'z7addalite/software/doppler'

def run(cmd,log):
    p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,encoding='utf-8',errors='replace')
    log.write_text(p.stdout+p.stderr,encoding='utf-8')
    if p.returncode: raise RuntimeError(str(log))

def replace(t,a,b):
    if t.count(a)!=1: raise ValueError('Unexpected baseline context: '+a)
    return t.replace(a,b)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',required=True,type=Path)
    ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--host-cc',required=True,type=Path)
    ap.add_argument('--compiler',type=Path)
    ap.add_argument('--reference',type=Path,help='Previously verified remote build; all source/ELF hashes checked before reuse')
    a=ap.parse_args(); out=a.out.resolve(); base=a.base.resolve()
    if out.exists() or any(out==p or p in out.parents or out in p.parents for p in (base,HERE.parents[2])):
        ap.error('Use a new external build directory, disjoint from inputs')
    out.mkdir(parents=True)
    ref=a.reference.resolve() if a.reference else out/'remote_reference'
    if a.reference:
        if ref==out or out in ref.parents or ref in out.parents: ap.error('Reference and output must be disjoint')
        m=json.loads((ref/'build_manifest.json').read_text())
        verification=json.loads((ref/'offline_verification.json').read_text())
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        if not all(verification['checks'].values()) or sha(ref/'relay_remote.elf')!=m['elf_sha256']:
            raise ValueError('Unverified or modified reference ELF')
        for name,h in m['source_sha256'].items():
            if sha(ref/'src'/name)!=h: raise ValueError('Reference source changed: '+name)
        for p in (HERE.parent/'remote_control').glob('*.h'):
            if sha(p)!=sha(ref/'src'/p.name): raise ValueError('Remote API changed: '+p.name)
        pins=json.loads((HERE.parent/'baseline.json').read_text())
        for p,h in [(base/'relay_udp.elf',pins['base_elf_sha256']),
                    (base/'lib/libxil.a',pins['base_libxil_sha256']),
                    (base/'include/xparameters.h',pins['base_xparameters_sha256']),
                    *[(base/'obj'/n,h) for n,h in pins['reused_objects_sha256'].items()]]:
            if sha(p)!=h: raise ValueError('Baseline dependency changed: '+str(p))
    else:
        run([sys.executable,HERE.parent/'remote_control/rebuild.py','--base',base,'--out',ref,'--host-cc',a.host_cc,
             *(['--compiler',a.compiler] if a.compiler else [])],out/'reference.log')
    shutil.copytree(ref/'src',out/'src'); (out/'obj').mkdir()
    for p in [HERE/'relay_doppler.c',HERE/'relay_doppler.h',HERE/'relay_doppler_board.h',CORE/'doppler.c',CORE/'doppler.h']:
        shutil.copy2(p,out/'src'/p.name)
    p=out/'src/relay_remote_board.h'; t=p.read_text(encoding='utf-8')
    t=replace(t,'static XTime remote_boot_ticks;',
        'static void rd_board_off(void);\nstatic void rd_board_cli(const char *);\nstatic XTime remote_boot_ticks;')
    t=replace(t,'(void)unused; relay_set_mode(mode);','(void)unused; relay_set_mode(mode);\n    if(mode==2) rd_board_off();')
    t=replace(t,'static char remote_cli_line[32];','static char remote_cli_line[192];')
    t=replace(t,'    } else printf("ERR REMOTE UART writes disabled; use leased UDP\\r\\n");',
        '    } else if(!strncmp(remote_cli_line,"dp ",3)) rd_board_cli(remote_cli_line);\n'
        '    else printf("ERR REMOTE UART writes disabled; use leased UDP\\r\\n");')
    p.write_text(t,encoding='utf-8',newline='\n')
    p=out/'src/main.c'; t=p.read_text(encoding='utf-8')
    t=replace(t,'#include "relay_remote_udp.h"','#include "relay_remote_udp.h"\n#include "relay_doppler_board.h"')
    t=replace(t,'    remote_board_init();','    remote_board_init();\n    rd_board_init();')
    t=replace(t,'        if (probe_ready) relay_udp_poll();','        if (probe_ready) relay_udp_poll();\n        rd_board_poll();')
    p.write_text(t,encoding='utf-8',newline='\n')
    m=json.loads((ref/'build_manifest.json').read_text())
    template=m['compile_commands'][0]; compiler=str(a.compiler.resolve()) if a.compiler else template[0]; flags=template[1:template.index('-c')]
    flags=[f.replace(str(ref/'src'),str(out/'src')) for f in flags]
    objects=[]; cmds=[]
    for p in sorted((out/'src').glob('*.c')):
        obj=out/'obj'/(p.stem+'.o'); cmd=[compiler,*flags,'-c',p,'-o',obj]
        run(cmd,out/'obj'/(p.stem+'.log')); objects.append(str(obj));cmds.append(list(map(str,cmd)))
    # Reuse the verified dependency/link contract, replace only rebuilt objects.
    link=[]
    for item in m['link_command']:
        if str(ref/'obj') in item: continue
        link.append(item.replace(str(ref),str(out)).replace('relay_remote.elf','relay_doppler.elf'))
    link[0]=compiler
    shutil.copy2(ref/'relay_remote.ld',out/'relay_remote.ld')
    link[link.index('-L'+str(base/'lib')):link.index('-L'+str(base/'lib'))]=objects
    run(link,out/'link.log')
    elf=out/'relay_doppler.elf'
    image=elf.read_bytes();eh=struct.unpack_from('<16sHHIIIIIHHHHHH',image)
    loads=[s for i in range(eh[10]) if (s:=struct.unpack_from('<IIIIIIII',image,eh[5]+i*eh[9]))[0]==1]
    if eh[4]!=0x04800000 or not loads or not all(0x04800000<=s[2] and s[2]+s[5]<=0x04c00000 and s[2]==s[3] for s in loads):
        raise ValueError('Candidate outside reserved DDR window')
    for tool,opts in [('size',[]),('readelf',['-h','-l']),('nm',['-n'])]:
        run([Path(compiler).with_name('arm-none-eabi-'+tool+'.exe'),*opts,elf],out/(tool+'.txt'))
    symbols=(out/'nm.txt').read_text()
    mmu=int(re.search(r'^([0-9a-f]+)\s+\w\s+MMUTable$',symbols,re.M)[1],16)
    def word(addr):
        for _,offset,va,_,fs,*_ in loads:
            if va<=addr and addr+4<=va+fs: return struct.unpack_from('<I',image,offset+addr-va)[0]
        raise ValueError('MMU entry not file backed')
    axi=word(mmu+0x43c*4)
    if mmu%16384 or axi&3!=2 or axi&0xfff00000!=0x43c00000 or axi&0x700c:
        raise ValueError('AXI window requires identity, strongly ordered/device memory')
    if not all(word(mmu+i*4)&3==2 and word(mmu+i*4)&0xfff00000==i<<20 for i in range(0x48,0x4c)):
        raise ValueError('Candidate DDR mapping mismatch')
    manifest=dict(hardware_tested=False,default_runtime='OFF',pl_required='DPQ1 v1 @ 0x43c10000',
        base_remote_verification=json.loads((ref/'offline_verification.json').read_text()),
        compile_commands=cmds,link_command=link,
        elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
        reference=str(ref),reference_binary_equivalence_claimed=False,
        load_ranges=[[hex(s[2]),hex(s[2]+s[5])] for s in loads],
        mmu_table=hex(mmu),axi_section_descriptor=hex(axi),
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'src').iterdir()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('BUILT',elf)

if __name__=='__main__': main()
