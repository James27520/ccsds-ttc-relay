"""Explicit, process-local binding for the wired DAC -> RX experiment.

Probe performs status/identity reads only. No identity is installed on a board,
and no COM name or permanent physical role is inferred. Empty stable IDs are
accepted only by this RX session adapter, never by ordinary Console.

Console.run is an internal trusted implementation API, not a shell sandbox for
arbitrary Python callers. Public write/upload gate configuration and TX startup.
ADDA has no boot nonce: its USB and uptime continuity check cannot authenticate
clones or distinguish every reboot within the UART timing uncertainty.
"""
import copy
import re
import time
import uuid

from .transport import Console
from .telemetry import TelemetrySerial

_PROCESS_TOKEN = uuid.uuid4().hex
_BINDINGS = {}  # one-use probe tokens, valid only in this application process
_NAMES = ('for d in /sys/bus/iio/devices/iio:device*; do '
          'test -f "$d/name" && printf "%s %s\\n" "$d" "$(cat "$d/name")"; done')
_USB_KEYS = ('port', 'usb_vid', 'usb_pid', 'usb_serial', 'usb_location', 'hwid')
_RX_KEYS = _USB_KEYS + ('linux_boot_id', 'model', 'iio_serial')


def _usb_identity(port):
    from serial.tools import list_ports
    matches = [p for p in list_ports.comports() if p.device == port]
    if len(matches) != 1 or matches[0].vid is None or matches[0].pid is None:
        raise RuntimeError('USB session port is unavailable or ambiguous')
    p = matches[0]
    return dict(port=p.device, usb_vid=p.vid, usb_pid=p.pid,
                usb_serial=p.serial_number or '',
                usb_location=getattr(p, 'location', None) or '', hwid=p.hwid or '')


def _open_usb(port, write_timeout):
    import serial
    handle = serial.Serial(port=None, baudrate=115200, timeout=.05,
                           write_timeout=write_timeout, xonxoff=False,
                           rtscts=False, dsrdtr=False)
    try:
        handle.dtr = handle.rts = False
        handle.port = port
        handle.open()
        return handle
    except BaseException:
        handle.close()
        raise


def _one(lines, pattern, label):
    matches = [re.fullmatch(pattern, line) for line in lines]
    matches = [m for m in matches if m]
    if len(matches) != 1:
        raise RuntimeError('Missing or ambiguous '+label)
    return matches[0]


