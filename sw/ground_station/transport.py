"""Bounded DEBUG-console transport for the existing Pluto Linux boards.

No board is opened on import. Selection is explicit; Linux/IIO identity is read
before any configuration. All generated paths and shell values are internal.
"""
import hashlib
import math
import re
import time
import uuid

MAX_RESPONSE_BYTES = 1024 * 1024


def _board_identity(info, usb_serial):
    """Prefer a nonempty same-line IIO serial, then a stable USB serial.

    Some firmware prints an empty hw_serial line. Horizontal whitespace is
    deliberate: matching across its newline would mistake fw_version for ID.
    """
    serial_match = re.search(r'\bhw_serial:[ \t]*([^\r\n]*)', info)
    iio_serial = serial_match[1].strip() if serial_match else ''
    if iio_serial:
        return iio_serial, 'iio'
    if (isinstance(usb_serial, str) and len(usb_serial) >= 8 and
            re.fullmatch(r'[A-Za-z0-9_-]+', usb_serial)):
        return usb_serial, 'usb'
    raise RuntimeError('未读取到稳定IIO或USB序列标识，拒绝配置')


def discover_devices():
    from serial.tools import list_ports
    return [dict(port=p.device, label=f"{p.device} · {p.description} · {p.serial_number or '无USB序列号'}",
                 usb_serial=p.serial_number, hwid=p.hwid)
            for p in list_ports.comports() if p.vid is not None]


