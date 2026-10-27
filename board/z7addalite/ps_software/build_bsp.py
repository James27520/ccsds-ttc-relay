"""Offline ARM BSP compile from generated ADDA hardware + pinned local sources.
No generated headers/libraries/initialization from LDSDR are consumed.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess
from build_common import tool_directory
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bsp',type=Path,default=ROOT/'platform_bsp_2018/ps7_cortexa9_0')
parser.add_argument('--out',type=Path,default=ROOT/'bsp_build')
parser.add_argument('--arm-bin',type=Path)
args=parser.parse_args();BSP=args.bsp.resolve();BIN=tool_directory(args.arm_bin,'ADDA_ARM_GCC_BIN','arm-none-eabi-gcc.exe');OUT=args.out.resolve()
if OUT.exists() and any(OUT.iterdir()):raise SystemExit('Refuse nonempty BSP build output; choose new --out')
OUT.mkdir(parents=True,exist_ok=True)
INC=OUT/'include';INC.mkdir(exist_ok=True)
shutil.copy2(BSP/'include/xparameters.h',INC/'xparameters.h')
sources=[]
for directory in sorted((BSP/'libsrc').iterdir()):
    if directory.name.startswith('lwip'):continue
    src=directory/'src'
    for h in src.glob('*.h'):shutil.copy2(h,INC/h.name)
    sources+=list(src.glob('*.c'))+list(src.glob('*.S'))
lwip=BSP/'libsrc/lwip202_v1_2/src'
lwipdir=next(p for p in lwip.iterdir() if p.is_dir() and (p/'src/core').exists())
port=lwip/'contrib/ports/xilinx'
for base in [lwipdir/'src/include',port/'include']:
    for p in base.iterdir():
        if p.is_dir():shutil.copytree(p,INC/p.name,dirs_exist_ok=True)
        else:shutil.copy2(p,INC/p.name)
lwips=list((lwipdir/'src/core').glob('*.c'))+list((lwipdir/'src/core/ipv4').glob('*.c'))
lwips+=[lwipdir/'src/netif/ethernet.c']
lwips += [port/p for p in ['sys_arch_raw.c','netif/xpqueue.c','netif/xadapter.c','netif/xtopology_g.c',
    'netif/xemacpsif_hw.c','netif/xemacpsif_physpeed.c','netif/xemacpsif.c','netif/xemacpsif_dma.c']]
flags=['-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-O2','-g','-ffunction-sections','-fdata-sections',
       '-fno-tree-loop-distribute-patterns','-fcommon','-I'+str(INC),'-DPROCESSOR_LITTLE_ENDIAN']
manifest={'inputs':{},'headers':{},'objects':{},'libraries':{},'compiler':str(BIN/'arm-none-eabi-gcc.exe')}
manifest['compiler_version']=subprocess.run([str(BIN/'arm-none-eabi-gcc.exe'),'--version'],check=True,capture_output=True,text=True).stdout
for header in sorted(INC.rglob('*')):
    if header.is_file():manifest['headers'][header.relative_to(INC).as_posix()]=hashlib.sha256(header.read_bytes()).hexdigest()
with (OUT/'build.log').open('w') as log:
    for group,srcs in [('xil',sources),('lwip',lwips)]:
        objects=[]
        for idx,src in enumerate(srcs):
            obj=OUT/f'{group}_{idx:03d}_{src.stem}.o';objects.append(obj)
            cmd=[str(BIN/'arm-none-eabi-gcc.exe'),*flags,'-I'+str(src.parent),'-c',str(src),'-o',str(obj)]
            log.write(' '.join(cmd)+'\n');log.flush()
            result=subprocess.run(cmd,stdout=log,stderr=log)
            if result.returncode:raise SystemExit(f'Compile failed: {src}; see {OUT / "build.log"}')
            manifest['inputs'][str(src)]=hashlib.sha256(src.read_bytes()).hexdigest()
            manifest['objects'][obj.name]=hashlib.sha256(obj.read_bytes()).hexdigest()
        archive=OUT/('libxil.a' if group=='xil' else 'liblwip4.a')
        if archive.exists():archive.unlink() # single generated file within this dedicated output
        subprocess.run([str(BIN/'arm-none-eabi-ar.exe'),'rcs',str(archive),*map(str,objects)],check=True,stdout=log,stderr=log)
        manifest['libraries'][archive.name]=hashlib.sha256(archive.read_bytes()).hexdigest()
        print(group,len(objects),'objects ->',archive.name,flush=True)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('PASS generated ADDA BSP compiled offline')
