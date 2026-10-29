"""Bench-only frequency adapters, separate from the commissioned GUI profiles.

No device is opened on import. Use with confirmed coax wiring and a finite relay
lease. The existing board-side 30-second TX guard is retained without renewal.
These discrete points do not certify a continuous band or an NTN air interface.
"""
from dataclasses import dataclass
import hashlib
import uuid

from sw.ground_station.business_live import _verify_runtime_binding
from sw.ground_station.protocol import generate_message_iq
from sw.ground_station.tc_hardware import CommandSource
from sw.ground_station.transport import Console
from sw.tools.rf_channel_probe import ChannelProbeReceiver


@dataclass(frozen=True)
class FrequencyPoint:
    name: str
    relay_rx_mhz: int
    relay_tx_mhz: int

    @property
    def source_lo_hz(self):
        return self.relay_rx_mhz * 1000000

    @property
    def input_center_hz(self):
        return self.source_lo_hz + 500000

    @property
    def output_center_hz(self):
        return self.relay_tx_mhz * 1000000 + 500000

    @property
    def receiver_lo_hz(self):
        return self.output_center_hz + 250000


POINTS = (
    FrequencyPoint('baseline', 901, 1000),
    FrequencyPoint('output_2450', 901, 2450),
    FrequencyPoint('s_band', 1989, 2179),
    FrequencyPoint('upper_board_band', 2450, 2900),
    FrequencyPoint('s_band_shift', 1990, 2180),
)


def validate_point(point):
    if type(point) is not FrequencyPoint or point not in POINTS:
        raise ValueError('Use an explicit bench frequency point')
    return point


class FrequencyProbeReceiver(ChannelProbeReceiver):
    RX_LO_POINTS = tuple(sorted({p.receiver_lo_hz for p in POINTS}))


class FrequencyProbeSource(CommandSource):
    def write(self, path, value, tolerance=0):
        if not self.owned or self._closed:
            raise RuntimeError('Frequency probe does not own TX configuration')
        allowed = {
            'out_altvoltage1_TX_LO_frequency': {str(p.source_lo_hz) for p in POINTS},
            'out_altvoltage1_TX_LO_powerdown': {'1'},
            'out_voltage_sampling_frequency': {'2500000'},
            'out_voltage_rf_bandwidth': {'3000000'},
            'out_voltage0_rf_port_select': {'A'},
            'out_voltage0_hardwaregain': {str(-x) for x in range(50, 90)},
            'out_voltage1_hardwaregain': {'-89'},
        }
        if not path.startswith(self.phy+'/') or str(value) not in allowed.get(path[len(self.phy)+1:], set()):
            raise ValueError('Frequency probe write is outside its bounded profile')
        _verify_runtime_binding(self)
        return Console.write(self, path, value, tolerance)

    def tune_muted(self, point):
        point = validate_point(point)
        self.verify_binding()
        self.require_idle()
        if self.prepared or self.read(self.phy+'/out_altvoltage1_TX_LO_powerdown') != '1':
            raise RuntimeError('Stop the owned source before retuning')
        self.owned = True
        self.mute()
        return int(self.configure_if_changed('out_altvoltage1_TX_LO_frequency', point.source_lo_hz, 10))

    def prepare_message(self, point, text, session, sequence, attenuation_db=60):
        point = validate_point(point)
        if type(attenuation_db) is not int or not 50 <= attenuation_db <= 89:
            raise ValueError('Bench attenuation must be an integer in 50..89 dB')
        iq, manifest = generate_message_iq(text, session, sequence)
        raw = iq.tobytes()
        manifest = dict(manifest, sha256=hashlib.sha256(raw).hexdigest(),
                        input_center_hz=point.input_center_hz,
                        output_center_hz=point.output_center_hz,
                        source_lo_hz=point.source_lo_hz)
        self.remote = '/tmp/frequency_probe_'+uuid.uuid4().hex[:12]
        self._prepare_waveform(raw, manifest, lo_hz=point.source_lo_hz,
                               attenuation_db=attenuation_db, block_samples=len(iq))
        return manifest
