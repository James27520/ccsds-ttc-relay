"""Bounded, RX-only four-scan-channel probe; no automatic port/channel choice.

Call configure(), then capture() -> (raw4, metadata). raw4 has 32768 rows
of little-endian sign-extended 12-bit [I1,Q1,I2,Q2]. Split before passing
either channel to the established business decoder. No hardware is opened
at import time, and all board files live in a private /tmp directory.
"""
import hashlib
import re
import shlex
import time
import uuid

import numpy as np

from sw.ground_station.rf_session import SessionRxConsole
from sw.ground_station.transport import Console
from sw.ground_station.protocol import decode_capture

SAMPLES = 32768
RAW_BYTES = SAMPLES * 8
FS = 2500000


def split_iq_channels(raw):
    """Validate one fixed snapshot; return I1/Q1 and I2/Q2 packed bytes."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ValueError('Snapshot must contain binary IQ bytes')
    raw = bytes(raw)
    if len(raw) != RAW_BYTES:
        raise ValueError(f'Four-channel snapshot requires exactly {RAW_BYTES} bytes')
    values = np.frombuffer(raw, dtype='<i2').reshape(SAMPLES, 4)
    if np.any(values < -2048) or np.any(values > 2047):
        raise ValueError('Snapshot is not sign-extended le:S12/16>>0')
    return values[:, :2].tobytes(), values[:, 2:].tobytes()


def decode_iq_channels(raw, expected_offset_hz=-250000):
    """Decode both physical scan pairs independently, without ranking them."""
    return tuple(decode_capture(channel, expected_offset_hz=expected_offset_hz,
                                sample_rate_hz=FS)
                 for channel in split_iq_channels(raw))


class ChannelProbeReceiver(SessionRxConsole):
    """Current-boot binding with only two explicitly allowed RX LO points."""

    def _safe_idle(self):
        self.verify_binding()
        self.require_idle()
        if self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('Probe requires TX LO powerdown=1')

    def _check_format(self):
        if self.read(self.debug+'/adi,2rx-2tx-mode-enable') != '1':
            raise RuntimeError('Probe requires 2R2T mode already enabled')
        for index in range(4):
            prefix = self.rx+f'/scan_elements/in_voltage{index}'
            if (self.read(prefix+'_index') != str(index) or
                    self.read(prefix+'_type') != 'le:S12/16>>0'):
                raise RuntimeError('Four-channel RX scan layout is unsupported')

    def _read_configuration(self):
        lo = int(self.read(self.phy+'/out_altvoltage0_RX_LO_frequency'))
        if abs(lo-self.settings['rx_lo_hz_requested']) > 10:
            raise RuntimeError('Probe RX LO changed since configuration')
        for name, value in [('in_voltage_sampling_frequency', str(FS)),
                            ('in_voltage_rf_bandwidth', '3000000')]:
            if self.read(self.phy+'/'+name) != value:
                raise RuntimeError('Probe RX sample rate or bandwidth changed')
        gains = []
        for channel in (0, 1):
            prefix = self.phy+f'/in_voltage{channel}'
            if (self.read(prefix+'_gain_control_mode') != 'manual' or
                    self.read(prefix+'_rf_port_select') != 'A_BALANCED'):
                raise RuntimeError('Probe RX mode or port changed')
            gain = self.read(prefix+'_hardwaregain')
            match = re.fullmatch(r'([+-]?[0-9]+(?:\.[0-9]+)?)(?: dB)?', gain)
            if not match or float(match[1]) != self.settings['rx_gain_db_readback'][channel]:
                raise RuntimeError('Probe RX gain changed')
            gains.append(float(match[1]))
        return dict(rx_lo_hz_readback=lo, rx_gain_db_readback=gains)

    def write(self, path, value, tolerance=0):
        if not self._writable or self._closed:
            raise RuntimeError('Probe RX configuration is not owned')
        allowed = {
            self.phy+'/in_voltage_sampling_frequency': {'2500000'},
            self.phy+'/in_voltage_rf_bandwidth': {'3000000'},
            self.phy+'/out_altvoltage0_RX_LO_frequency': {'901750000', '1000750000'},
        }
        for channel in (0, 1):
            prefix = self.phy+f'/in_voltage{channel}'
            allowed[prefix+'_gain_control_mode'] = {'manual'}
            allowed[prefix+'_hardwaregain'] = {'0', '20', '30'}
            allowed[prefix+'_rf_port_select'] = {'A_BALANCED'}
        if str(value) not in allowed.get(path, set()):
            raise ValueError('Probe permits only its bounded RX configuration')
        self._safe_idle()
        return Console.write(self, path, value, tolerance)

    def configure(self, lo_hz, gain_db=30):
        if type(lo_hz) is not int or lo_hz not in (901750000, 1000750000):
            raise ValueError('Probe RX LO must be 901750000 or 1000750000 Hz')
        if type(gain_db) is not int or gain_db not in (0, 20, 30):
            raise ValueError('Probe RX gain must be 0, 20 or 30 dB')
        self.settings = None
        self._safe_idle()
        self._check_format()
        self._writable = True
        try:
            for name, value in [('in_voltage_sampling_frequency', FS),
                                ('in_voltage_rf_bandwidth', 3000000)]:
                self.write(self.phy+'/'+name, value)
            for channel in (0, 1):
                for suffix, value in [('_gain_control_mode', 'manual'),
                                      ('_hardwaregain', gain_db),
                                      ('_rf_port_select', 'A_BALANCED')]:
                    self.write(self.phy+f'/in_voltage{channel}'+suffix, value)
            got = int(self.write(self.phy+'/out_altvoltage0_RX_LO_frequency', lo_hz, 10))
            self._safe_idle()
            self._check_format()
            self.settings = dict(rx_lo_hz_requested=lo_hz, rx_lo_hz_readback=got,
                                 rx_gain_db_readback=[gain_db, gain_db],
                                 sample_rate_hz=FS, bandwidth_hz=3000000,
                                 samples_per_channel=SAMPLES,
                                 scan_order=['I1', 'Q1', 'I2', 'Q2'],
                                 scan_type='le:S12/16>>0', rf_port_select='A_BALANCED')
            return dict(self.settings)
        finally:
            self._writable = False

    def _finish_capture(self):
        directory = getattr(self, '_capture_directory', None)
        if directory is None:
            return
        self.verify_binding()
        owned = self.read(directory+'/owned').split()
        if len(owned) != 2 or not all(re.fullmatch(r'[0-9]+', x) for x in owned):
            raise RuntimeError('Probe capture process identity is incomplete')
        pid, ticks = owned
        if int(pid) <= 1 or int(ticks) <= 0:
            raise RuntimeError('Probe capture process identity is invalid')
        self.run(f'if test "$(awk \'{{print $22}}\' /proc/{pid}/stat 2>/dev/null)" = {ticks}; '
                 f'then kill -INT {pid}; fi')
        deadline = time.monotonic()+3
        while self.read(self.rx+'/buffer/enable') != '0':
            if time.monotonic() >= deadline:
                raise RuntimeError('Probe RX DMA release was not confirmed')
            time.sleep(.03)
        self._capture_directory = None

    def capture(self):
        if not getattr(self, 'settings', None):
            raise RuntimeError('Configure the probe before capture')
        if getattr(self, '_capture_directory', None):
            raise RuntimeError('Previous probe capture cleanup is incomplete')
        self._safe_idle()
        self._check_format()
        self._read_configuration()
        begin = time.monotonic()
        directory = '/tmp/channel_probe_'+uuid.uuid4().hex[:12]
        self.run('mkdir '+directory)
        script = (f'echo "$$ $(awk \'{{print $22}}\' /proc/$$/stat)" > {directory}/owned || exit 1; '
                  f'exec iio_readdev -u local: -T 1500 -b {SAMPLES} -s {SAMPLES} '
                  'cf-ad9361-lpc voltage0 voltage1 voltage2 voltage3')
        self._capture_directory = directory
        try:
            result = self.run(f'sh -c {shlex.quote(script)} > {directory}/capture.bin '
                              f'2> {directory}/err; echo $?; cat {directory}/err', timeout=5)
            if result.strip() != '0':
                raise RuntimeError('Four-channel capture failed: '+result[-180:])
            self._finish_capture()
            self._safe_idle()
            raw = self.download(directory+'/capture.bin', RAW_BYTES)
            split_iq_channels(raw)
            self._safe_idle()
            self._check_format()
            readback = self._read_configuration()
            metadata = dict(self.settings, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                            capture_seconds=time.monotonic()-begin, identity=dict(self.info))
            metadata.update(readback)
            self.run(f'rm -f {directory}/capture.bin {directory}/owned {directory}/err; rmdir {directory}')
            return raw, metadata
        finally:
            self._finish_capture()
            self._safe_idle()
