"""Offline C checker cross-check against captured M1 vectors and corruptions."""
import argparse,ctypes,hashlib,os,subprocess,json
from pathlib import Path
from build_common import tool_directory
ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host-bin',type=Path)
parser.add_argument('--fixtures',type=Path,default=ROOT/'../telecontrol_system/sim/pn9_fixtures')
parser.add_argument('--out',type=Path,default=ROOT/'build/pattern')
args=parser.parse_args()
args.out.mkdir(parents=True,exist_ok=True)
BIN=tool_directory(args.host_bin,'ADDA_HOST_GCC_BIN','gcc.exe')
handle=os.add_dll_directory(str(BIN))
subprocess.run([str(BIN/'gcc.exe'),'-std=c99','-O2','-Wall','-Wextra','-Werror','-shared',str(ROOT/'adda_pattern_check.c'),'-o',str(args.out/'pattern_check.dll')],check=True)
lib=ctypes.CDLL(str(args.out/'pattern_check.dll'))
class Result(ctypes.Structure):
    _fields_=[(n,ctypes.c_uint32) for n in ['samples','transitions','mismatches','zero_states','invalid_samples','toggle_mask','first_raw','last_raw']]
lib.apc_check.argtypes=[ctypes.POINTER(ctypes.c_int16),ctypes.c_size_t,ctypes.c_uint,ctypes.POINTER(Result)]
lib.apc_check.restype=ctypes.c_int
fixture_manifest=json.loads((args.fixtures/'pn9_fixture_manifest.json').read_text(encoding='utf-8'))
fixture_entries={entry['path']:entry for entry in fixture_manifest['files']}
provenance=[]
results=[]
def check(raw,channel,expected,label):
    signed=[v-0x4000 if v&0x2000 else v for v in raw]
    array=(ctypes.c_int16*len(signed))(*signed);r=Result()
    rc=lib.apc_check(array,len(signed),channel,ctypes.byref(r))
    assert rc==expected,(label,rc,r.mismatches)
    results.append({'case':label,'rc':rc,**{n:getattr(r,n) for n,_ in r._fields_}})
files=[args.fixtures/f'pn9_real_{index:02d}.mem' for index in range(3)]
for p in files:
    entry=fixture_entries[p.name]
    assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256'],p.name
    vectors=[int(line,16) for line in p.read_text(encoding='ascii').splitlines()]
    assert len(vectors)==4096 and all(0<=v<(1<<112) for v in vectors)
    words=[(v>>(14*k))&0x3fff for v in vectors for k in range(8)]
    provenance.append({'fixture':p.name,'fixture_sha256':entry['sha256'],'source_csv':entry['provenance']['source_csv'],'source_csv_sha256':entry['provenance']['source_csv_sha256']})
    for channel in [0,1]:
        stream=words[channel::2]
        for k in range(4):
            raw=stream[k::4];label=f'{p.name} channel{channel} k{k}'
            check(raw,channel,1,label)
            bad=raw.copy();bad[len(bad)//2]^=1;check(bad,channel,0,label+' flipped bit')
    a=words[0::8]
    check(a[:511],0,-1,p.name+' truncated')
    check([0x3fff]*1024,0,0,p.name+' zero LFSR')
    check([x^0x3fff for x in a],0,0,p.name+' wrong normalization')
(args.out/'pattern_check_results.json').write_text(json.dumps({'source':'archived historical PN9 capture-derived fixtures; not a new measurement','provenance':provenance,'cases':results},indent=2)+'\n')
print('PASS',len(results),'offline C cases replaying three historical capture-derived fixtures; no new hardware measurement')
