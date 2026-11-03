#!/usr/bin/env python3
"""USB RX-to-TX block forwarding demo for Pluto-compatible AD9361 SDRs.

Run on the RK3588, with RF cabling/attenuation already checked.
This is a bounded, non-cyclic data-path demonstration, not a guaranteed
gap-free or deterministic-latency repeater. No hardware test has been made.
"""

import argparse
import math
import sys
import time


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri', default='usb:1.4.5', help='Use current iio_info -s result')
    parser.add_argument('--rx-hz', type=int, required=True, help='RX LO frequency, Hz')
    parser.add_argument('--tx-hz', type=int, required=True, help='TX LO frequency, Hz')
    parser.add_argument('--rate', type=int, default=2_500_000, help='RX/TX sample rate, samples/s')
    parser.add_argument('--bandwidth', type=int, default=1_500_000, help='RX/TX RF bandwidth, Hz')
    parser.add_argument('--samples', type=int, default=16384, help='Complex samples per block')
    parser.add_argument('--seconds', type=float, default=5.0, help='Approximate loop duration; calls can block')
    parser.add_argument('--rx-gain', type=float, default=10.0, help='Manual RX gain, dB')
    parser.add_argument('--tx-gain', type=float, default=-60.0,
                        help='TX attenuation setting in dB, -89.75 to 0; NOT dBm')
    parser.add_argument('--transmit', action='store_true',
                        help='Actually configure hardware and forward samples; otherwise only show plan')
    args = parser.parse_args()
    if min(args.rx_hz, args.tx_hz, args.rate, args.bandwidth, args.samples) <= 0:
        parser.error('Frequencies, sample rate, bandwidth and block size must be positive')
    if args.rx_hz == args.tx_hz:
        parser.error('This demonstration is for the requested different-frequency loopback')
    if args.bandwidth > args.rate:
        parser.error('For this demonstration, use RF bandwidth no greater than sample rate')
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 60:
        parser.error('Use a finite duration greater than 0 and no more than 60 seconds')
    if not math.isfinite(args.tx_gain) or not -89.75 <= args.tx_gain <= 0:
        parser.error('TX gain must be between -89.75 and 0 dB')
    if not math.isfinite(args.rx_gain):
        parser.error('RX gain must be finite; hardware will validate its frequency-dependent range')
    return args


def main():
    args = parse_args()
    print(f'URI: {args.uri}; logical RX 0 -> logical TX 0')
    print(f'RX LO: {args.rx_hz} Hz; TX LO: {args.tx_hz} Hz')
    print(f'Sample rate: {args.rate} S/s; RF bandwidth: {args.bandwidth} Hz')
    print(f'RX gain: {args.rx_gain} dB; TX setting: {args.tx_gain} dB (not dBm)')
    print(f'Block: {args.samples} samples, {1000 * args.samples / args.rate:.3f} ms of signal')
    print('Physical SMA-to-logical-channel mapping must be verified on this firmware.')
    if not args.transmit:
        print('PLAN ONLY: no device opened or modified. Add --transmit to execute.')
        return 0

    try:
        import adi
        import numpy as np
    except ImportError as exc:
        print(f'Missing dependency: {exc}. Requires compatible pyadi-iio, pylibiio and numpy.', file=sys.stderr)
        return 2

    sdr = None
    status = 0
    blocks = 0
    peak = 0.0
    try:
        sdr = adi.ad9361(uri=args.uri)
        sdr.tx_hardwaregain_chan0 = -89.75
        sdr.rx_enabled_channels = [0]
        sdr.tx_enabled_channels = [0]
        sdr.sample_rate = args.rate
        sdr.rx_rf_bandwidth = args.bandwidth
        sdr.tx_rf_bandwidth = args.bandwidth
        sdr.rx_lo = args.rx_hz
        sdr.tx_lo = args.tx_hz
        sdr.gain_control_mode_chan0 = 'manual'
        sdr.rx_hardwaregain_chan0 = args.rx_gain
        sdr.rx_buffer_size = args.samples
        sdr.tx_cyclic_buffer = False

        for label, actual, requested in (
            ('sample_rate', sdr.sample_rate, args.rate),
            ('rx_lo', sdr.rx_lo, args.rx_hz),
            ('tx_lo', sdr.tx_lo, args.tx_hz),
        ):
            print(f'Readback {label}: {actual}')
            if int(actual) != requested:
                raise RuntimeError(f'{label} readback differs from request; refusing sample transmission')

        sdr.tx_hardwaregain_chan0 = args.tx_gain
        print('Forwarding fresh RX blocks to TX. Ctrl+C requests exit.', flush=True)
        started = time.monotonic()
        while time.monotonic() - started < args.seconds:
            samples = np.asarray(sdr.rx())
            if samples.ndim != 1 or samples.size != args.samples:
                raise RuntimeError(f'Unexpected single-channel RX shape: {samples.shape}')
            # Preserve raw I/Q values: no per-block normalization or demodulation.
            # RX/TX bit alignment may differ; verify levels on the instrument.
            peak = max(peak, float(np.abs(samples).max()))
            sdr.tx(samples)
            blocks += 1
        elapsed = time.monotonic() - started
        print(f'{blocks} blocks submitted in {elapsed:.3f} s; RX peak magnitude: {peak:.1f}')
        print('Submission count does not prove uninterrupted RF output or absence of sample loss.')
    except KeyboardInterrupt:
        print('\nInterrupted.')
        status = 130
    except Exception as exc:
        print(f'Forwarding failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        status = 1
    finally:
        if sdr is not None:
            # Best effort: attenuation and buffer destruction do NOT guarantee RF mute.
            for label, operation in (
                ('set TX0 maximum attenuation', lambda: setattr(sdr, 'tx_hardwaregain_chan0', -89.75)),
                ('destroy TX buffer', sdr.tx_destroy_buffer),
                ('destroy RX buffer', sdr.rx_destroy_buffer),
            ):
                try:
                    operation()
                except Exception as exc:
                    print(f'Cleanup could not {label}: {exc}', file=sys.stderr)
            print('Cleanup attempted. Verify RF output on CMU200; hardware RF mute is not guaranteed.')
    return status


if __name__ == '__main__':
    sys.exit(main())
