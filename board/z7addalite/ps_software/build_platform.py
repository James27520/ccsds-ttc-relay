"""Link two reviewable ADDA ELF candidates offline; never download/run."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,zipfile
from build_common import tool_directory
from build_bsp_guard import verify_bsp
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,default=ROOT/'platform_build_next')
parser.add_argument('--bsp',type=Path,default=ROOT/'bsp_build')
parser.add_argument('--arm-bin',type=Path)
parser.add_argument('--xsa',type=Path,default=ROOT/'../telecontrol_system/reports/telecontrol_platform.xsa')
parser.add_argument('--ps-init',type=Path,default=ROOT/'../telecontrol_system/reports/platform_init/ps7_init.tcl')
parser.add_argument('--hardware-note',default='Pre-final PS/AXI platform; no final routed capture acceptance')
parser.add_argument('--tm-tx-enabled',action='store_true',help='Explicit opt-in ONLY for new matching telemetry PL; never use with frozen r4c')
args=parser.parse_args();BIN=tool_directory(args.arm_bin,'ADDA_ARM_GCC_BIN','arm-none-eabi-gcc.exe');OUT=args.out.resolve();BSP=args.bsp.resolve()
try:bsp_verification=verify_bsp(BSP)
except (ValueError,KeyError,OSError) as exc:raise SystemExit('BSP pre-link verification failed: '+str(exc))
if OUT.exists() and list(OUT.glob('*.elf')):raise SystemExit('Refuse to overwrite frozen ELF directory; choose new --out')
OUT.mkdir(parents=True,exist_ok=True)
linker=(ROOT/'vendor_reference/lscript_reference_only.ld').read_text()
linker=linker.replace('ORIGIN = 0x100000, LENGTH = 0x3FF00000','ORIGIN = 0x01000000, LENGTH = 0x3F000000')
linker=linker.replace('_STACK_SIZE : 0x2000','_STACK_SIZE : 0x40000').replace('_HEAP_SIZE : 0x2000','_HEAP_SIZE : 0x1000000')
linker=linker.replace('_IRQ_STACK_SIZE : 1024','_IRQ_STACK_SIZE : 16384')
(OUT/'adda.ld').write_text(linker)
incs=[BSP/'include',ROOT,ROOT/'../telecontrol_system/abi',ROOT/'../software/protocol',ROOT/'../software/demod',ROOT/'../software/fixtures/generated']
flags=['-std=c99','-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-O2','-g','-ffunction-sections','-fdata-sections','-Wall','-Wextra']+['-I'+str(p) for p in incs]
sources=[ROOT/n for n in ['adda_platform_main.c','adda_ps_core.c','adda_capture.c','adda_controller.c','adda_pattern_check.c','adda_telemetry_tx.c','adda_service.c',
 '../software/protocol/adda_protocol.c','../software/demod/adda_demod.c','../software/demod/adda_receiver.c','../software/fixtures/generated/waveform_fixture.c']]
manifest={'hardware':args.hardware_note,'tm_tx_enabled':args.tm_tx_enabled,'files':{},'inputs':{},'sources':{},'bsp_verification':bsp_verification}
for label,path in [('xsa',args.xsa),('ps7_init',args.ps_init),('bsp_manifest',BSP/'manifest.json'),('libxil',BSP/'libxil.a'),('liblwip4',BSP/'liblwip4.a'),('xparameters',BSP/'include/xparameters.h')]:
    manifest['inputs'][label]={'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
shutil.copy2(args.ps_init,OUT/'ps7_init.tcl')
source_inputs=sources+[ROOT/'build_platform.py',ROOT/'build_bsp.py',ROOT/'build_bsp_guard.py',ROOT/'build_common.py',ROOT/'patch_network_bsp.py',ROOT/'network_phy_policy.inc',ROOT/'../telecontrol_system/abi/capture_abi.h']+list(ROOT.glob('*.h'))
source_inputs+=list((ROOT/'../software/protocol').glob('*.h'))+list((ROOT/'../software/demod').glob('*.h'))+list((ROOT/'../software/fixtures/generated').glob('*.h'))
source_inputs+=[ROOT/'vendor_reference/lscript_reference_only.ld']
source_inputs=sorted(set(src.resolve() for src in source_inputs))
for src in source_inputs:manifest['sources'][os.path.relpath(src,ROOT)]=hashlib.sha256(src.read_bytes()).hexdigest()
with zipfile.ZipFile(OUT/'source_snapshot.zip','w',compression=zipfile.ZIP_DEFLATED) as freeze:
    for src in source_inputs:freeze.write(src,src.relative_to(ROOT.parent).as_posix())
manifest['files']['source_snapshot.zip']=hashlib.sha256((OUT/'source_snapshot.zip').read_bytes()).hexdigest()
manifest['files']['ps7_init.tcl']=hashlib.sha256((OUT/'ps7_init.tcl').read_bytes()).hexdigest()
with (OUT/'build.log').open('w') as log:
    for enabled in [0,1]:
        variant='adda_ps_selftest' if not enabled else 'adda_m2_candidate'
        if args.tm_tx_enabled:variant+='_tm'
        objects=[]
        for src in sources:
            obj=OUT/(variant+'_'+src.stem+'.o');objects.append(obj)
            cmd=[str(BIN/'arm-none-eabi-gcc.exe'),*flags,f'-DADDA_CAPTURE_ENABLED={enabled}',f'-DADDA_TM_TX_ENABLED={int(args.tm_tx_enabled)}','-c',str(src),'-o',str(obj)]
            log.write(' '.join(cmd)+'\n');log.flush()
            if subprocess.run(cmd,stdout=log,stderr=log).returncode:raise SystemExit('compile failed: '+str(src))
        elf=OUT/(variant+'.elf');mapfile=OUT/(variant+'.map')
        cmd=[str(BIN/'arm-none-eabi-gcc.exe'),'-mcpu=cortex-a9','-mfpu=vfpv3','-mfloat-abi=hard','-nostartfiles',
          '-Wl,--gc-sections','-Wl,-Map='+str(mapfile),'-T',str(OUT/'adda.ld'),*map(str,objects),'-L'+str(BSP),
          '-Wl,--start-group','-lxil','-llwip4','-lm','-lc','-lgcc','-Wl,--end-group','-o',str(elf)]
        log.write(' '.join(cmd)+'\n');log.flush()
        if subprocess.run(cmd,stdout=log,stderr=log).returncode:raise SystemExit('link failed: '+variant)
        for p in [elf,mapfile]:manifest['files'][p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
        result=subprocess.run([str(BIN/'arm-none-eabi-readelf.exe'),'-h','-l',str(elf)],check=True,capture_output=True,text=True)
        (OUT/(variant+'_readelf.txt')).write_text(result.stdout)
        size=subprocess.run([str(BIN/'arm-none-eabi-size.exe'),str(elf)],check=True,capture_output=True,text=True)
        print(size.stdout.strip(),flush=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('PASS linked candidates only; no hardware execution')