class SessionRxConsole(Console):
    """Current-boot RX adapter; trusted run() is retained for capture jobs."""
    def __init__(self, port, record=lambda **event: None):
        self.record = record
        self._console_synchronized = True
        self._closed = False
        self._writable = False
        self._fingerprint = _usb_identity(port)
        self.port = _open_usb(port, 3)
        try:
            self.info = self._identify()
            self._fingerprint = {k: self.info[k] for k in _RX_KEYS}
        except BaseException:
            self.close()
            raise

    def _identify(self):
        usb = _usb_identity(self._fingerprint['port'])
        if any(usb[k] != self._fingerprint[k] for k in _USB_KEYS):
            raise RuntimeError('Receiver USB identity changed')
        boot = self.read('/proc/sys/kernel/random/boot_id')
        if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot):
            raise RuntimeError('Receiver Linux boot_id unavailable; log in first')
        text = self.run('iio_info -u local:', timeout=12)
        if 'ad9361-phy' not in text or 'cf-ad9361-lpc' not in text:
            raise RuntimeError('Receiver is not a supported Pluto Linux SDR')
        model = re.search(r'\bhw_model:[ \t]*([^\r\n]*)', text)
        serial = re.search(r'\bhw_serial:[ \t]*([^\r\n]*)', text)
        if not model or not model[1].strip():
            raise RuntimeError('Receiver model unavailable')
        names = self.run(_NAMES)
        mapping = {}
        for path, name in re.findall(r'^(/sys/bus/iio/devices/iio:device\d+) (\S+)\r?$',
                                     names, re.M):
            if name in mapping:
                raise RuntimeError('Ambiguous IIO device mapping')
            mapping[name] = path
        self.phy, self.tx, self.rx = (mapping[n] for n in (
            'ad9361-phy', 'cf-ad9361-dds-core-lpc', 'cf-ad9361-lpc'))
        self.debug = '/sys/kernel/debug/iio/'+self.phy.rsplit('/', 1)[1]
        if _usb_identity(usb['port']) != usb:
            raise RuntimeError('Receiver USB changed during probe')
        return dict(usb, linux_boot_id=boot, model=model[1].strip(),
                    iio_serial=serial[1].strip() if serial else '',
                    identity_scope='current process, Linux boot and USB session; RX only',
                    physical_role='user-selected wired receiver; not permanently authenticated')

    def verify_binding(self):
        if self._closed:
            raise RuntimeError('Receiver binding is closed or invalidated')
        try:
            current = self._identify()
            if any(current[k] != self._fingerprint[k] for k in _RX_KEYS):
                raise RuntimeError('Receiver boot/model/IIO/USB binding changed')
            return True
        except BaseException:
            self.close()
            raise

    def write(self, path, value, tolerance=0):
        if not self._writable or self._closed:
            raise RuntimeError('RX session is not bound for configuration')
        allowed = {
            self.phy+'/in_voltage_sampling_frequency': {'2500000'},
            self.phy+'/in_voltage_rf_bandwidth': {'3000000'},
            self.phy+'/in_voltage0_gain_control_mode': {'manual'},
            self.phy+'/in_voltage1_gain_control_mode': {'manual'},
            self.phy+'/in_voltage0_hardwaregain': {'20'},
            self.phy+'/in_voltage1_hardwaregain': {'20'},
            self.phy+'/in_voltage0_rf_port_select': {'A_BALANCED'},
            self.phy+'/out_altvoltage0_RX_LO_frequency': {'90000000'},
            self.phy+'/out_altvoltage1_TX_LO_powerdown': {'1'},
            self.phy+'/out_voltage0_hardwaregain': {'-89'},
            self.phy+'/out_voltage1_hardwaregain': {'-89'},
            self.rx+'/buffer/enable': {'0'},
        }
        if str(value) not in allowed.get(path, set()):
            raise ValueError('RX session allows only its fixed RX point and TX shutdown')
        self.verify_binding()
        return super().write(path, value, tolerance)

    def upload(self, *args, **kwargs):
        raise ValueError('Upload is forbidden on the RX session')

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._writable = False
        self.port.close()


def _tmstatus(lines):
    tx = _one(lines, r'TM_TX enabled=([01]) seq=(\d+) pending=([01]) stopping=([01]) '
                    r'status=([0-9a-fA-F]{8}) diag=([0-9a-fA-F]{8})', 'TM_TX status')
    dac = _one(lines, r'TM_DAC verified=([01]) finished=([01]) '
                     r'diagnostic=([0-9a-fA-F]{8}) rc=0', 'TM_DAC status')
    fields = dict(zip(('enabled', 'seq', 'pending', 'stopping'),
                      (int(tx[i]) for i in range(1, 5))))
    if fields['seq'] > 0xffffffff:
        raise RuntimeError('TM_TX sequence out of range')
    fields.update(status=int(tx[5], 16), diag=int(tx[6], 16),
                  dac_verified=int(dac[1]), dac_finished=int(dac[2]),
                  dac_diagnostic=int(dac[3], 16))
    return fields


