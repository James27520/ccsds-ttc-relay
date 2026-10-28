"""Offline cross-module ADDA/LDSDR/host wire integration; never hardware or RF.

The native program runs the real C send/parse/ACK/ATM2 implementations against
explicitly fake hardware snapshots. Python then consumes its exact payloads
using the production parser and assessment function. An assessment of these
fixtures demonstrates format interoperability only, not actual IQ acquisition.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
PS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gcc', type=Path, default=os.environ.get('CC',
        'D:/AMDDesignTools/2026.1/tps/mingw/10.0.0/win64.o/nt/bin/gcc.exe'))
    parser.add_argument('--out', type=Path, help='Fresh evidence directory; never overwritten')
    args = parser.parse_args()
    out = args.out or Path(tempfile.mkdtemp(prefix='adda_remote_wire_'))
    if args.out:
        out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT))
    from sw.tools.telemetry_downlink import parse_payload
    from sw.ground_station.tc_live import assess_rf_reply
    from sw.ground_station.telemetry import parse_tm1
    names = {0x21: 'enable', 0x22: 'stop', 0x23: 'status'}
    sources = [PS/'test_remote_wire.c', PS/'adda_ps_core.c', PS/'adda_telemetry_tx.c',
               PS/'../software/protocol/adda_protocol.c', PS/'../software/demod/adda_demod.c',
               PS/'../software/demod/adda_receiver.c']
    command = [str(args.gcc.resolve()), '-std=c99', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
               '-I'+str(PS/'../software/protocol'), '-I'+str(PS/'../software/demod'),
               *map(str, sources), '-lm', '-o', str(out/'remote_wire.exe')]
    environment = dict(os.environ, PATH=str(args.gcc.resolve().parent)+os.pathsep+os.environ.get('PATH', ''))
    build = subprocess.run(command, capture_output=True, text=True, env=environment)
    (out/'build.log').write_text(build.stdout+build.stderr, encoding='utf-8')
    build.check_returncode()
    run = subprocess.run([str(out/'remote_wire.exe')], capture_output=True, text=True, env=environment)
    (out/'native.jsonl').write_text(run.stdout, encoding='utf-8')
    (out/'native.stderr.log').write_text(run.stderr, encoding='utf-8')
    run.check_returncode()
    cases = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(cases) == 5
    results = []
    for case in cases:
        payload = bytes.fromhex(case['payload_hex'])
        snapshot = parse_payload(payload)
        requested = dict(operation=names[case['operation']], rx_mhz=900, tx_mhz=1001, air_seq=case['air_seq'])
        assessment = assess_rf_reply(requested, dict(frames=[dict(payload_hex=payload.hex(), crc16=case['crc16'])]))
        tm1 = parse_tm1(case['tm1'])
        if case['remote_rc']:
            assert all(value == 0 for key, value in tm1.items() if key.startswith('a_'))
            assert tm1['failures'] == 1 and tm1['applied'] == 0
            assert snapshot['ack_record']['valid'] and snapshot['ack_record']['rc'] == case['remote_rc']
        else:
            assert tm1['a_valid'] == 1 and tm1['a_rc'] == 0
        assert snapshot['protocol'] == 'EXPERIMENTAL_ATM2' and len(payload) == 112
        assert assessment['matched'] and assessment['passed'] == (case['remote_rc'] == 0)
        assert assessment['remote_rc'] == case['remote_rc'] and not assessment['independent_spi']
        assert snapshot['applied'] == (1 if not case['remote_rc'] else 0)
        assert snapshot['failures'] == (1 if case['remote_rc'] else 0)
        assert snapshot['ack_record']['command_version'] == case['operation']
        assert all(snapshot[key]['origin_name'] == 'ADC_NORMAL' for key in ('decoded_record', 'send_record', 'ack_record'))
        if 'different_lo' in case['case']:
            assert snapshot['ack_record']['rx_hz'] != requested['rx_mhz']*1_000_000
        if case['case'] == 'negative_invalid_readback':
            assert not snapshot['relay']['valid'] and not snapshot['spi_valid']
        if case['case'] == 'enable':
            assert snapshot['relay']['lease_active'] and snapshot['relay']['lease_expired']
            assert snapshot['relay']['remaining_ms'] == 299990
        results.append(dict(case=case['case'], matched=assessment['matched'], success=assessment['passed'],
                            legacy_tm1_parse=True, legacy_tm1_ack_valid=tm1['a_valid'],
                            remote_rc=case['remote_rc'], payload_bytes=len(payload), relay=snapshot['relay'],
                            actual_rx_hz=snapshot['ack_record']['rx_hz'], actual_tx_hz=snapshot['ack_record']['tx_hz']))
    inputs = sources+[PS/'../software/protocol/adda_protocol.h', PS/'adda_ps_core.h', PS/'adda_telemetry_tx.h',
                      ROOT/'board/ldsdr/remote_control/relay_remote_packet.h', Path(__file__),
                      ROOT/'sw/tools/telemetry_downlink.py', ROOT/'sw/ground_station/tc_live.py']
    inputs.append(ROOT/'sw/ground_station/telemetry.py')
    result = dict(passed=True, scope='offline native wire fixtures; no hardware, sockets or RF IQ acquisition',
                  command=command, cases=results,
                  source_sha256={str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs})
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f'PASS {len(cases)} cross-module ADDA -> LDSDR -> ADDA -> ATM2 -> Python cases; offline fixtures only; output={out}')


if __name__ == '__main__':
    main()
