"""SDR RX1 -> Python IQ block forwarding -> SDR TX1, with live RX/TX IQ spectra.

This is a narrowband, block-based bring-up test. TX spectrum represents the IQ
submitted to the DAC, not independently measured RF power. It cannot guarantee
gap-free forwarding or fixed delay, especially for a full 20 MHz LTE waveform.
"""
import argparse
import math
import os
import queue
import sys
import threading
import time


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scan', action='store_true', help='Discover devices without transmitting')
    p.add_argument('--uri', help='Exact URI from --scan, or auto for one connected USB Pluto-compatible SDR')
    p.add_argument('--dll-dir', help='Windows directory containing native libiio.dll and dependencies')
    p.add_argument('--rx-mhz', type=float, help='Receive LO in MHz; required for forwarding')
    p.add_argument('--tx-mhz', type=float, help='Transmit LO in MHz; required for forwarding')
    p.add_argument('--rate', type=int, default=30720000,
                   help='Complex samples per second (default: 30.72 MSPS, matching the IIO LTE20 view)')
    p.add_argument('--bandwidth', type=int, default=18000000,
                   help='RX/TX analog filter bandwidth in Hz (default: 18 MHz)')
    p.add_argument('--rx-gain-mode', choices=('slow_attack', 'fast_attack', 'manual'),
                   default='slow_attack', help='RX gain control (default: slow_attack, matching the IIO view)')
    p.add_argument('--rx-gain', type=float, default=20.0,
                   help='RX gain in dB only when --rx-gain-mode manual')
    p.add_argument('--tx-attenuation', type=float, default=0.0,
                   help='TX attenuation in dB (default: 0, maximum hardware output; 60 means weaker)')
    p.add_argument('--gain', type=float, default=1.0, help='Fixed IQ numerical multiplier, not RF gain in dB')
    p.add_argument('--buffer', type=int, default=16384)
    p.add_argument('--seconds', type=float, default=30.0, help='0 runs until Ctrl+C')
    p.add_argument('--plot', action='store_true', default=True,
                   help='Live RX IQ and TX input IQ spectra (the default); not measured TX RF')
    p.add_argument('--no-plot', action='store_false', dest='plot', help='Forward without a graph')
    p.add_argument('--refresh', type=float, default=0.1, help='Spectrum refresh interval in seconds')
    p.add_argument('--fft-size', type=int, default=4096)
    p.add_argument('--average', type=int, default=1, help='Display power EMA factor; 1=instantaneous, 8=smoother')
    a = p.parse_args()
    if not a.scan and not a.uri:
        p.error('Run --scan first, then supply --uri.')
    if not a.scan and (a.rx_mhz is None or a.tx_mhz is None):
        p.error('Specify both --rx-mhz and --tx-mhz for forwarding.')
    values = (a.rx_gain, a.tx_attenuation, a.gain, a.seconds, a.refresh)
    if not a.scan:
        values += (a.rx_mhz, a.tx_mhz)
    if not all(math.isfinite(v) for v in values):
        p.error('Parameters must be finite numbers.')
    if not 521000 <= a.rate <= 61440000 or not 0 < a.bandwidth <= a.rate:
        p.error('Require 521000 <= rate <= 61440000 and 0 < bandwidth <= rate.')
    if a.buffer < 1024 or a.buffer % 8:
        p.error('--buffer must be >=1024 and divisible by 8.')
    if a.seconds < 0 or not 0 < a.gain <= 16 or not 0 <= a.tx_attenuation <= 89:
        p.error('Require seconds >=0, 0 < gain <=16 and 0 <= tx-attenuation <=89.')
    if not 0.05 <= a.refresh <= 5 or not 256 <= a.fft_size <= a.buffer:
        p.error('Require 0.05 <= refresh <=5 and 256 <= fft-size <= buffer.')
    if not 1 <= a.average <= 100:
        p.error('Require 1 <= average <=100.')
    return a


