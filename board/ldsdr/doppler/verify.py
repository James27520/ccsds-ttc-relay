"""Minimal offline business algorithm and IQ capture simulation. No board I/O."""
import argparse,json,subprocess,hashlib
from pathlib import Path
HERE=Path(__file__).resolve().parent
CORE=HERE.parents[1]/'z7addalite/software/doppler'
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--cc',required=True,type=Path);p.add_argument('--vivado-bin',required=True,type=Path)
 p.add_argument('--relay-rtl',type=Path,help='Optional existing relay RTL for C-to-NCO integration check')
 p.add_argument('--out',required=True,type=Path);a=p.parse_args();out=a.out.resolve()
 out.mkdir(parents=True,exist_ok=False)
 commands=[
  [a.cc,'-std=c99','-O2','-UNDEBUG','-Wall','-Wextra','-Werror','-I'+str(CORE),HERE/'relay_doppler.c',CORE/'doppler.c',HERE/'test_business.c','-lm','-o',out/'test_business.exe'],
  [out/'test_business.exe'],
  [a.cc,'-std=c99','-O2','-UNDEBUG','-Wall','-Wextra','-Werror','-I'+str(CORE),HERE/'relay_doppler.c',CORE/'doppler.c',HERE/'test_board.c','-lm','-o',out/'test_board.exe'],
  [out/'test_board.exe'],
  [a.vivado_bin/'xvlog.bat','--sv',HERE/'relay_iq_snapshot.v',HERE/'tb_snapshot.sv'],
  [a.vivado_bin/'xelab.bat','tb_snapshot','-s','snapshot_test'],
  [a.vivado_bin/'xsim.bat','snapshot_test','-runall']]
 if a.relay_rtl:
  pins=json.loads((HERE.parent/'pl/baseline.json').read_text())
  for name,h in pins['sources_sha256'].items():
   expected=pins['candidate_nco_sha256'] if name=='relay_nco.v' else h
   if hashlib.sha256((a.relay_rtl/name).read_bytes()).hexdigest()!=expected:raise ValueError('Relay RTL changed: '+name)
  commands += [[a.vivado_bin/'xvlog.bat','--sv',HERE/'tb_business_mix.sv',*a.relay_rtl.glob('relay_*.v')],
   [a.vivado_bin/'xelab.bat','tb_business_mix','-s','mixer_test'],
   [a.vivado_bin/'xsim.bat','mixer_test','-runall'],[out/'test_business.exe','--rtl-output']]
 report={'hardware_tested':False,'commands':[]}
 for k,cmd in enumerate(commands):
  cmd=list(map(str,cmd));r=subprocess.run(cmd,cwd=out,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240)
  log=r.stdout+r.stderr;(out/f'step{k}.log').write_text(log,encoding='utf-8');report['commands'].append(cmd)
  if r.returncode or 'Fatal:' in log: raise RuntimeError(str(out/f'step{k}.log'))
  if k in (1,3,6,10):
   expected={1:'BUSINESS_DOPPLER_PASS',3:'BOARD_DOPPLER_PASS',6:'SNAPSHOT_PASS',10:'MIXER_PASS'}[k]
   if expected not in log: raise RuntimeError('Missing '+expected)
   print(next(line for line in log.splitlines() if expected in line));report[{1:'c_result',3:'board_mock_result',6:'rtl_result',10:'mixer_result'}[k]]=log
 report['passed']=True
 report['source_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.suffix in ('.c','.h','.v','.sv','.py')}
 (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
if __name__=='__main__':main()
