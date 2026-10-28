"""One wired ADC_NORMAL command followed by its independently decoded RF reply.

Run --probe first. Execution additionally needs --wiring-confirmed: source
TX1A -> ADDA J5, ADDA J6 -> same source RX1A. Business input is disconnected.
No automatic retries, local LO replacement, firmware load or persistent write.
"""
import argparse
import json
from pathlib import Path
import queue
import time

from .relay import RelayConsole
from .rf_live import RFTelemetryController, idle_dac
from .tc_hardware import CommandSource, ControlAdda, request_values
from .tc_evidence import assess_transaction
from .rf_session import probe_pair
from sw.tools.telecontrol_waveform import command_iq


def wait_for(read, condition, timeout, label):
    deadline = time.monotonic()+timeout
    while True:
        state = read()
        if condition(state):
            return state
        if time.monotonic() >= deadline:
            raise TimeoutError(label)
        time.sleep(.05)


def manual_command(a, source, relay, requested, record):
    """One normal snapshot, source stopped before C decode; never auto on."""
    before = a.acquire_control()
    for prefix in ('d', 's', 'a'):
        if before[prefix+'_valid'] and before[prefix+'_air_seq'] == requested['air_seq']:
            raise ValueError('请使用不同于最近记录的新空口序号')
    idle_dac(a.tmstatus())
    for command in ('auto off', 'arm off', 'levels 0 89', 'network on'):
        a.control(command)
    wait_for(a.query, lambda s: s['network'] == 1 and s['pending'] == 0, 12, '板间网口未就绪')
    a.control('arm on')
    source.start()
    a.control('capture normal 0 0')
    capture = wait_for(a.capture_status, lambda s: s['state'] in (6, 7), 5, 'ADC采集超时')
    if capture['state'] != 6 or capture['valid'] != 1 or capture['consumed']:
        raise RuntimeError('ADC未产生未消费的正常快照')
    source.stop()
    decode_lines = a.control('decode')
    expected = ('DECODED source=ADC_NORMAL rx={rx_mhz} tx={tx_mhz} '
                'air_seq={air_seq} rc=0').format(**requested)
    if expected not in decode_lines:
        raise RuntimeError('本次ADC_NORMAL解码与新指令不符')
    applied = wait_for(a.query, lambda s: s['pending'] == 0 and s['applied'] != before['applied'],
                       5, '未获得新的匹配ACK')
    if applied['applied'] != before['applied']+1 or applied['failures'] != before['failures']:
        raise RuntimeError('控制计数异常，不计为闭环成功')
    spi = relay.diagnostics(atten=89, gain=0, exact_frequency=False)
    for name in ('rx', 'tx'):
        if abs(spi['relay_'+name+'_hz_readback']-requested[name+'_mhz']*1000000) > 10000:
            raise RuntimeError('独立SPI频率与指令不一致')
    a.release_control()  # After ACK only; keeps all three evidence records.
    wait_for(a.tmstatus, lambda s: s['pending'] == s['stopping'] == 0, 3, 'DAC停止握手未完成')
    idle_dac(a.tmstatus())
    frozen = a.query()
    record(kind='tc_control_complete', requested=requested, before=before, applied=applied,
           frozen=frozen, spi=spi, adc_capture=capture, decode_lines=decode_lines)
    return dict(before=before, frozen=frozen, spi=spi, adc_capture=capture)


def receive_reply(out, source_port, adda_port, source_identity, adda_identity, boot_interval, uptime):
    events = queue.Queue()
    def prober(rx, adda, record):
        return probe_pair(rx, adda, record, adda_continuity=(boot_interval, uptime))
    c = RFTelemetryController(events.put, log_dir=out/'downlink', prober=prober)
    def wait(kind, state=None, timeout=60):
        deadline = time.monotonic()+timeout
        while True:
            try:
                event = events.get(timeout=max(.01, deadline-time.monotonic()))
            except queue.Empty:
                raise TimeoutError('下行等待超时：'+kind) from None
            if event['type'] == 'status' and event.get('state') == 'error':
                raise RuntimeError(event['message'])
            if event['type'] == kind and (state is None or event.get('state') == state):
                return event
            if time.monotonic() >= deadline:
                raise TimeoutError('下行等待超时：'+kind)
    try:
        wait('status', 'disconnected')
        c.submit('probe', rx_port=source_port, adda_port=adda_port)
        event = wait('probe')
        # Same physical selection and SDR boot throughout the sequential test.
        for role, previous in [('receiver', source_identity), ('adda', adda_identity)]:
            now = event['binding'][role]
            keys = set(previous)-{'identity_scope', 'physical_role'}
            if any(now.get(key) != previous.get(key) for key in keys):
                raise RuntimeError('控制阶段与下行阶段设备身份变化：'+role)
        wait('status', 'probed')
        c.submit('connect', binding_token=event['binding_token'])
        wait('status', 'connected')
        c.submit('capture', send=True)
        captured = wait('capture')
        wait('status', 'connected')
        return captured
    finally:
        c.submit('close')
        # Keep port owner alive through baud recovery and report cleanup failure.
        c.worker.join(55)
        if c.worker.is_alive():
            raise RuntimeError('下行worker尚未退出；不得并行打开其端口')
        remaining = []
        while not events.empty():
            remaining.append(events.get_nowait())
        if any(e.get('state') == 'error' or e.get('level') == 'error' for e in remaining):
            raise RuntimeError('下行关闭未完全确认，见采集日志')


