"""Compile/run mocked negative tests against exact patched vendor functions.

No board, socket or network access. --bsp is the generated patched BSP root.
The tests inject absent/unsupported PHYs, MDIO errors, stuck reset and resource
failures, and verify recovery. Delays are virtual; hardware timing is separate.
"""
import argparse, hashlib, json, os, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bsp',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--host-bin',type=Path,default=os.environ.get('ADDA_HOST_GCC_BIN'))
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
gcc=str(a.host_bin/'gcc.exe') if a.host_bin else shutil.which('gcc')
if not gcc:raise SystemExit('Set --host-bin / ADDA_HOST_GCC_BIN or put gcc on PATH')
env=os.environ.copy();env['PATH']=str(Path(gcc).parent)+os.pathsep+env['PATH']
lib=a.bsp.resolve()/'ps7_cortexa9_0/libsrc';port=lib/'lwip202_v1_2/src/contrib/ports/xilinx/netif'

def function(path,signature):
    text=path.read_text();start=text.index(signature);begin=text.index('{',start);depth=0
    for end in range(begin,len(text)):
        if text[end]=='{':depth+=1
        elif text[end]=='}':
            depth-=1
            if depth==0:return text[start:end+1]+'\n'
    raise ValueError(signature)

groups={
 'phy':[(port/'xemacpsif_physpeed.c',s) for s in ['void detect_phy(', 'static int adda_phy_read(', 'static u32_t adda_phy_current_speed(', 'u32_t phy_current_speed_emacps(', 'static u32_t get_IEEE_phy_speed(XEmacPs *mac']]+[(port/'xadapter.c',s) for s in ['static u32_t phy_link_detect(XEmacPs','static u32_t phy_autoneg_status(XEmacPs','void eth_link_detect(']],
 'init':[(port/'xemacpsif.c',s) for s in ['static err_t low_level_init(struct netif *netif)\n{','err_t xemacpsif_init(']],
 'mdio':[(lib/'emacps_v3_8/src/xemacps_control.c',s) for s in ['LONG XEmacPs_PhyRead(', 'LONG XEmacPs_PhyWrite(']]
}
results={}
for name,items in groups.items():
    source=out/(name+'_extracted.inc');source.write_text('\n'.join(function(path,sig) for path,sig in items))
    exe=out/(name+'.exe')
    cmd=[gcc,'-std=c99','-O2','-Wall','-Wextra','-Werror','-I'+str(out),'-I'+str(port),str(ROOT/('test_network_'+name+'.c')),'-o',str(exe)]
    subprocess.run(cmd,check=True,env=env)
    run=subprocess.run([str(exe)],capture_output=True,text=True,env=env,timeout=15)
    if run.returncode:raise RuntimeError(run.stdout+run.stderr)
    print(run.stdout.strip())
    results[name]={'result':run.stdout.strip(),'extracted_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
      'harness_sha256':hashlib.sha256((ROOT/('test_network_'+name+'.c')).read_bytes()).hexdigest()}
(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
