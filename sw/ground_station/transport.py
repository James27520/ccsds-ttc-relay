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
        self._console_synchronized = True
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
        if not getattr(self, '_console_synchronized', True):
            raise RuntimeError('串口恢复未确认，禁止继续发送命令；请关闭并重新连接')
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

    def upload(self, path, data, progress=None, *, mode='fast'):
        """Upload while RF is muted; verify board bytes before caller may use them.

        Fast input uses head with a 3-second raw tty read timeout. If interrupted,
        no shell/control bytes are sent until that read has timed out and the
        saved tty settings have been restored. Legacy xxd remains explicit.
        """
        if mode not in ('fast', 'legacy'):
            raise ValueError('Upload mode must be fast or legacy')
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError('Upload requires 1..1 MiB of binary data')
        data = bytes(data)
        if not 0 < len(data) <= MAX_RESPONSE_BYTES:
            raise ValueError('Upload requires 1..1 MiB of binary data')
        self.run(f'test ! -e {path} && : > {path}')
        if mode == 'fast':
            return self._upload_fast(path, data, progress)
        encoded = data.hex()
        for start in range(0, len(encoded), 512):
            chunk = encoded[start:start+512]
            self.run(f"printf %s '{chunk}' | xxd -r -p >> {path}")
            if progress:
                progress(min(1., (start+512)/len(encoded)))
        digest = self._verify_upload(path, data)
        self.record(kind='upload', mode='legacy', bytes=len(data), sha256=digest, baudrate=115200)
        return digest

    def _verify_upload(self, path, data):
        digest = hashlib.sha256(data).hexdigest()
        got = self.run(f'wc -c < {path}; sha256sum {path}').splitlines()
        if (len(got) != 2 or got[0].strip() != str(len(data)) or
                re.fullmatch(digest+r'  .+', got[1]) is None):
            raise RuntimeError('板端上传长度或SHA256校验失败')
        return digest

    def _restore_after_upload(self, token, failed):
        # Raw mode makes Ctrl-C an ordinary data byte. VMIN=0/VTIME=30 lets
        # head see EOF after 3 seconds without input, including a zero-byte send.
        # Discard queued host bytes, then leave a margin before ANY new command.
        self._console_synchronized = False
        try:
            if failed:
                try:
                    self.port.reset_output_buffer()
                except Exception:
                    pass  # Still wait for the board read timeout after USB loss.
            time.sleep(3.6 if failed else .5)
            self.port.baudrate = 115200
            self.port.reset_input_buffer()
            try:
                self._confirm_default_console(token)
            except Exception as exc:
                raise RuntimeError('上传后串口恢复115200未确认：'+str(exc)) from exc
        finally:
            try:
                self.port.baudrate = 115200
            except BaseException:
                self._console_synchronized = False
                raise

    def _upload_fast(self, path, data, progress):
        token = uuid.uuid4().hex[:12]
        tag = token.encode('ascii')
        command = (
            "( gs_stty=$(stty -g) || exit 1; "
            "trap 'stty \"$gs_stty\"' EXIT HUP INT TERM; "
            "stty -echo -opost || exit 1; printf '\\nUP_READY_%s\\n'; sleep 0.3; "
            "stty 921600 raw -echo min 0 time 30 && sleep 0.3 && printf '\\nUP_BEGIN_%s\\n' && "
            "head -c %d > %s; gs_rc=$?; "
            "printf '\\nUP_END_%s_%%s\\n' \"$gs_rc\"; sleep 0.3 )\n"
        ) % (token, token, len(data), path, token)
        payload = command.encode('ascii')
        if len(payload) > 900:
            raise ValueError('Fast upload command exceeds 900-byte bound')
        started = time.monotonic()
        error, sent = None, 0
        previous_write_timeout = self.port.write_timeout
        try:
            if self.port.write(payload) != len(payload):
                raise RuntimeError('高速上传命令未完整写入')
            remaining = self._read_marker(rb'\nUP_READY_'+tag+rb'\n', 3)
            self.port.baudrate = 921600
            self._read_marker(rb'\nUP_BEGIN_'+tag+rb'\n', 3, remaining)
            # Bound each write below the board's 3-second raw read timeout.
            # A blocked UI callback must never resume raw data after tty restore.
            self.port.write_timeout = min(1., previous_write_timeout) if previous_write_timeout is not None else 1.
            # BEGIN may already be stale when a paused host finally reads it.
            # Budget the first raw write from BEFORE the command was sent,
            # rather than granting a fresh timeout after reading that marker.
            last_write_started = started
            if progress:
                progress(0.)
            for start in range(0, len(data), 4096):
                if time.monotonic()-last_write_started >= 2:
                    raise TimeoutError('高速上传包间隔超过2秒，已停止发送剩余数据')
                chunk = data[start:start+4096]
                last_write_started = time.monotonic()
                written = self.port.write(chunk)
                if isinstance(written, int) and 0 <= written <= len(chunk):
                    sent += written
                if written != len(chunk):
                    raise RuntimeError('高速上传数据未完整写入')
                if progress:
                    progress((start+len(chunk))/len(data))
            remaining = self._read_marker(rb'\nUP_END_'+tag+rb'_', 8)
            status = bytearray()
            for _ in range(4):
                char, remaining = self._read_exact(1, 3, remaining)
                if char == b'\n':
                    break
                status.extend(char)
            else:
                raise RuntimeError('高速上传返回码过长')
            if status != b'0':
                raise RuntimeError('高速上传返回码异常：'+repr(bytes(status)))
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit also need the raw-input timeout
            # before the console can safely accept another command.
            error = exc
        restored = False
        try:
            self._restore_after_upload(token, failed=error is not None)
            restored = True
        except Exception as recovery_error:
            error = recovery_error if error is None else RuntimeError(str(error)+'；'+str(recovery_error))
        digest = hashlib.sha256(data).hexdigest()
        if error is None:
            try:
                self._verify_upload(path, data)
            except Exception as exc:
                error = exc
        try:
            self.port.write_timeout = previous_write_timeout
        except Exception as exc:
            error = exc if error is None else RuntimeError(str(error)+'；'+str(exc))
        self.record(kind='upload', mode='fast', baudrate=921600,
                    restored_baudrate=115200 if restored else None,
                    bytes=len(data), bytes_sent_confirmed=sent, sha256=digest,
                    seconds=time.monotonic()-started, success=error is None,
                    error=str(error) if error else None)
        if error is not None:
            raise error
        return digest

    def download(self, path, size, *, mode='fast'):
        """Fetch verified bytes; fast UART is temporary for each transaction.

        mode='legacy' retains the 115200 xxd path for explicit comparison or
        boards without fast UART support. A failed fast transfer never silently
        falls back: its integrity error and console recovery remain visible.
        """
        if mode not in ('fast', 'legacy'):
            raise ValueError('Download mode must be fast or legacy')
        if type(size) is not int or not 0 < size <= MAX_RESPONSE_BYTES:
            raise ValueError('Download size must be 1..1 MiB')
        info = self.run(f'wc -c < {path}; sha256sum {path}').splitlines()
        if (len(info) != 2 or info[0].strip() != str(size) or
                re.fullmatch(r'[0-9a-f]{64}  .+', info[1]) is None):
            raise RuntimeError('采样长度不符')
        digest = info[1].split()[0]
        if mode == 'fast':
            return self._download_fast(path, size, digest)
        encoded = self.run('xxd -p ' + path, timeout=max(12, 2*size/6000+8))
        hex_data = ''.join(encoded.split())
        if re.fullmatch(r'[0-9a-fA-F]*', hex_data) is None:
            raise ValueError('采样传输包含非十六进制字符')
        if len(hex_data) != size*2:
            raise RuntimeError('采样十六进制长度不符')
        raw = bytes.fromhex(hex_data)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise RuntimeError('采样传输校验失败')
        self.record(kind='download', mode='legacy', bytes=len(raw), sha256=digest, baudrate=115200)
        return raw

    def _read_marker(self, pattern, timeout, initial=b''):
        """Bounded ASCII handshake reader; never used to delimit binary data."""
        data = bytearray(initial)
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            match = re.search(pattern, data)
            if match:
                return bytes(data[match.end():])
            if len(data) > 65536:
                raise RuntimeError('高速串口握手响应超过长度限制')
            data.extend(self.port.read(max(1, min(self.port.in_waiting, 8192))))
        raise TimeoutError('高速串口握手超时')

    def _read_exact(self, size, timeout, initial=b''):
        data = bytearray(initial)
        deadline = time.monotonic()+timeout
        while len(data) < size:
            if time.monotonic() >= deadline:
                raise TimeoutError(f'高速串口数据不足：{len(data)}/{size}字节')
            data.extend(self.port.read(min(size-len(data), max(1, min(self.port.in_waiting, 8192)))))
        return bytes(data[:size]), bytes(data[size:])

    def _confirm_default_console(self, token):
        marker = 'GS_RESTORED_'+token
        # This private operation is the sole exception to the unsynchronized
        # command gate, and is called only after the relevant restore delay.
        self._console_synchronized = True
        try:
            reply = self.run('test "$(stty speed)" = 115200 && printf %s '+marker, timeout=3)
            if reply != marker:
                raise RuntimeError('未确认串口已恢复115200')
        except BaseException:
            self._console_synchronized = False
            raise

    def _restore_after_fast(self, token, failed):
        """Bounded recovery at the two known rates, always leaving host at 115200."""
        self._console_synchronized = False
        try:
            self._restore_fast_attempts(token, failed)
        finally:
            # Also cover USB removal, write failure or unsupported host baud
            # configuration before the ordinary recovery path reaches this rate.
            try:
                self.port.baudrate = 115200
            except BaseException:
                self._console_synchronized = False
                raise

    def _restore_fast_attempts(self, token, failed):
        if failed:
            # ISIG stays enabled on the board, so Ctrl-C interrupts cat and runs
            # the restoration trap even when a transfer stopped midway.
            self.port.baudrate = 921600
            self.port.write(b'\x03\n')
        time.sleep(.5)
        self.port.baudrate = 115200
        self.port.reset_input_buffer()
        try:
            self._confirm_default_console(token)
            return
        except Exception as first_error:
            # A failed speed switch/partial shell command can miss the trap.
            # One explicit recovery attempt is allowed; no open-ended scan.
            try:
                self.port.baudrate = 921600
                self.port.write(b'\x03\nstty 115200\n')
                time.sleep(.5)
            finally:
                self.port.baudrate = 115200
            self.port.reset_input_buffer()
            try:
                self._confirm_default_console(token)
            except Exception as recovery_error:
                raise RuntimeError('串口恢复115200未确认：'+str(recovery_error)) from first_error

    def _download_fast(self, path, size, digest):
        token = uuid.uuid4().hex[:12]
        tag = token.encode('ascii')
        command = (
            "( gs_stty=$(stty -g) || exit 1; "
            "trap 'stty \"$gs_stty\"' EXIT HUP INT TERM; "
            "stty -echo -opost || exit 1; printf '\\nFAST_READY_%s\\n'; sleep 0.3; "
            "stty 921600 && sleep 0.3 && printf '\\nFAST_BEGIN_%s\\n' && cat %s; "
            "gs_rc=$?; printf '\\nFAST_END_%s_%%s\\n' \"$gs_rc\"; sleep 0.3 )\n"
        ) % (token, token, path, token)
        payload = command.encode('ascii')
        if len(payload) > 900:
            raise ValueError('Fast transfer command exceeds 900-byte bound')
        started = time.monotonic()
        error = None
        raw = None
        try:
            if self.port.write(payload) != len(payload):
                raise RuntimeError('高速下载命令未完整写入')
            remaining = self._read_marker(rb'\nFAST_READY_'+tag+rb'\n', 3)
            self.port.baudrate = 921600
            remaining = self._read_marker(rb'\nFAST_BEGIN_'+tag+rb'\n', 3, remaining)
            raw, remaining = self._read_exact(size, max(8, size/92160*3+3), remaining)
            prefix = b'\nFAST_END_'+tag+b'_'
            received, remaining = self._read_exact(len(prefix), 3, remaining)
            if received != prefix:
                raise RuntimeError('高速下载结束标记损坏')
            status = bytearray()
            for _ in range(4):
                char, remaining = self._read_exact(1, 3, remaining)
                if char == b'\n':
                    break
                status.extend(char)
            else:
                raise RuntimeError('高速下载返回码过长')
            if status != b'0':
                raise RuntimeError('高速下载返回码异常：'+repr(bytes(status)))
            if hashlib.sha256(raw).hexdigest() != digest:
                raise RuntimeError('高速采样传输SHA256校验失败')
        except BaseException as exc:
            error = exc
        restored = False
        try:
            self._restore_after_fast(token, failed=error is not None)
            restored = True
        except Exception as recovery_error:
            if error is None:
                error = recovery_error
            else:
                error = RuntimeError(str(error)+'；'+str(recovery_error))
        self.record(kind='download', mode='fast', baudrate=921600,
                    restored_baudrate=115200 if restored else None,
                    bytes=size, sha256=digest, seconds=time.monotonic()-started,
                    success=error is None, error=str(error) if error else None)
        if error is not None:
            raise error
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
