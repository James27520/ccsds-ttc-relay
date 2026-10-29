"""Offline presentation data for the three-window UI review.

No controller, serial connection or transmitter is constructed here. Drafts
are not sent commands; historical evidence never becomes current device state.
"""
from decimal import Decimal, InvalidOperation, localcontext
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from .rf_profiles import BUSINESS_TX_CENTERS, BUSINESS_RX_CENTERS


MIN_CENTER_MHZ = Decimal('70.5')
MAX_CENTER_MHZ = Decimal('6000.5')
CONTROL_OPERATIONS = {'设置频率': 'frequency', '开启转发': 'enable',
                      '停止转发': 'stop', '查询状态': 'status'}


def business_frequency_plan(role, center_mhz):
    """Explicit local profiles, separate from any remote board state."""
    choices = {'sender': BUSINESS_TX_CENTERS, 'receiver': BUSINESS_RX_CENTERS}
    if role not in choices:
        raise ValueError('业务角色须为 sender / receiver')
    try:
        center = Decimal(str(center_mhz))
    except InvalidOperation as error:
        raise ValueError('业务中心频率无效') from error
    if not center.is_finite() or center not in tuple(map(Decimal, choices[role])):
        raise ValueError('本阶段业务中心仅支持 '+ ' / '.join(choices[role])+' MHz')
    center_hz = int(center*1_000_000)
    # Preserve the original 1000.5 MHz / 1000.75 MHz RX operating offset.
    offset_hz = 500_000 if role == 'sender' else -250_000
    return dict(center_hz=center_hz, lo_hz=center_hz-offset_hz, offset_hz=offset_hz)


def frequency_plan(input_mhz, output_mhz):
    """UI plan, exact to one Hz. This is not a hardware range authorization."""
    result = {}
    for key, value in (('input_hz', input_mhz), ('output_hz', output_mhz)):
        try:
            if len(str(value)) > 32:
                raise ValueError('频率数值过长')
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError('请输入有效频率') from exc
        if not number.is_finite():
            raise ValueError('请输入有限频率值')
        if not MIN_CENTER_MHZ <= number <= MAX_CENTER_MHZ:
            raise ValueError('频率范围：70.5–6000.5 MHz')
        # Keep every accepted input digit: Decimal's default context could
        # otherwise round a long fractional tail away before this check.
        with localcontext() as context:
            context.prec = 64
            hz = number * 1_000_000
        if hz != hz.to_integral_value():
            raise ValueError('最多支持 6 位小数（1 Hz）')
        result[key] = int(hz)
    return result