class SessionAdda(TelemetrySerial):
    """Current firmware/USB/uptime binding with just three control operations."""
    def __init__(self, port, record=lambda **event: None):
        self.record = record
        self._closed = False
        self._writable = False
        self._fingerprint = _usb_identity(port)
        self._boot_interval = None
        self._uptime = None
        self.port = _open_usb(port, 1)
        try:
            self._check_identity()
            self.info = dict(self._fingerprint, model='Z7ADDALite telemetry controller / TM1',
                             identity_scope='current process, USB and uptime continuity; no boot nonce',
                             physical_role='user-selected wired DAC source; not permanently authenticated')
        except BaseException:
            self.close()
            raise

    def _command(self, command):
        if self._closed:
            raise RuntimeError('ADDA binding is closed or invalidated')
        if command not in ('status', 'telemetry', 'tmstatus'):
            if command not in ('tmclear', 'tmsend', 'tmstop') or not self._writable:
                raise ValueError('ADDA session command refused')
        lines = self._exchange(command)
        if any(x.startswith('BOOT ') for x in lines):
            self.close()
            raise RuntimeError('ADDA restarted during session')
        return lines

    def status(self):
        lines = self._command('status')
        _one(lines, r'CONTROLLER auto=[01] capture_state=\d+ capture_valid=[01] consumed=[01]',
             'telecontrol firmware')
        return _one(lines, r'STATUS network=[^\r\n]+', 'controller status')[0]

    def tmstatus(self):
        return _tmstatus(self._command('tmstatus'))

    def _check_identity(self):
        if _usb_identity(self._fingerprint['port']) != self._fingerprint:
            raise RuntimeError('ADDA USB identity changed')
        self.status()
        self.tmstatus()
        before = time.monotonic()
        snapshot = self.query()
        after = time.monotonic()
        uptime = snapshot['uptime_ms']
        # A TM1 sample was generated within this command's send/receive window.
        # Millisecond quantization expands the inferred boot interval by 1 ms.
        interval = (before-uptime/1000-.001, after-uptime/1000+.001)
        if self._boot_interval is not None:
            interval = (max(interval[0], self._boot_interval[0]),
                        min(interval[1], self._boot_interval[1]))
            if uptime < self._uptime or interval[0] > interval[1]:
                raise RuntimeError('ADDA uptime continuity lost; probe a new session')
        if _usb_identity(self._fingerprint['port']) != self._fingerprint:
            raise RuntimeError('ADDA USB identity changed during probe')
        self._boot_interval, self._uptime = interval, uptime

    def verify_binding(self):
        if self._closed:
            raise RuntimeError('ADDA binding is closed or invalidated')
        try:
            self._check_identity()
            return True
        except BaseException:
            self.close()
            raise

    def _control(self, command):
        if not self._writable or self._closed:
            raise RuntimeError('ADDA session is not bound for control')
        # Caller verifies binding before arming RX. In particular tmsend must
        # immediately follow RX-ready, without spending its finite capture
        # window on three extra queries. An unsuccessful send is never retried.
        return self._command(command)

    def clear(self):
        return self._control('tmclear')

    def send(self):
        return self._control('tmsend')

    def stop(self):
        return self._control('tmstop')

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._writable = False
        self.port.close()


def _close_all(*connections):
    for connection in connections:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass  # Cleanup must still reach the other owned port.


def probe_pair(rx_port, adda_port, record=lambda **event: None):
    """Read-only probe, always close both ports; returned dict is JSON serializable."""
    if rx_port.casefold() == adda_port.casefold():
        raise ValueError('Receiver and ADDA must use distinct ports')
    receiver = adda = None
    try:
        receiver = SessionRxConsole(rx_port, record)
        adda = SessionAdda(adda_port, record)
        binding = dict(schema=1, process_token=_PROCESS_TOKEN, token=uuid.uuid4().hex,
                       receiver=copy.deepcopy(receiver.info), adda=copy.deepcopy(adda.info))
        _BINDINGS[binding['token']] = dict(binding=copy.deepcopy(binding),
            boot_interval=adda._boot_interval, uptime=adda._uptime)
        record(kind='rf_session_probe', binding=binding)
        return binding
    finally:
        _close_all(receiver, adda)


def open_pair(binding, record=lambda **event: None):
    """Consume a process-local probe token, reopen and revalidate before control."""
    if not isinstance(binding, dict):
        raise ValueError('Invalid RF binding')
    saved = _BINDINGS.pop(binding.get('token', ''), None)
    if (saved is None or binding != saved['binding'] or
            binding.get('process_token') != _PROCESS_TOKEN):
        raise RuntimeError('RF probe binding expired, modified or already used')
    receiver = adda = None
    try:
        receiver = SessionRxConsole(binding['receiver']['port'], record)
        if any(receiver.info[k] != binding['receiver'][k] for k in _RX_KEYS):
            raise RuntimeError('Receiver changed since read-only probe')
        adda = SessionAdda(binding['adda']['port'], record)
        if any(adda.info[k] != binding['adda'][k] for k in _USB_KEYS):
            raise RuntimeError('ADDA changed since read-only probe')
        adda._boot_interval, adda._uptime = saved['boot_interval'], saved['uptime']
        receiver.verify_binding()
        adda.verify_binding()
        receiver._writable = adda._writable = True
        record(kind='rf_session_bound', receiver=receiver.info, adda=adda.info)
        return receiver, adda
    except BaseException:
        _close_all(receiver, adda)
        raise
