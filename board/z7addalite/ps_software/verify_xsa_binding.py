"""Verify full HWH/init identity and bitstream membership before ELF delivery.

Only the HWH export's root TIMESTAMP is ignored. All peripherals, parameters,
ports, memory maps, target part and other content must match the XSA used to
generate the BSP. This script is read-only except for its requested JSON report.
"""
import argparse, hashlib, json, xml.etree.ElementTree as ET, zipfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
for name in ['platform-xsa','final-xsa','ps-init','bit','out']:
    p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args()

def sha(data):return hashlib.sha256(data).hexdigest()
def hwhs(z):
    result={}
    for name in sorted(z.namelist()):
        if not name.endswith('.hwh'):continue
        root=ET.fromstring(z.read(name));root.attrib.pop('TIMESTAMP',None)
        text=ET.canonicalize(ET.tostring(root,encoding='unicode'),strip_text=True)
        result[name]=sha(text.encode())
    return result

report={'scope':'offline hardware binding, no board acceptance','inputs':{}}
for name in ['platform_xsa','final_xsa','ps_init','bit']:
    path=getattr(a,name)
    report['inputs'][name]={'path':str(path.resolve()),'sha256':sha(path.read_bytes())}
with zipfile.ZipFile(a.platform_xsa) as old,zipfile.ZipFile(a.final_xsa) as final:
    old_hwh,final_hwh=hwhs(old),hwhs(final)
    report['platform_hwh_canonical_sha256']=old_hwh
    report['final_hwh_canonical_sha256']=final_hwh
    report['hwh_equal_except_export_timestamp']=bool(old_hwh) and old_hwh==final_hwh
    report['ps_init_equal']=old.read('ps7_init.tcl')==final.read('ps7_init.tcl')==a.ps_init.read_bytes()
    report['bit_members']={n:sha(final.read(n)) for n in final.namelist() if n.endswith('.bit')}
    report['bit_member_matches']=report['inputs']['bit']['sha256'] in report['bit_members'].values()
report['pass']=all(report[k] for k in ['hwh_equal_except_export_timestamp','ps_init_equal','bit_member_matches'])
if a.out.exists():raise SystemExit('Refuse overwrite; choose a new --out report')
a.out.parent.mkdir(parents=True,exist_ok=True)
a.out.write_text(json.dumps(report,indent=2)+'\n')
if not report['pass']:raise SystemExit('FAIL: XSA/init/bit mismatch; see '+str(a.out))
print('PASS complete HWH (except export timestamp), ps7_init and embedded bitstream binding')