def spectrum(iq, rate, fft_size):
    """Complex, two-sided FFT; magnitude is relative to one raw IQ count, not dBm."""
    import numpy as np
    window = np.hanning(fft_size)
    magnitude = np.abs(np.fft.fftshift(np.fft.fft(iq[:fft_size] * window))) / window.sum()
    db = 20 * np.log10(np.maximum(magnitude, 1e-10))
    hz = np.fft.fftshift(np.fft.fftfreq(fft_size, 1 / rate))
    return hz, db


def resolve_uri(iio, uri):
    if uri != 'auto':
        return uri
    candidates = [key for key, description in iio.scan_contexts().items()
                  if key.startswith('usb:') and 'pluto' in description.lower()]
    if len(candidates) != 1:
        raise RuntimeError(f'--uri auto requires exactly one USB Pluto-compatible SDR; '
                           f'found {len(candidates)}. Run --scan and specify --uri.')
    print(f'Auto-selected current USB URI: {candidates[0]}')
    return candidates[0]


def smooth_spectrum(previous_power, db, factor):
    """Average display power, never modify forwarded IQ or average directly in dB."""
    import numpy as np
    power = 10.0 ** (db / 10.0)
    if previous_power is not None:
        power = previous_power + (power - previous_power) / factor
    return power, 10 * np.log10(np.maximum(power, 1e-20))


def live_plot(plt, frames, stop, done, radio_info, a):
    """Only the main thread operates the GUI; no second SDR connection is opened."""
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout='constrained')
    fig.canvas.manager.set_window_title('SDR live RX / TX IQ spectra')
    fig.suptitle('Live IQ spectra | TX input IQ is NOT a measurement of transmitted RF')
    lines = []
    titles = ('RX1: live received IQ', 'TX1: IQ submitted to TX buffer')
    for ax, title in zip(axes, titles):
        line, = ax.plot([], [], linewidth=1)
        lines.append(line)
        ax.set_title(title)
        ax.set_xlabel('LO + baseband frequency (MHz)')
        ax.set_ylabel('dB re 1 raw IQ count\n(not dBm)')
        ax.set_ylim(-80, 95)
        ax.grid(True, alpha=0.3)
    for ax, lo in zip(axes, radio_info['los']):
        ax.set_xlim((lo - radio_info['rate'] / 2) / 1e6, (lo + radio_info['rate'] / 2) / 1e6)
        ax.axvline(lo / 1e6, color='gray', linestyle='--', linewidth=0.8)
        ax.ticklabel_format(axis='x', style='plain', useOffset=False)
    status = axes[1].text(0.01, 0.04, 'Waiting for IQ...', transform=axes[1].transAxes,
                          bbox={'facecolor': 'white', 'alpha': 0.85}, fontsize=9)
    can_blit = fig.canvas.supports_blit
    artists = [*lines, status]
    backgrounds = []
    if can_blit:
        for artist in artists:
            artist.set_animated(True)

        def cache_background(event):
            backgrounds[:] = [fig.canvas.copy_from_bbox(ax.bbox) for ax in axes]
            for artist in artists:
                artist.axes.draw_artist(artist)

        fig.canvas.mpl_connect('draw_event', cache_background)
    fig.canvas.mpl_connect('close_event', lambda event: stop.set())
    plt.show(block=False)
    fig.canvas.draw()
    last_frame = None
    powers = [None, None]
    try:
        while not stop.is_set() and not done.is_set() and plt.fignum_exists(fig.number):
            try:
                last_frame = frames.get_nowait()
                new_frame = True
            except queue.Empty:
                new_frame = False
            if last_frame is not None:
                x, y, meta = last_frame
                if new_frame:
                    for i, (iq, lo, line) in enumerate(zip((x, y), radio_info['los'], lines)):
                        hz, db = spectrum(iq, radio_info['rate'], a.fft_size)
                        powers[i], db = smooth_spectrum(powers[i], db, a.average)
                        line.set_data((lo + hz) / 1e6, db)
                age = time.monotonic() - meta['timestamp']
                status.set_text(f"blocks={meta['blocks']} | processed={meta['msps']:.3f} MSPS "
                                f"({100 * meta['msps'] * 1e6 / radio_info['rate']:.1f}% of configured rate) | "
                                f"TX clipped={meta['clipped']} | frame age={age:.2f}s | avg={a.average}")
                if can_blit and backgrounds:
                    for background in backgrounds:
                        fig.canvas.restore_region(background)
                    for artist in artists:
                        artist.axes.draw_artist(artist)
                    for ax in axes:
                        fig.canvas.blit(ax.bbox)
                else:
                    fig.canvas.draw_idle()
            plt.pause(a.refresh)
    finally:
        stop.set()
        plt.close(fig)


