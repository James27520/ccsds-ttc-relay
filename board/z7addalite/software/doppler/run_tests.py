"""Offline C builds/tests only; no serial ports, device access, or downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BOARD = HERE.parents[1]
PS = BOARD / 'ps_software'
DEMOD = HERE.parent / 'demod'
PROTOCOL = HERE.parent / 'protocol'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', default='gcc', help='host C compiler executable')
    parser.add_argument('--zig', type=Path, help='use this Zig executable as C compiler')
    parser.add_argument('--out', type=Path, default=HERE / 'build')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cc = [str(args.zig), 'cc'] if args.zig else [args.cc]
    # Zig ReleaseFast defines NDEBUG: explicitly keep the existing C assertions.
    flags = ['-std=c99', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror']
    includes = [PS, BOARD / 'telecontrol_system/abi', DEMOD, PROTOCOL,
                HERE.parent / 'fixtures/generated']
    flags += ['-I'+str(p) for p in includes]
    demod = [DEMOD / 'adda_demod.c', DEMOD / 'adda_receiver.c', PROTOCOL / 'adda_protocol.c']
    tracking = [HERE / 'doppler.c', HERE / 'adda_doppler_rx.c']
    controller = [PS / p for p in ('adda_capture.c', 'adda_controller.c', 'adda_ps_core.c')]
    controller += [HERE.parent / 'fixtures/generated/waveform_fixture.c']
    runs = []

    def run(command, name):
        result = subprocess.run(list(map(str, command)), text=True, encoding='utf-8',
                                errors='replace', capture_output=True)
        (out / (name+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        if result.returncode:
            print(result.stdout, result.stderr)
            raise SystemExit(f'{name} failed ({result.returncode})')
        return result.stdout

    def executable(name, sources, extra=()):
        binary = out / (name+'.exe')
        run([*cc, *flags, *extra, *sources, '-lm', '-o', binary], name+'_build')
        stdout = run([binary], name)
        print(stdout.strip())
        runs.append({'name': name, 'passed': True, 'stdout': stdout})

    executable('doppler_core', [HERE/'doppler.c', HERE/'test_doppler.c'])
    executable('capture_default', [*controller, *demod, PS/'test_capture_controller.c'])
    executable('capture_doppler', [*controller, *demod, *tracking, HERE/'test_controller_doppler.c'],
               ['-DADDA_DOPPLER_ENABLED=1'])
    for name, test, sources in (
        ('ps_core', 'test_ps_core.c', [PS/'adda_ps_core.c', *demod]),
        ('khz_protocol', 'test_khz_control.c', [PS/'adda_ps_core.c', PS/'adda_telemetry_tx.c', *demod]),
        ('remote_protocol', 'test_remote_control.c', [PS/'adda_ps_core.c', PS/'adda_telemetry_tx.c', *demod]),
    ):
        executable(name, [*sources, PS/test])
    executable('service', [PS/n for n in ('adda_service.c','adda_controller.c','adda_ps_core.c',
               'adda_telemetry_tx.c','test_service.c')] + [PROTOCOL/'adda_protocol.c'],
               ['-DADDA_TM_TX_ENABLED=1'])
    for enabled in (0, 1):
        executable(f'telemetry_{enabled}', [PS/'adda_telemetry_tx.c', PS/'test_telemetry_tx.c',
                   PROTOCOL/'adda_protocol.c'], [f'-DADDA_TM_TX_ENABLED={enabled}'])
    library = out / 'doppler_receiver.dll'
    run([*cc, *flags, '-shared', *demod, *tracking, '-lm', '-o', library], 'library_build')
    run([sys.executable, DEMOD/'test_waveforms.py', '--library', library,
         '--results', out/'legacy_waveforms.json'], 'legacy_waveforms')
    print('PASS original 45 waveform cases')
    run([sys.executable, HERE/'test_dynamic.py', '--library', library, '--out', out], 'dynamic')
    print((out/'dynamic.log').read_text())
    sources = sorted(set([*demod, *tracking, *controller, *HERE.glob('*.h'), *HERE.glob('*.py'),
                          *HERE.glob('test*.c')]))
    report = {'kind': 'host simulation; no hardware execution', 'compiler': cc, 'tests': runs,
              'sources': {str(p.relative_to(BOARD)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    (out/'host_manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
