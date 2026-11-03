"""Compare default decoding with the pre-Doppler source commit; no hardware."""
import argparse
import ctypes as ct
import hashlib
import json
from pathlib import Path
import re
import subprocess
import numpy as np
from test_dynamic import Frame, Stats, N, make_source, waveform


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref',default='7600e45')
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--zig',type=Path)
    parser.add_argument('--cc',default='gcc')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch('[0-9a-fA-F]{7,40}',args.baseline_ref):
        parser.error('baseline-ref must be a commit hash')
    repo=Path(__file__).resolve().parents[4]
    args.out.mkdir(parents=True,exist_ok=True)
    paths=['demod/adda_demod.c','demod/adda_demod.h','demod/adda_receiver.c',
           'demod/adda_receiver.h','protocol/adda_protocol.c','protocol/adda_protocol.h']
    hashes={}
    for relative in paths:
        data=subprocess.check_output(['git','show',f'{args.baseline_ref}:board/z7addalite/software/{relative}'],cwd=repo)
        p=args.out/'baseline'/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        hashes[relative]=hashlib.sha256(data).hexdigest()
    cc=[str(args.zig),'cc'] if args.zig else [args.cc]
    library=args.out/'baseline.dll'
    cmd=[*cc,'-std=c99','-O2','-UNDEBUG','-Wall','-Wextra','-Werror','-shared',
         *[str(args.out/'baseline'/p) for p in paths if p.endswith('.c')],'-lm','-o',str(library)]
    subprocess.run(cmd,check=True)
    old,new=ct.CDLL(str(library.resolve())),ct.CDLL(str(args.library.resolve()))
    for lib in (old,new):
        lib.adda_receive.argtypes=[ct.POINTER(ct.c_int16),ct.c_size_t,ct.POINTER(Frame),ct.POINTER(Stats)]
    source=make_source();rows=[]
    for i,cfo in enumerate((-31337,-22123,-1000,0,1500,17321,31337,48000)):
        for noise in (False,True):
            samples,_=waveform(source,cfo,0,0,90+i,snr=12,noise_only=noise)
            ptr=samples.ctypes.data_as(ct.POINTER(ct.c_int16))
            a,b=Frame(),Frame();sa,sb=Stats(),Stats()
            ra=old.adda_receive(ptr,N,ct.byref(a),ct.byref(sa))
            rb=new.adda_receive(ptr,N,ct.byref(b),ct.byref(sb))
            assert ra==rb,(cfo,ra,rb)
            if ra==1:
                for name,_ in Frame._fields_:
                    if name in ('command','body'):continue
                    assert getattr(a,name)==getattr(b,name),(cfo,name)
                assert bytes(a.body)==bytes(b.body)
            for name,_ in Stats._fields_:
                assert getattr(sa,name)==getattr(sb,name),(cfo,name,getattr(sa,name),getattr(sb,name))
            rows.append({'cfo_hz':cfo,'noise_only':noise,'return_code':ra,'identical':True})
    report={'kind':'host differential comparison, no RF','baseline_commit':args.baseline_ref,
            'baseline_sources':hashes,'cases':rows,'all_passed':True}
    (args.out/'legacy_equivalence.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(f'PASS {len(rows)} default-path comparisons: same decoded frame and all demod stats')


if __name__=='__main__':main()
