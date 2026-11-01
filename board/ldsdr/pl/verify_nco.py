"""Offline NCO regression against four hash-pinned external RTL files.

No serial/JTAG access or full FPGA build. Baseline inputs remain read-only.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', required=True, type=Path)
    parser.add_argument('--vivado-bin', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    rtl, out = args.rtl.resolve(), args.out.resolve()
    if out.exists() or out == rtl or rtl in out.parents or out == HERE or HERE in out.parents:
        parser.error('Use a new output directory outside baseline and package')
    pins = json.loads((HERE/'baseline.json').read_text(encoding='utf-8'))
    for name, expected in pins['sources_sha256'].items():
        if sha(rtl/name) != expected:
            raise ValueError(f'Baseline hash mismatch: {name}')
    # Reuse the exact-context unified-diff parser used by the PS rebuild.
    spec = importlib.util.spec_from_file_location('ldsdr_patch', HERE.parent/'rebuild.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out.mkdir(parents=True)
    report = {'hardware_tested': False, 'baseline_sha256': pins['sources_sha256'],
              'patch_sha256': sha(HERE/'relay_nco.patch'),
              'bench_sha256': sha(HERE/'tb_nco_axis.sv'), 'cases': {}}
    for name in ('baseline', 'candidate'):
        work = out/name
        src = work/'src'
        src.mkdir(parents=True)
        for filename in pins['sources_sha256']:
            shutil.copy2(rtl/filename, src/filename)
        if name == 'candidate':
            module.apply_patch(work, (HERE/'relay_nco.patch').read_text(encoding='utf-8'))
            if sha(src/'relay_nco.v') != pins['candidate_nco_sha256']:
                raise ValueError('Patched NCO hash mismatch')
        suffix = '.bat' if os.name == 'nt' else ''
        commands = [
            ['xvlog', '--sv', *(['--define', 'BASELINE'] if name == 'baseline' else []),
             str(HERE/'tb_nco_axis.sv'), *[str(src/f) for f in pins['sources_sha256']]],
            ['xelab', 'tb_nco_axis', '-s', 'nco_test'],
            ['xsim', 'nco_test', '-runall'],
        ]
        for number, command in enumerate(commands):
            command[0] = str(args.vivado_bin.resolve()/(command[0]+suffix))
            proc = subprocess.run(command, cwd=work, capture_output=True,
                                  text=True, errors='replace', timeout=180)
            log = proc.stdout+proc.stderr
            (work/f'step{number}.log').write_text(log, encoding='utf-8')
            if proc.returncode:
                raise RuntimeError(f'{name} failed: see {work}/step{number}.log')
        marker = 'BASELINE_REPRODUCED' if name == 'baseline' else 'CANDIDATE_PASS'
        if marker not in log or 'Fatal:' in log:
            raise RuntimeError(f'{name}: expected simulation result missing')
        result = next(line for line in log.splitlines() if marker in line)
        report['cases'][name] = {'result': result, 'commands': commands}
        print(result, flush=True)
    for name, expected in pins['sources_sha256'].items():
        if sha(rtl/name) != expected:
            raise ValueError(f'Baseline changed during verification: {name}')
    report['passed'] = True
    (out/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
