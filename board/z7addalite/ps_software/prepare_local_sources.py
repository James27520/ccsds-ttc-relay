"""Extract minimal existing local source dependencies, no downloads or board I/O."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import zipfile
import argparse

ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--embeddedsw-archive',type=Path,default=os.environ.get('ADDA_EMBEDDEDSW_ARCHIVE'))
p.add_argument('--vendor-uart-archive',type=Path,default=os.environ.get('ADDA_VENDOR_UART_ARCHIVE'))
a=p.parse_args()
if not a.embeddedsw_archive:
    p.error('Supply --embeddedsw-archive or set ADDA_EMBEDDEDSW_ARCHIVE')
if not a.vendor_uart_archive and not (ROOT/'vendor_reference/lscript_reference_only.ld').is_file():
    p.error('The packaged linker reference is missing; supply --vendor-uart-archive or ADDA_VENDOR_UART_ARCHIVE')
SDK_ZIP=a.embeddedsw_archive;UART_ZIP=a.vendor_uart_archive
DRIVERS=['common','cpu_cortexa9','generic','uartps','scugic','scutimer','scuwdt',
         'emacps','ddrps','devcfg','dmaps','xadcps','coresightps_dcc','qspips','sdps']
prefixes=['lib/bsp/standalone/','ThirdParty/sw_services/lwip202/']+[
    'XilinxProcessorIPLib/drivers/'+name+'/' for name in DRIVERS]
manifest={'archives':{},'files':{}}

def save(base,relative,data):
    parts=PurePosixPath(relative).parts
    if not parts or '..' in parts or PurePosixPath(relative).is_absolute():raise ValueError(relative)
    target=base.joinpath(*parts).resolve()
    if not target.is_relative_to(base.resolve()):raise ValueError(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists() and target.read_bytes()!=data:raise RuntimeError('Refusing overwrite changed '+str(target))
    target.write_bytes(data)
    manifest['files'][str(target.relative_to(ROOT))]=hashlib.sha256(data).hexdigest()

for archive in [path for path in [SDK_ZIP,UART_ZIP] if path is not None]:
    manifest['archives'][str(archive)]=hashlib.sha256(archive.read_bytes()).hexdigest()
with zipfile.ZipFile(SDK_ZIP) as z:
    for entry in z.infolist():
        if entry.is_dir():continue
        relative='/'.join(PurePosixPath(entry.filename).parts[1:])
        if relative=='license.txt' or any(relative.startswith(prefix) for prefix in prefixes):
            save(ROOT/'embeddedsw_2018_subset',relative,z.read(entry))
if UART_ZIP:
 with zipfile.ZipFile(UART_ZIP) as z:
    sdk='arm_01_uart_hello_world/arm_01_uart_hello_world.sdk/'
    selected={
        'design_1_wrapper.hdf':'uart_only.hdf',
        'design_1_wrapper_hw_platform_0/ps7_init.tcl':'ps7_init_reference_only.tcl',
        'design_1_wrapper_hw_platform_0/ps7_init.c':'ps7_init_reference_only.c',
        'helloword_bsp/system.mss':'system.mss',
        'helloword_bsp/ps7_cortexa9_0/include/xparameters.h':'xparameters_reference_only.h',
        'helloword/src/lscript.ld':'lscript_reference_only.ld'}
    for source,dest in selected.items():save(ROOT/'vendor_reference',dest,z.read(sdk+source))
(ROOT/'local_sources_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Local files prepared:',len(manifest['files']))
print('Generic 2018.3 source subset prepared; generate the BSP from the release ADDA XSA.')