class Console:
    def __init__(self, port, record=lambda **event: None):
        import serial
        from serial.tools import list_ports
        matches = [p for p in list_ports.comports() if p.device == port]
        if len(matches) != 1 or matches[0].vid is None:
            raise ValueError("请选择当前可用的USB调试串口")
        self.record = record
        self.info = dict(port=port, usb_serial=matches[0].serial_number, hwid=matches[0].hwid)
        self.port = serial.Serial(port=None, baudrate=115200, timeout=.05, write_timeout=3)
        self.port.dtr = self.port.rts = False
        self.port.port = port
        self.port.open()
        try:
            self.port.write(b'\n')
            time.sleep(.2)
            initial = self.port.read(self.port.in_waiting).decode('utf-8', 'replace')
            # Root login on the supplied boards needs no password. A password
            # prompt is not answered or logged by this application.
            if re.search(r'login:\s*$', initial):
                self.port.write(b'root\n')
                time.sleep(.3)
                initial = self.port.read(self.port.in_waiting).decode('utf-8', 'replace')
            if re.search(r'[Pp]assword:\s*$', initial):
                raise RuntimeError("板端需要登录，请先在DEBUG终端完成登录后再连接")
            info = self.run('iio_info -u local:', timeout=12)
            if 'ad9361-phy' not in info or 'cf-ad9361-lpc' not in info:
                raise RuntimeError("该端口不是支持的Pluto Linux SDR；请核对设备")
            identity, identity_source = _board_identity(info, self.info['usb_serial'])
            model = re.search(r'hw_model:[ \t]*([^\r\n]*)', info)
            self.info.update(serial=identity, identity_source=identity_source,
                             model=model.group(1).strip() if model else 'Pluto Linux / AD936x')
            names = self.run('for d in /sys/bus/iio/devices/iio:device*; do '
                             'test -f "$d/name" && printf "%s %s\\n" "$d" "$(cat "$d/name")"; done')
            mapping = {}
            for line in names.splitlines():
                m = re.fullmatch(r'(/sys/bus/iio/devices/iio:device\d+) (\S+)', line.strip())
                if m:
                    mapping[m[2]] = m[1]
            self.phy = mapping['ad9361-phy']
            self.tx = mapping['cf-ad9361-dds-core-lpc']
            self.rx = mapping['cf-ad9361-lpc']
            self.debug = '/sys/kernel/debug/iio/' + self.phy.rsplit('/', 1)[1]
            self.record(kind='identity', **self.info)
        except Exception:
            self.port.close()
            raise

    def run(self, command, timeout=8):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Console timeout must be positive and finite')
        token = uuid.uuid4().hex[:12]
        wrapper = ("printf '\\nGS_BEGIN_%s\\n'; ( %s ); gs_rc=$?; "
                   "printf '\\nGS_END_%s_%%s\\n' \"$gs_rc\"") % (token, command, token)
        data_out = wrapper.encode('ascii') + b'\n'
        if len(data_out) > 900:
            raise ValueError('Console command exceeds 900-byte bound')
        if self.port.write(data_out) != len(data_out):
            self.port.write(b'\x03\n')
            raise RuntimeError('串口命令未完整写入，当前操作未确认完成')
        data = bytearray()
        deadline = time.monotonic() + timeout
        end = re.compile(rb'(?:^|\r?\n)GS_END_' + token.encode() + rb'_(\d+)\r?\n')
        match = None
        while time.monotonic() < deadline:
            packet = self.port.read(max(1, min(self.port.in_waiting, 8192)))
            if len(data) + len(packet) > MAX_RESPONSE_BYTES:
                self.port.write(b'\x03\n')
                raise RuntimeError('板端响应超过1 MiB上限，当前操作未确认完成')
            data.extend(packet)
            match = end.search(data)
            if match:
                break
        begin = re.search(rb'(?:^|\r?\n)GS_BEGIN_' + token.encode() + rb'\r?\n', data)
        # Frame boundaries are byte offsets; UTF-8 characters before an END
        # marker must not shift the slice or leak a marker into the response.
        output_bytes = data[begin.end():match.start()] if begin and match else data
        output = output_bytes.decode('utf-8', 'replace').strip()
        rc = int(match[1]) if match and begin else None
        self.record(kind='console', command=command[:160], rc=rc,
                    output=output[:2000], output_chars=len(output))
        if rc is None:
            self.port.write(b'\x03\n')
            time.sleep(.1)
            raise TimeoutError("板端响应超时，当前操作未确认完成")
        if rc:
            raise RuntimeError(f"板端命令失败(rc={rc}): {output[-500:]}")
        return output

    def read(self, path):
        return self.run('cat ' + path)

    def write(self, path, value, tolerance=0):
        value = str(value)
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
            raise ValueError('Invalid sysfs value')
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError('Readback tolerance must be finite and nonnegative')
        number = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
        expected_numeric = re.fullmatch(number, value)
        if value.lower() in ('nan', 'inf', '-inf', 'infinity', '-infinity') or (
                expected_numeric and not math.isfinite(float(value))):
            raise ValueError('Sysfs numeric value must be finite')
        self.run(f'printf %s {value} > {path}')
        got = self.read(path)
        if expected_numeric:
            # Only hardwaregain attributes document a dB suffix. Other units,
            # trailing text and NaN cannot establish a successful numeric write.
            suffix = r'(?: dB)?' if path.endswith('_hardwaregain') else ''
            match = re.fullmatch('(' + number + ')' + suffix, got)
            if (match is None or not math.isfinite(float(match[1])) or
                    abs(float(match[1]) - float(value)) > tolerance):
                raise RuntimeError(f'设置读回不一致: {path.rsplit("/", 1)[-1]}={got}')
        elif got != value:
            raise RuntimeError(f'设置读回不一致: {path.rsplit("/", 1)[-1]}={got}')
        return got

    def upload(self, path, data, progress=None):
        self.run(f'test ! -e {path} && : > {path}')
        encoded = data.hex()
        for start in range(0, len(encoded), 512):
            chunk = encoded[start:start+512]
            self.run(f"printf %s '{chunk}' | xxd -r -p >> {path}")
            if progress:
                progress(min(1., (start+512)/len(encoded)))
        digest = hashlib.sha256(data).hexdigest()
        got = self.run(f'wc -c < {path}; sha256sum {path}').splitlines()
        if len(got) != 2 or int(got[0]) != len(data) or got[1].split()[0] != digest:
            raise RuntimeError('板端上传校验失败')
        return digest

    def download(self, path, size):
        info = self.run(f'wc -c < {path}; sha256sum {path}').splitlines()
        if len(info) != 2 or int(info[0]) != size:
            raise RuntimeError('采样长度不符')
        encoded = self.run('xxd -p ' + path, timeout=max(12, 2*size/6000+8))
        hex_data = ''.join(encoded.split())
        if re.fullmatch(r'[0-9a-fA-F]*', hex_data) is None:
            raise ValueError('采样传输包含非十六进制字符')
        if len(hex_data) != size*2:
            raise RuntimeError('采样十六进制长度不符')
        raw = bytes.fromhex(hex_data)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != info[1].split()[0]:
            raise RuntimeError('采样传输校验失败')
        return raw

    def require_idle(self):
        if self.read(self.tx+'/buffer/enable') != '0' or self.read(self.rx+'/buffer/enable') != '0':
            raise RuntimeError('板卡已有采集或发送进程；请先停止原程序')
        for attr in ('bist_prbs', 'bist_tone', 'loopback'):
            if self.read(self.debug+'/'+attr) != '0':
                raise RuntimeError('板卡测试信号/环回已开启，拒绝接管')

    def mute(self):
        # Separate attempts ensure an attenuation failure cannot skip LO shutdown.
        errors = []
        for path, value in [(self.phy+'/out_altvoltage1_TX_LO_powerdown', 1),
                            (self.phy+'/out_voltage0_hardwaregain', -89),
                            (self.phy+'/out_voltage1_hardwaregain', -89)]:
            try:
                self.write(path, value)
            except Exception as exc:
                errors.append(str(exc))
        try:
            self.run(f'for f in {self.tx}/out_altvoltage*_scale; do echo 0 > "$f" || exit 1; done')
            scales = self.run(f'cat {self.tx}/out_altvoltage*_scale').split()
            if not scales or any(float(x) != 0 for x in scales):
                raise RuntimeError('DDS未清零')
        except Exception as exc:
            errors.append(str(exc))
        if errors:
            raise RuntimeError('停发未完全确认: ' + '; '.join(errors))

    def close(self):
        self.port.close()