def forward(radio, a, frames, stop, done, result):
    """Forward every acquired block; only outdated display frames are discarded."""
    import numpy as np
    try:
        start = last_report = time.monotonic()
        last_frame = start - a.refresh
        total = blocks = clipped = 0
        while not stop.is_set() and (a.seconds == 0 or time.monotonic() - start < a.seconds):
            x = np.asarray(radio.rx())
            if stop.is_set():
                break
            if x.ndim != 1 or not np.iscomplexobj(x) or x.size != a.buffer:
                raise RuntimeError('Expected one complex RX1 array with --buffer samples.')
            if not np.all(np.isfinite(x)):
                raise RuntimeError('Non-finite RX data.')
            y = x * a.gain
            limit = 16383
            clipped += int(np.count_nonzero((abs(y.real) > limit) | (abs(y.imag) > limit)))
            y = np.clip(y.real, -limit, limit) + 1j * np.clip(y.imag, -limit, limit)
            radio.tx(y)
            total += x.size
            blocks += 1
            now = time.monotonic()
            msps = total / max(now - start, 1e-9) / 1e6
            if a.plot and now - last_frame >= a.refresh:
                frame = (x[:a.fft_size].copy(), y[:a.fft_size].copy(),
                         {'blocks': blocks, 'msps': msps, 'clipped': clipped, 'timestamp': now})
                try:
                    frames.get_nowait()
                except queue.Empty:
                    pass
                frames.put_nowait(frame)
                last_frame = now
            if now - last_report >= 1:
                rms = float(np.sqrt(np.mean(np.abs(x) ** 2)))
                print(f'{now-start:6.1f}s blocks={blocks} RX_RMS(raw)={rms:.1f} '
                      f'processed={msps:.3f} MSPS ({100 * msps * 1e6 / a.rate:.1f}% of rate) '
                      f'TX_clipped={clipped}', flush=True)
                last_report = now
    except Exception as exc:
        result['error'] = exc
    finally:
        done.set()


def cleanup(radio):
    for name in ('tx_destroy_buffer', 'rx_destroy_buffer'):
        try:
            getattr(radio, name)()
        except Exception as exc:
            print(f'Cleanup warning ({name}): {exc}', file=sys.stderr)
    try:
        radio.dds_enabled = [False] * len(radio.dds_enabled)
        radio.tx_hardwaregain_chan0 = -89.0
    except Exception as exc:
        print(f'TX shutdown warning: {exc}', file=sys.stderr)