def format_mhz(hz):
    if hz % 1_000_000 == 0:
        return str(hz // 1_000_000)
    return format(Decimal(hz) / 1_000_000, 'f').rstrip('0').rstrip('.')


def command_request(input_mhz, output_mhz, sequence, operation='frequency'):
    """Encode only exactly representable legacy LO values; never round."""
    if operation not in CONTROL_OPERATIONS.values():
        raise ValueError('未知遥控操作')
    plan = frequency_plan(input_mhz, output_mhz)
    incoming, outgoing = plan['input_hz']-500_000, plan['output_hz']-500_000
    if incoming % 1_000_000 or outgoing % 1_000_000:
        raise ValueError('方案已保存；此精度需要扩展遥控报文，当前不能编码发送。')
    if type(sequence) is not int or not 0 <= sequence <= 255:
        raise ValueError('指令序号须为 0–255 的整数')
    request = dict(rx_mhz=incoming//1_000_000,
                   tx_mhz=outgoing//1_000_000, air_seq=sequence)
    if operation != 'frequency':
        request['operation'] = operation
    return request


def relay_snapshot_view(relay, now):
    """Format actual ACK fields; elapsed wall time can only reduce the estimate."""
    def number(value):
        return type(value) in (int, float) and math.isfinite(value)
    received = relay.get('snapshot_received_at')
    timestamp = (datetime.fromtimestamp(received, timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                 if number(received) and 0 <= received <= 253402214400 else '未提供')
    lines = [f'状态快照 · 接收 {timestamp}（非持续监控）']
    valid = relay.get('valid') is True
    gains, atten = relay.get('rx_gain_db'), relay.get('tx_attenuation_mdb')
    if valid and type(relay.get('mode')) is int and all(
            isinstance(values, (list, tuple)) and len(values) == 2 and
            all(type(v) is int for v in values) for values in (gains, atten)):
        lines += [f'实际 mode {relay["mode"]} · RX 增益 {gains[0]} / {gains[1]} dB',
                  f'TX 衰减 {atten[0]/1000:g} / {atten[1]/1000:g} dB']
    else:
        lines.append('模式 / 电平回读无效，实际值未知')
    lower = relay.get('remaining_lower_bound_ms')
    remaining = (max(0, lower-max(0, now-received)*1000)
                 if number(lower) and lower >= 0 and number(received) else 0)
    expired = not valid or relay.get('lease_active') is not True or remaining <= 0
    if relay.get('mute_fault'):
        lines.append('静音故障锁存 · 需处理后重新查询')
        expired = True
    if relay.get('lease_active') is True:
        lines.append(f'保守剩余 {math.floor(remaining/1000)} 秒' if not expired else '快照租期已过期或无法估计 · 待查询')
    else:
        lines.append('快照未报告有效租期 · 当前状态待查询')
    if relay.get('lease_expired'):
        lines.append('板端报告曾到期')
    return dict(body='\n'.join(lines), expired=expired)


def device_choices(ports, aliases):
    """Local historical labels aid selection, never establish device identity."""
    devices = {}
    fingerprints = [(p.get('vid'), p.get('pid'), p.get('serial')) for p in ports]
    for port, fingerprint in zip(ports, fingerprints):
        if port.get('vid') is None:  # Bluetooth / non-USB serial ports.
            continue
        matches = [a for a in aliases if (a.get('vid'), a.get('pid'), a.get('serial')) == fingerprint
                   and fingerprint[2] and (not a.get('port') or a['port'] == port['port'])]
        alias = matches[0] if len(matches) == 1 and fingerprints.count(fingerprint) == 1 else {}
        role = alias.get('role')
        if role == 'management':
            continue
        prefix = {'sender': '发送板（上次识别）', 'receiver': '接收板（上次识别）'}.get(role)
        name = f'{prefix or "未识别 USB 串口"} · {port["port"]}'
        devices[name] = dict(port, role=role)
    return dict(sorted(devices.items(), key=lambda item: (item[1].get('role') not in ('sender', 'receiver'), item[0])))


def load_device_aliases(path=None):
    path = Path(path) if path else Path.home()/'CCSDSGroundStation'/'device_labels.json'
    try:
        result = _read_json(path)
        return [a for a in result.get('devices', []) if isinstance(a, dict)]
    except (OSError, ValueError, TypeError):
        return []


def simulated_reply(plan, outcome):
    """Presentation fixtures only: never pass these to evidence validation."""
    titles = {'success': '模拟 · 执行成功', 'failure': '模拟 · 执行失败', 'timeout': '模拟 · 等待超时'}
    details = {
        'success': f'业务输入   {format_mhz(plan["input_hz"])} MHz\n业务输出   {format_mhz(plan["output_hz"])} MHz\n\n模拟回报与目标一致。',
        'failure': '设备拒绝本次设置。\n\n未确认目标频率生效，请检查设备状态后重试。',
        'timeout': '未在等待时间内收到回报。\n\n执行结果未知，请查询状态后再决定是否重发。',
    }
    return dict(source='simulation', title=titles[outcome], body=details[outcome])


def text_bytes(text):
    size = len(text.encode('utf-8', errors='strict'))
    if not 1 <= size <= 32:
        raise ValueError('正文需要 1–32 个 UTF-8 字节；一个汉字通常占 3 字节')
    return size


def _read_json(path):
    if path.stat().st_size > 2*1024*1024:
        raise ValueError('记录过大，请选择单次事务的 result.json')
    value = json.loads(path.read_text(encoding='utf-8'))
    if type(value) is not dict:
        raise ValueError('请选择包含事务字段的 JSON 对象记录')
    return value


def load_historical_transaction(path):
    """Recheck saved RF frame bytes, not the supplied assessment/passed flag.

    The IQ is not re-demodulated here. This validates the associated report's
    bytes and transaction correlation, not the origin of the saved recording.
    Only a companion report inside this transaction's downlink folder is read.
    """
    from .tc_evidence import assess_transaction
    path = Path(path).resolve()
    result = _read_json(path)
    if result.get('probe_only') is not False or result.get('cleanup_errors') != []:
        raise ValueError('需要完整且清理正常的历史事务记录')
    report_name = str(result['rf_report']).replace('\\', '/').split('/')[-1]
    if not report_name.endswith('.json') or report_name in ('.json', '..json'):
        raise ValueError('关联回报文件名无效')
    directory = (path.parent/'downlink').resolve()
    report_path = (directory/report_name).resolve()
    if not report_path.is_relative_to(directory):
        raise ValueError('回报必须位于本次事务的 downlink 目录')
    report = _read_json(report_path)
    control = result['control']
    assessment = assess_transaction(result['requested'], control['before'],
        control['frozen'], control['spi'], report, result['dac_sequence'])
    if result.get('final_spi') != control['spi']:
        raise ValueError('前后独立频率回读不一致')
    return dict(path=str(path), report_path=str(report_path), assessment=assessment)
