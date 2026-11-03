#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone receive-only spectrum GUI for RK3588 + USB AD9361 SDR.

python3 sdr_live_spectrum.py
Requires numpy, matplotlib, compatible pyadi-iio and Python libiio bindings.
No TX buffer is created. This does not mute a previously configured transmitter.
Vertical units are window-corrected digital FFT amplitude, NOT dBm or dBFS.
--demo runs synthetic signal/noise without opening any SDR.
"""
import argparse
import queue
import re
import subprocess
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np


def spectrum(iq, rate, remove_dc=True):
    x = np.asarray(iq)
    if x.ndim != 1 or x.size < 8 or not np.isfinite(x).all():
        raise ValueError('Invalid single-channel I/Q array')
    rms = float(np.sqrt(np.mean(np.abs(x) ** 2)))
    centered = x - np.mean(x) if remove_dc else x
    window = np.hanning(x.size)
    amplitude = np.abs(np.fft.fftshift(np.fft.fft(centered * window))) / window.sum()
    db = 20 * np.log10(np.maximum(amplitude, 1e-12))
    hz = np.fft.fftshift(np.fft.fftfreq(x.size, 1 / rate))
    # Ignore three bins around DC when reporting the dominant peak, not when plotting.
    usable = (np.abs(hz) > 3 * rate / x.size) & (np.abs(hz) < 0.45 * rate)
    index = np.flatnonzero(usable)[np.argmax(db[usable])]
    return hz, db, rms, int(index)


def usb_uri(iio):
    try:
        found = dict(iio.scan_contexts())
    except Exception:
        found = {}
    if not any(u.startswith('usb:') for u in found):
        result = subprocess.run(['iio_info', '-s'], capture_output=True, text=True,
                                errors='replace', timeout=15, check=False)
        for line in (result.stdout + result.stderr).splitlines():
            match = re.search(r'\[(usb:[^\]\s]+)\]', line)
            if match:
                found[match.group(1)] = line
    print('Available contexts:', found, flush=True)
    matches = [u for u, description in found.items() if u.startswith('usb:') and
               any(s in str(description).lower() for s in ('pluto', 'ad936', 'ldsdr', 'fmcomms'))]
    if len(matches) != 1:
        raise RuntimeError('Expected one USB SDR. Run iio_info -s and specify --uri explicitly.')
    return matches[0]


def receive(args, frames, events, commands, stop):
    radio = None
    stage = 'load SDR libraries'
    try:
        center, gain = args.center_mhz * 1e6, args.gain
        rate = args.rate
        if not args.demo:
            import adi
            import iio
            stage = 'discover USB SDR'
            uri = usb_uri(iio) if args.uri == 'auto' else args.uri
            stage = 'connect ' + uri
            events.put(stage)
            radio = adi.ad9361(uri=uri)
            # All SDR access, including reconfiguration and cleanup, stays in this thread.
            radio._ctx.set_timeout(3000)
            for name, value in (
                ('rx_enabled_channels', [args.channel]), ('sample_rate', rate),
                ('rx_rf_bandwidth', args.bandwidth), ('rx_lo', int(center)),
                (f'gain_control_mode_chan{args.channel}', 'manual'),
                (f'rx_hardwaregain_chan{args.channel}', gain),
                ('rx_buffer_size', args.fft),
            ):
                stage = f'set {name}={value}'
                events.put(stage)
                setattr(radio, name, value)
            center = int(radio.rx_lo)
            rate = int(radio.sample_rate)
            gain = float(getattr(radio, f'rx_hardwaregain_chan{args.channel}'))
        rng = np.random.default_rng()
        sample_index = 0
        report_at = 0
        started = time.monotonic()
        generation = 0
        while not stop.is_set():
            try:
                new_center, new_gain = commands.get_nowait()
            except queue.Empty:
                pass
            else:
                stage = 'apply center frequency / RX gain'
                if radio is not None:
                    radio.rx_destroy_buffer()
                    radio.rx_lo = int(new_center)
                    setattr(radio, f'rx_hardwaregain_chan{args.channel}', new_gain)
                    center = int(radio.rx_lo)
                    gain = float(getattr(radio, f'rx_hardwaregain_chan{args.channel}'))
                else:
                    center, gain = new_center, new_gain
                generation += 1
                events.put(f'Applied center={center/1e6:.6f} MHz, RX gain={gain:g} dB')
            stage = 'read RX buffer'
            if radio is not None:
                iq = np.asarray(radio.rx())
            else:
                t = (np.arange(args.fft) + sample_index) / rate
                on = int((time.monotonic()-started) / 6) % 2 == 0
                iq = rng.normal(size=args.fft) + 1j*rng.normal(size=args.fft)
                if on:
                    iq += 70 * np.exp(2j*np.pi*(args.target_mhz*1e6-center)*t)
                sample_index += args.fft
                stop.wait(0.02)
            now = time.monotonic()
            if now >= report_at:
                stage = 'compute FFT'
                hz, db, rms, peak = spectrum(iq, rate, not args.keep_dc)
                packet = dict(iq=iq.copy(), hz=hz, db=db, rms=rms, peak=peak,
                              center=center, gain=gain, rate=rate, time=now,
                              generation=generation)
                try:
                    frames.put_nowait(packet)
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    frames.put_nowait(packet)
                report_at = now + 0.2
    except Exception as exc:
        traceback.print_exc()
        events.put(f'ERROR during {stage}: {exc}. Restart after correcting the connection/configuration.')
    finally:
        if radio is not None:
            try:
                radio.rx_destroy_buffer()
            except Exception as exc:
                events.put('RX cleanup error: ' + str(exc))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uri', default='auto')
    p.add_argument('--center-mhz', type=float, default=1000.0)
    p.add_argument('--target-mhz', type=float, default=1000.1)
    p.add_argument('--gain', type=float, default=10.0)
    p.add_argument('--channel', type=int, choices=[0, 1], default=0)
    p.add_argument('--rate', type=int, default=2500000)
    p.add_argument('--bandwidth', type=int, default=1500000)
    p.add_argument('--fft', type=int, default=16384)
    p.add_argument('--keep-dc', action='store_true')
    p.add_argument('--demo', action='store_true')
    p.add_argument('--demo-png', help='Save an offline synthetic spectrum PNG; no GUI/SDR')
    args = p.parse_args()
    if (not all(np.isfinite(v) for v in (args.center_mhz, args.target_mhz, args.gain))
            or min(args.center_mhz, args.target_mhz, args.rate, args.bandwidth) <= 0
            or args.bandwidth > args.rate or not 1024 <= args.fft <= 262144):
        p.error('Invalid frequency/rate/bandwidth/FFT settings')
    import matplotlib
    if args.demo_png:
        matplotlib.use('Agg')
    elif matplotlib.get_backend().lower() == 'agg':
        # Desktop Ubuntu often falls back to Agg if no GUI toolkit was installed.
        matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.widgets import Button, TextBox

    fig, (ax, water_ax) = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                                     gridspec_kw={'height_ratios': [3, 2]})
    fig.subplots_adjust(left=.09, right=.87, bottom=.22, top=.88, hspace=.24)
    try:
        fig.canvas.manager.set_window_title('LDsdr RX spectrum - RK3588')
    except AttributeError:
        pass
    ax.set_title('Waiting for receive data...')
    ax.set_ylabel('FFT amplitude [dB re 1 count]')
    ax.set_ylim(-100, 80)
    ax.grid(alpha=.25)
    hz = np.fft.fftshift(np.fft.fftfreq(args.fft, 1/args.rate))
    line, = ax.plot(hz/1000, np.full(args.fft, -120.), lw=.8, color='#137aaf')
    marker = ax.axvline((args.target_mhz-args.center_mhz)*1000, color='#e88322', ls='--',
                       alpha=.65, zorder=1, label='Expected tone')
    peak_point, = ax.plot([], [], 'o', color='#d13e35', markersize=5, zorder=4)
    ax.legend(loc='upper right')
    # 100 displayed rows, compressed to at most 2048 frequency columns.
    stride = max(1, args.fft // 2048)
    columns = len(hz[::stride])
    history = np.full((100, columns), -100.)
    water = water_ax.imshow(history, origin='lower', aspect='auto', cmap='magma',
                            extent=[hz[0]/1000, hz[-1]/1000, -100, 0], vmin=-80, vmax=50)
    water_ax.set_ylabel('Displayed frames\nolder below')
    water_ax.set_xlabel('Offset from RX center [kHz]')
    water_ax.set_xlim(-args.rate/2000, args.rate/2000)
    color_ax = fig.add_axes([.90, .25, .018, .24])
    fig.colorbar(water, cax=color_ax, label='dB re 1 count')
    info = fig.text(.09, .945, 'RX ONLY | digital levels, NOT dBm/dBFS', fontsize=10)
    status = fig.text(.09, .16, 'Connecting...', fontsize=9, wrap=True)
    center_box = TextBox(fig.add_axes([.17, .08, .16, .04]), 'Center MHz ', initial=str(args.center_mhz))
    gain_box = TextBox(fig.add_axes([.45, .08, .10, .04]), 'RX gain dB ', initial=str(args.gain))
    apply_button = Button(fig.add_axes([.59, .08, .10, .04]), 'Apply')
    save_button = Button(fig.add_axes([.73, .08, .14, .04]), 'Save PNG + IQ')
    fig.text(.09, .025, 'Close window to stop. Stop other SDR programs first. '
             'Mean/DC removed.' if not args.keep_dc else 'Close window to stop. DC retained.', fontsize=9)
    frames, events, commands = queue.Queue(maxsize=1), queue.Queue(), queue.Queue(maxsize=1)
    stop = threading.Event()
    latest = [None]
    displayed_generation = [None]

    def update(_):
        while not events.empty():
            try:
                text = events.get_nowait()
            except queue.Empty:
                break
            status.set_text(text)
            status.set_color('#b22' if 'ERROR' in text else '#333')
            print(text, flush=True)
        try:
            data = frames.get_nowait()
        except queue.Empty:
            if latest[0] is not None and time.monotonic()-latest[0]['time'] > 2:
                ax.set_title('STALE: no new samples for >2 seconds')
            return
        latest[0] = data
        if displayed_generation[0] != data['generation']:
            history[:] = -100
            displayed_generation[0] = data['generation']
        x, y = data['hz']/1000, data['db']
        line.set_data(x, y)
        marker_x = (args.target_mhz*1e6-data['center'])/1000
        marker.set_xdata([marker_x, marker_x])
        marker.set_visible(abs(marker_x) < data['rate']/2000)
        history[:-1] = history[1:].copy()
        # Max pooling preserves narrow peaks when compressing waterfall columns.
        history[-1] = np.maximum.reduceat(y, np.arange(0, len(y), stride))
        water.set_data(history)
        water.set_extent([x[0], x[-1], -100, 0])
        water_ax.set_xlim(x[0], x[-1])
        idx = data['peak']
        peak_point.set_data([x[idx]], [y[idx]])
        ax.set_title(f'RX center {data["center"]/1e6:.6f} MHz | gain {data["gain"]:g} dB | '
                     f'Fs {data["rate"]/1e6:g} MS/s | CH{args.channel}')
        info.set_text(f'{"DEMO | " if args.demo or args.demo_png else ""}'
                      f'RMS {data["rms"]:.2f} counts | strongest non-DC peak '
                      f'{(data["center"]+data["hz"][idx])/1e6:.6f} MHz '
                      f'({data["hz"][idx]/1000:+.3f} kHz) | FFT bin {data["rate"]/len(y):.1f} Hz')

    def apply(_):
        try:
            center, gain = float(center_box.text)*1e6, float(gain_box.text)
            if not np.isfinite(center) or center <= 0 or not np.isfinite(gain):
                raise ValueError('Enter finite frequency and gain')
            if not worker.is_alive():
                raise ValueError('Receiver stopped; restart the script')
            commands.put_nowait((center, gain))
            status.set_text('Applying settings...')
        except (ValueError, queue.Full) as exc:
            status.set_text('Settings not queued: ' + str(exc))

    def save(_):
        data = latest[0]
        if data is None:
            status.set_text('No samples to save yet')
            return
        base = Path.cwd() / datetime.now().strftime('sdr_rx_%Y%m%d_%H%M%S_%f')
        try:
            np.savez(str(base)+'.npz', iq=data['iq'], sample_rate=data['rate'],
                     rx_lo=data['center'], gain=data['gain'], channel=args.channel)
            fig.savefig(str(base)+'.png', dpi=140)
            status.set_text('Saved ' + str(base) + '.png / .npz')
        except Exception as exc:
            status.set_text('Save failed: ' + str(exc))

    apply_button.on_clicked(apply)
    save_button.on_clicked(save)
    fig.canvas.mpl_connect('close_event', lambda _: stop.set())
    if args.demo_png:
        rng = np.random.default_rng(2)
        t = np.arange(args.fft)/args.rate
        iq = 70*np.exp(2j*np.pi*100000*t) + rng.normal(size=args.fft)+1j*rng.normal(size=args.fft)
        f, db, rms, peak = spectrum(iq, args.rate)
        history[:] = -55 + rng.normal(size=history.shape)*3
        for i in range(100):
            frames.put(dict(iq=iq, hz=f, db=db, rms=rms, peak=peak, center=args.center_mhz*1e6,
                            rate=args.rate, gain=args.gain, generation=0, time=time.monotonic()))
            update(i)
        status.set_text('OFFLINE DEMO: synthetic 100 kHz tone; no SDR connected.')
        fig.savefig(args.demo_png, dpi=120)
        plt.close(fig)
        return
    worker = threading.Thread(target=receive, args=(args, frames, events, commands, stop), daemon=True)
    worker.start()
    animation = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
    try:
        plt.show()
    finally:
        stop.set()
        worker.join(timeout=5)
        if worker.is_alive():
            print('Receiver has not exited yet; an I/O call may still be blocked.', flush=True)


if __name__ == '__main__':
    main()