def main():
    a = arguments()
    dll_handle = None
    if a.dll_dir:
        directory = os.path.abspath(a.dll_dir)
        if not os.path.isfile(os.path.join(directory, 'libiio.dll')):
            print('libiio.dll not found in --dll-dir.', file=sys.stderr)
            return 2
        os.environ['PATH'] = directory + os.pathsep + os.environ.get('PATH', '')
        if os.name == 'nt':
            dll_handle = os.add_dll_directory(directory)
    try:
        import iio
        import adi
        import numpy as np
    except (ImportError, OSError, TypeError, AttributeError) as exc:
        print(f'Cannot load Python packages/native libiio: {exc}', file=sys.stderr)
        print('Use Python 3.12, install numpy pyadi-iio pylibiio, and specify --dll-dir.', file=sys.stderr)
        return 2

    radio = None
    try:
        if a.scan:
            contexts = iio.scan_contexts()
            for uri, description in contexts.items():
                print(f'{uri}  {description}')
            if not contexts:
                print('No SDR found. Check USB data cable, power, startup and driver.')
            return 0

        plt = None
        if a.plot:
            import matplotlib.pyplot as plt
            if 'agg' == plt.get_backend().lower() or 'inline' in plt.get_backend().lower():
                raise RuntimeError('Use an interactive Matplotlib backend (TkAgg/QtAgg), not inline/Agg.')
        # Pluto exposes only voltage0/voltage1 (one I/Q pair) to the driver.
        # This also selects RX1/TX1 on compatible AD9361 boards without requesting voltage2.
        uri = resolve_uri(iio, a.uri)
        radio = adi.Pluto(uri=uri)
        radio._ctx.set_timeout(5000)
        radio.rx_enabled_channels = [0]
        radio.tx_enabled_channels = [0]
        radio.rx_output_type = 'raw'
        radio.tx_cyclic_buffer = False  # Each TX block comes from newly received IQ.
        radio.rx_buffer_size = a.buffer
        radio.loopback = 0  # Disable internal test loopback: use the physical RF ports.
        radio._ctrl.attrs['ensm_mode'].value = 'fdd'
        radio.sample_rate = a.rate
        radio.rx_rf_bandwidth = a.bandwidth
        radio.tx_rf_bandwidth = a.bandwidth
        radio.rx_lo = round(a.rx_mhz * 1e6)
        radio.tx_lo = round(a.tx_mhz * 1e6)
        radio.gain_control_mode_chan0 = a.rx_gain_mode
        if a.rx_gain_mode == 'manual':
            radio.rx_hardwaregain_chan0 = a.rx_gain
        radio.tx_hardwaregain_chan0 = -a.tx_attenuation
        actual = int(radio.sample_rate)
        if abs(actual - a.rate) > max(2, round(a.rate * 10e-6)):
            raise RuntimeError(f'Sample rate readback {actual} differs too much from {a.rate}.')
        if actual != a.rate:
            print(f'Sample rate rounded: requested {a.rate}, actual {actual} S/s; continuing.')
        print(f'RX1 {radio.rx_lo / 1e6:.6f} MHz -> TX1 {radio.tx_lo / 1e6:.6f} MHz')
        print(f'Rate {actual} S/s; buffer {a.buffer}; TX attenuation {a.tx_attenuation} dB; IQ multiplier {a.gain}')
        print(f'RX filter {a.bandwidth / 1e6:g} MHz; gain mode {a.rx_gain_mode}'
              + (f'; manual gain {a.rx_gain:g} dB' if a.rx_gain_mode == 'manual' else ''))
        if uri.startswith('usb:'):
            minimum_mb_s = actual * 8 / 1e6  # 16-bit I,Q in each of the RX and TX directions.
            print(f'Raw RX+TX IQ traffic is at least {minimum_mb_s:.1f} MB/s at this rate.')
            if minimum_mb_s > 60:
                print('WARNING: This exceeds the 60 MB/s theoretical USB 2.0 limit; '
                      'a continuous full-band relay is not possible through this host path.')
        print('Forwarding NEW IQ blocks. Ctrl+C stops. No gap-free or fixed-delay guarantee.')
        frames = queue.Queue(maxsize=1)
        stop, done = threading.Event(), threading.Event()
        result = {}
        info = {'rate': actual, 'los': (radio.rx_lo, radio.tx_lo)}
        worker = threading.Thread(target=forward, args=(radio, a, frames, stop, done, result),
                                  name='SDR IQ forwarding')
        worker.start()
        try:
            if a.plot:
                live_plot(plt, frames, stop, done, info, a)
            else:
                while not done.wait(0.1):
                    pass
        finally:
            stop.set()
            worker.join()  # Let bounded IIO calls finish before destroying buffers.
        if 'error' in result:
            raise result['error']
        print('Stopped or test duration reached; shutting down TX.')
        return 0
    except KeyboardInterrupt:
        print('\nStopped; shutting down TX.')
        return 0
    except Exception as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        print('Close IIO Oscilloscope/other SDR programs; check USB, URI and device settings.', file=sys.stderr)
        return 1
    finally:
        if radio is not None:
            cleanup(radio)
        if dll_handle is not None:
            dll_handle.close()


if __name__ == '__main__':
    sys.exit(main())