def execute(out, source_port, adda_port, relay_port, requested, *, wiring_confirmed=False, probe=False):
    request_values(**requested)
    if len({source_port.casefold(), adda_port.casefold(), relay_port.casefold()}) != 3:
        raise ValueError('三个DEBUG端口必须各不相同')
    if not probe and wiring_confirmed is not True:
        raise ValueError('实板执行前必须确认测控上下行接线')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    report = dict(passed=False, probe_only=probe, requested=requested)
    source = adda = relay = None
    errors = []
    with (out/'control.jsonl').open('x', encoding='utf-8') as journal:
        def record(**data):
            journal.write(json.dumps(dict(time=time.time(), **data), ensure_ascii=False)+'\n')
            journal.flush()
        try:
            source = CommandSource(source_port, record)
            adda = ControlAdda(adda_port, record)
            relay = RelayConsole(relay_port, record)
            source.require_idle()
            source_identity, adda_identity = source.info, adda.info
            report['identities'] = dict(source=source_identity, adda=adda_identity)
            report['initial'] = dict(adda=adda.query(), adc=adda.capture_status(), dac=adda.tmstatus(),
                source_tx_powerdown=source.read(source.phy+'/out_altvoltage1_TX_LO_powerdown'),
                source_rx_buffer=source.read(source.rx+'/buffer/enable'),
                source_tx_buffer=source.read(source.tx+'/buffer/enable'),
                relay=relay.diagnostics(atten=89, gain=0, exact_frequency=False))
            if report['initial']['source_tx_powerdown'] != '1':
                raise RuntimeError('指令源未关闭，禁止换线或接管')
            idle_dac(report['initial']['dac'])
            state, capture = report['initial']['adda'], report['initial']['adc']
            if (any(state[k] for k in ('network', 'armed', 'pending')) or capture['auto'] or
                    capture['state'] in range(1, 6)):
                raise RuntimeError('遥控板已有控制或采集任务，拒绝接管')
            if not probe:
                # Preflight the ADDA before changing even muted source settings.
                adda.acquire_control()
                report['waveform'] = source.prepare(requested, wiring_confirmed=True)
                (out/'source_waveform.bin').write_bytes(
                    command_iq(
                        requested['rx_mhz'],requested['tx_mhz'],requested['air_seq'],.1).tobytes())
                report['control'] = manual_command(adda, source, relay, requested, record)
                report['dac_sequence'] = adda.tmstatus()['seq']
                adda.verify_binding()
                boot_interval, uptime = adda._boot_interval, adda._uptime
                source.close(); source = None
                adda.close(); adda = None
                event = receive_reply(out, source_port, adda_port, source_identity, adda_identity,
                                      boot_interval, uptime)
                report['rf_iq'] = event['iq_path']
                report['rf_report'] = event['report_path']
                report['assessment'] = assess_transaction(requested, report['control']['before'],
                    report['control']['frozen'], report['control']['spi'], event['report'], report['dac_sequence'])
                report['final_spi'] = relay.diagnostics(atten=89, gain=0, exact_frequency=False)
                if report['final_spi'] != report['control']['spi']:
                    raise RuntimeError('下行采样期间转发频率或电平改变')
            report['passed'] = True
        except BaseException as exc:
            report['error'] = repr(exc)
        finally:
            if source:
                try:
                    source.stop()
                except Exception as exc:
                    errors.append('指令源停发：'+str(exc))
            if adda:
                try:
                    adda.release_control()
                except Exception as exc:
                    errors.append('遥控板停止：'+str(exc))
            for handle in (source, adda, relay):
                if handle:
                    try:
                        handle.close()
                    except Exception as exc:
                        errors.append('关闭串口：'+str(exc))
            report['cleanup_errors'] = errors
            if errors:
                report['passed'] = False
            (out/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True)
    p.add_argument('--adda', required=True)
    p.add_argument('--relay', required=True)
    p.add_argument('--rx', type=int, default=900)
    p.add_argument('--tx', type=int, default=1001)
    p.add_argument('--seq', type=int, default=240)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--probe', action='store_true')
    p.add_argument('--wiring-confirmed', action='store_true')
    a = p.parse_args()
    result = execute(a.out, a.source, a.adda, a.relay, request_values(a.rx,a.tx,a.seq),
                     probe=a.probe, wiring_confirmed=a.wiring_confirmed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
