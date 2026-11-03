#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Receive-only AD9361 check. Does not create TX buffers or guarantee RF mute.

Stop other SDR programs before running. Default: RX 900 MHz, expected CMU
tone 900.100 MHz. Toggle the CMU source to compare fresh per-block statistics.
Reports raw-count levels, not calibrated dBm or dBFS. Does not certify no loss.
"""
import argparse
import json
import re
import subprocess
import time
import traceback
from pathlib import Path


def find_uri(iio):
    try:
        contexts = dict(iio.scan_contexts())
    except Exception:
        contexts = {}
    if not any(u.startswith('usb:') for u in contexts):
        result = subprocess.run(['iio_info', '-s'], capture_output=True, text=True,
                                errors='replace', timeout=15)
        for line in (result.stdout + result.stderr).splitlines():
            match = re.search(r'\[(usb:[^\]\s]+)\]', line)
            if match:
                contexts[match.group(1)] = line
    for uri, name in contexts.items():
        print('FOUND:', uri, name, flush=True)
    candidates = [u for u, name in contexts.items() if u.startswith('usb:')
                  and any(t in str(name).lower() for t in ('pluto', 'ad936', 'ldsdr', 'fmcomms'))]
    if len(candidates) != 1:
        raise RuntimeError('Need exactly one USB SDR; run iio_info -s and specify --uri if needed')
    return candidates[0]


def analyze(np, x, rate, expected_offset):
    x = np.asarray(x)
    if x.ndim != 1 or x.size < 8 or not np.isfinite(x).all():
        raise ValueError('Invalid single-channel I/Q array')
    rms = float(np.sqrt(np.mean(np.abs(x) ** 2)))
    dc = complex(np.mean(x))
    centered = x - dc
    ac_rms = float(np.sqrt(np.mean(np.abs(centered) ** 2)))
    window = np.hanning(x.size)
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(centered * window))) / window.sum()
    freq = np.fft.fftshift(np.fft.fftfreq(x.size, 1.0 / rate))
    spacing = rate / x.size
    # Exclude the DC neighborhood when finding the dominant non-DC peak.
    valid = (np.abs(freq) >= max(500.0, 3 * spacing)) & (np.abs(freq) < rate * 0.45)
    peak_idx = np.flatnonzero(valid)[np.argmax(spectrum[valid])]
    target = np.abs(freq - expected_offset) <= max(5000, 3 * spacing)
    if not target.any():
        raise ValueError('Expected signal is outside sampled bandwidth')
    target_peak = float(spectrum[target].max())
    def db(value):
        return float(20 * np.log10(max(value, 1e-15)))
    return {
        'samples': int(x.size), 'rms_counts': rms, 'ac_rms_counts': ac_rms,
        'ac_level_db_counts': db(ac_rms), 'dc_i': dc.real, 'dc_q': dc.imag,
        'peak_offset_hz': float(freq[peak_idx]), 'peak_counts': float(spectrum[peak_idx]),
        'target_peak_db_counts': db(target_peak), 'fft_bin_hz': spacing,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uri', default='auto')
    p.add_argument('--rx-hz', type=int, default=900000000)
    p.add_argument('--signal-hz', type=int, default=900100000)
    p.add_argument('--rate', type=int, default=2500000)
    p.add_argument('--bandwidth', type=int, default=1500000)
    p.add_argument('--rx-gain', type=float, default=10)
    p.add_argument('--channel', type=int, choices=[0, 1], default=0)
    p.add_argument('--seconds', type=int, default=120)
    p.add_argument('--output', default='rx_check_last.npz')
    a = p.parse_args()
    if min(a.rx_hz, a.signal_hz, a.rate, a.bandwidth, a.seconds) <= 0:
        p.error('Frequencies, rate, bandwidth and duration must be positive')
    offset = a.signal_hz - a.rx_hz
    if abs(offset) < 5000 or abs(offset) + 5000 >= min(a.rate, a.bandwidth) / 2:
        p.error('Choose a tone at least 5 kHz away from DC, inside the RX bandwidth')

    import numpy as np
    import iio
    import adi
    radio = None
    last = None
    status = 0
    try:
        uri = find_uri(iio) if a.uri == 'auto' else a.uri
        print('CONNECT', uri, flush=True)
        radio = adi.ad9361(uri=uri)
        settings = [
            ('rx_enabled_channels', [a.channel]), ('sample_rate', a.rate),
            ('rx_rf_bandwidth', a.bandwidth), ('rx_lo', a.rx_hz),
            (f'gain_control_mode_chan{a.channel}', 'manual'),
            (f'rx_hardwaregain_chan{a.channel}', a.rx_gain), ('rx_buffer_size', 32768),
        ]
        for name, value in settings:
            print('SET', name, '=', value, flush=True)
            setattr(radio, name, value)
        rate, lo = int(radio.sample_rate), int(radio.rx_lo)
        if rate != a.rate or lo != a.rx_hz:
            raise RuntimeError(f'Readback mismatch: sample_rate={rate}, rx_lo={lo}')
        print(f'RX ONLY: LO={lo} Hz; expected offset={offset:+d} Hz; logical channel={a.channel}', flush=True)
        print('Toggle CMU source ON/OFF/ON. Each printed measurement uses a NEW block.', flush=True)
        print('Levels are relative digital counts, NOT dBm/dBFS. No TX buffer is submitted.', flush=True)
        start = time.monotonic()
        next_report = start
        blocks = 0
        while time.monotonic() - start < a.seconds:
            last = np.asarray(radio.rx()).copy()
            blocks += 1
            now = time.monotonic()
            if now >= next_report:
                stats = analyze(np, last, rate, offset)
                print(f't={now-start:6.1f}s block={blocks} '
                      f'RMS={stats["rms_counts"]:.2f} AC_RMS={stats["ac_rms_counts"]:.2f} '
                      f'peak_offset={stats["peak_offset_hz"]:+.0f} Hz '
                      f'target_peak={stats["target_peak_db_counts"]:.1f} dB(counts)', flush=True)
                next_report = now + 1
    except KeyboardInterrupt:
        print('Stopped by user.', flush=True)
    except Exception:
        traceback.print_exc()
        status = 1
    finally:
        if radio is not None:
            try:
                radio.rx_destroy_buffer()
            except Exception as exc:
                print('RX cleanup error:', exc)
        if last is not None:
            try:
                metadata = dict(vars(a), blocks=blocks, elapsed=time.monotonic()-start,
                                uri_used=uri, sample_rate_readback=rate, rx_lo_readback=lo)
                np.savez(a.output, iq=last, metadata_json=json.dumps(metadata))
                print('Saved last received I/Q block:', Path(a.output).resolve())
            except Exception as exc:
                print('Could not save I/Q:', exc)
                status = 1
    return status


if __name__ == '__main__':
    raise SystemExit(main())
