#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run on RK3588: forward fresh AD9361 RX I/Q blocks to TX over USB.

Default invocation DOES transmit, using the previously discussed example:
CMU200 source 900.100 MHz -> RX LO 900 MHz -> TX LO 1000 MHz
-> CMU200 measurement 1000.100 MHz. Verify cabling and input levels first.

This is a block-forwarding demonstration, not guaranteed gap-free streaming.
Requires compatible pyadi-iio, pylibiio and numpy. Does not install packages.
"""

import argparse
import importlib
import logging
import math
import re
import subprocess
import sys
import time


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uri', default='auto',
                   help='auto scans for one USB SDR; alternatively give an explicit IIO URI')
    p.add_argument('--rx-hz', type=int, default=900_000_000)
    p.add_argument('--tx-hz', type=int, default=1_000_000_000)
    p.add_argument('--rate', type=int, default=2_500_000)
    p.add_argument('--bandwidth', type=int, default=1_500_000)
    p.add_argument('--samples', type=int, default=16384)
    p.add_argument('--seconds', type=float, default=60.0,
                   help='Approximate duration; an I/O call can block beyond it')
    p.add_argument('--rx-gain', type=float, default=10.0)
    p.add_argument('--tx-gain', type=float, default=-60.0,
                   help='TX gain/attenuation setting in dB, NOT output power in dBm')
    p.add_argument('--log', default='sdr_forward.log')
    p.add_argument('--dry-run', action='store_true', help='Show plan without opening SDR')
    a = p.parse_args()
    if min(a.rx_hz, a.tx_hz, a.rate, a.bandwidth, a.samples) <= 0:
        p.error('Frequencies, bandwidth, sample rate and block size must be positive')
    if a.rx_hz == a.tx_hz:
        p.error('This demonstration requires different RX and TX frequencies')
    if a.bandwidth > a.rate:
        p.error('Use bandwidth <= sample rate for this demonstration')
    if not math.isfinite(a.seconds) or not 0 < a.seconds <= 3600:
        p.error('Duration must be finite and in (0, 3600] seconds')
    if not math.isfinite(a.tx_gain) or not -89.75 <= a.tx_gain <= 0:
        p.error('TX setting must be in [-89.75, 0] dB')
    if not math.isfinite(a.rx_gain):
        p.error('RX gain must be finite; the device validates its supported range')
    return a


def make_logger(path):
    log = logging.getLogger('sdr_forward')
    log.setLevel(logging.INFO)
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)
    log.propagate = False
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    log.addHandler(console)
    try:
        file_handler = logging.FileHandler(path, mode='a', encoding='utf-8')
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    except OSError as exc:
        log.warning('Cannot create log file %s: %s; console logging remains active', path, exc)
    return log


def select_usb_uri(contexts):
    """Never auto-select local ADCs, network devices or an ambiguous target."""
    matches = [uri for uri, description in contexts.items()
               if uri.startswith('usb:') and any(
                   marker in str(description).lower()
                   for marker in ('pluto', 'ad936', 'ldsdr', 'fmcomms'))]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError('Multiple USB SDRs found: ' + ', '.join(matches)
                           + '. Select the intended device with --uri.')
    raise RuntimeError('No recognized USB SDR found. Check SDR power and USB data cable, '
                       'then run iio_info -s. If it lists your SDR, pass its current URI '
                       'using --uri. Do not reuse an old USB address.')


def discover_usb(iio, log):
    contexts = {}
    try:
        contexts = dict(iio.scan_contexts())
    except Exception as exc:
        log.warning('Python IIO scan failed: %s; trying iio_info -s', exc)
    # Also try the installed CLI when bindings scan no USB devices. The CLI
    # and Python bindings may load different libiio installations.
    if not any(uri.startswith('usb:') for uri in contexts):
        try:
            result = subprocess.run(['iio_info', '-s'], capture_output=True,
                                    text=True, errors='replace', timeout=15, check=False)
            output = result.stdout + '\n' + result.stderr
            log.info('iio_info -s output:\n%s', output.strip())
            for line in output.splitlines():
                match = re.search(r'\[(usb:[^\]\s]+)\]', line)
                if match:
                    contexts[match.group(1)] = line
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning('CLI scan could not complete: %s', exc)
    for uri, description in contexts.items():
        log.info('[FOUND] %s : %s', uri, description)
    return select_usb_uri(contexts)


def main():
    a = arguments()
    log = make_logger(a.log)
    log.info('=== New run: USB raw I/Q block forwarding ===')
    log.info('URI=%s; logical RX0 -> TX0; verify physical SMA mapping', a.uri)
    log.info('RX LO=%d Hz; TX LO=%d Hz; sample rate=%d S/s; bandwidth=%d Hz',
             a.rx_hz, a.tx_hz, a.rate, a.bandwidth)
    log.info('RX gain=%s dB; TX setting=%s dB (NOT dBm); duration=%s s',
             a.rx_gain, a.tx_gain, a.seconds)
    log.info('Block=%d samples (%0.3f ms of signal); no gap-free guarantee',
             a.samples, 1000 * a.samples / a.rate)
    if a.dry_run:
        log.info('DRY RUN: no device opened or modified')
        return 0

    sdr = None
    status = 0
    stage = 'load Python dependencies'

    def step(label, operation):
        nonlocal stage
        stage = label
        log.info('[STEP] %s', label)
        value = operation()
        log.info('[OK] %s%s', label, '' if value is None else ': ' + str(value))
        return value

    def write(name, value):
        step('write ' + name + ' = ' + str(value), lambda: setattr(sdr, name, value))

    def read(name):
        return step('read ' + name, lambda: getattr(sdr, name))

    try:
        adi = step('import adi (pyadi-iio)', lambda: importlib.import_module('adi'))
        np = step('import numpy', lambda: importlib.import_module('numpy'))
        iio = step('import iio (Python bindings)', lambda: importlib.import_module('iio'))
        log.info('Python=%s; adi=%s; iio=%s', sys.version.split()[0],
                 getattr(adi, '__file__', '?'), getattr(iio, '__file__', '?'))
        if a.uri == 'auto':
            a.uri = step('scan current USB SDR address', lambda: discover_usb(iio, log))
        sdr = step('connect adi.ad9361(' + a.uri + ')', lambda: adi.ad9361(uri=a.uri))

        # Separate reads from writes so the first failed operation is identifiable.
        for name in ('rx_lo', 'tx_lo', 'tx_hardwaregain_chan0', 'sample_rate'):
            read(name)
        write('tx_hardwaregain_chan0', -89.75)
        write('rx_enabled_channels', [0])
        write('tx_enabled_channels', [0])
        write('sample_rate', a.rate)
        write('rx_rf_bandwidth', a.bandwidth)
        write('tx_rf_bandwidth', a.bandwidth)
        write('rx_lo', a.rx_hz)
        write('tx_lo', a.tx_hz)
        write('gain_control_mode_chan0', 'manual')
        write('rx_hardwaregain_chan0', a.rx_gain)
        write('rx_buffer_size', a.samples)
        write('tx_cyclic_buffer', False)

        for name, expected in (('sample_rate', a.rate), ('rx_lo', a.rx_hz), ('tx_lo', a.tx_hz)):
            actual = read(name)
            if int(actual) != expected:
                raise RuntimeError(f'{name}: requested {expected}, got {actual}; stopping')
        read('rx_rf_bandwidth')
        read('tx_rf_bandwidth')
        write('tx_hardwaregain_chan0', a.tx_gain)
        read('tx_hardwaregain_chan0')

        log.info('Starting fresh RX -> TX blocks. Ctrl+C requests exit.')
        started = time.monotonic()
        reported = started
        blocks = 0
        peak = 0.0
        while time.monotonic() - started < a.seconds:
            stage = f'RX buffer read (block {blocks + 1})'
            if blocks == 0:
                log.info('[STEP] %s', stage)
            samples = np.asarray(sdr.rx())
            if samples.ndim != 1 or samples.size != a.samples:
                raise RuntimeError(f'Unexpected single-channel RX shape: {samples.shape}')
            peak = max(peak, float(np.abs(samples).max()))
            stage = f'TX buffer submission (block {blocks + 1})'
            if blocks == 0:
                log.info('[STEP] %s', stage)
            # Preserve received numbers, with no block normalization. RX/TX bit
            # alignment may differ: measure output level; do not assume unity RF gain.
            sdr.tx(samples)
            blocks += 1
            now = time.monotonic()
            if blocks == 1 or now - reported >= 2:
                log.info('Submitted blocks=%d; elapsed=%.2f s; RX peak magnitude=%.1f',
                         blocks, now - started, peak)
                reported = now
        log.info('Finished: %d blocks submitted in %.3f s; this does not verify RF continuity',
                 blocks, time.monotonic() - started)
    except KeyboardInterrupt:
        log.warning('Interrupted during: %s', stage)
        status = 130
    except Exception:
        log.exception('[FAILED STEP] %s', stage)
        log.error('Stopped normal processing. See the FIRST failed step and traceback above.')
        status = 1
    finally:
        if sdr is not None:
            # Cleanup errors must not replace the original failing-step information.
            for label, operation in (
                ('set TX0 maximum attenuation', lambda: setattr(sdr, 'tx_hardwaregain_chan0', -89.75)),
                ('destroy TX buffer', lambda: sdr.tx_destroy_buffer()),
                ('destroy RX buffer', lambda: sdr.rx_destroy_buffer()),
            ):
                try:
                    operation()
                    log.info('[CLEANUP OK] %s', label)
                except Exception as exc:
                    log.warning('[CLEANUP FAILED] %s: %s', label, exc)
            log.warning('RF mute is NOT guaranteed by cleanup; verify output on CMU200.')
        log.info('Log file: %s', a.log)
    return status


if __name__ == '__main__':
    sys.exit(main())
