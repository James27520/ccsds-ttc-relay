#!/usr/bin/env python3
"""RK3588 + AD9361: known-tone TX test, then fresh-I/Q relay.

tone: TX LO 1000 MHz + 100 kHz generated tone => CMU RF1 at 1000.1 MHz.
relay: CMU RF2 900.1 MHz => RX LO 900 MHz => TX LO 1000 MHz => 1000.1 MHz.
Stop other SDR programs. Default TX setting -60 dB is attenuation, NOT dBm.
No automatic power ramp. Buffer cleanup does not guarantee RF hardware mute.
Separate IIO contexts are used for concurrent RX/TX; firmware must support it.
Queue statistics are NOT hardware overflow/underflow or sample-loss counters.
"""
import argparse
import logging
import math
import queue
import re
import subprocess
import threading
import time
import traceback
import numpy as np


def discover(iio):
    try:
        found = dict(iio.scan_contexts())
    except Exception:
        found = {}
    if not any(u.startswith('usb:') for u in found):
        result = subprocess.run(['iio_info', '-s'], capture_output=True, text=True,
                                errors='replace', timeout=15)
        for line in (result.stdout+result.stderr).splitlines():
            match = re.search(r'\[(usb:[^\]\s]+)\]', line)
            if match:
                found[match.group(1)] = line
    matches = [u for u,d in found.items() if u.startswith('usb:') and
               any(s in str(d).lower() for s in ('pluto','ad936','ldsdr','fmcomms'))]
    if len(matches) != 1:
        raise RuntimeError(f'Need one USB SDR; found {found}. Use --uri to select.')
    return matches[0]


def prepare_tx(x, scale):
    """Fixed numerical gain and component clipping, no per-block normalization."""
    x = np.asarray(x)
    if x.ndim != 1 or not np.isfinite(x).all():
        raise ValueError('Invalid single-channel IQ')
    y = x * scale
    limit = 16383.0
    clipped = np.count_nonzero((np.abs(y.real)>limit) | (np.abs(y.imag)>limit))
    y = np.clip(y.real,-limit,limit) + 1j*np.clip(y.imag,-limit,limit)
    return y, int(clipped)


def run_relay(rx, tx, a, stop):
    buffers, errors = queue.Queue(8), queue.Queue()
    lock = threading.Lock()
    counts = dict(rx=0, tx=0, dropped=0, waits=0, clipped=0, rx_rms=0., tx_peak=0.)

    def producer():
        try:
            while not stop.is_set():
                x = np.asarray(rx.rx()).copy()
                if x.ndim != 1 or len(x) != a.samples:
                    raise ValueError(f'Unexpected RX shape {x.shape}')
                with lock:
                    counts['rx'] += 1
                    counts['rx_rms'] = float(np.sqrt(np.mean(np.abs(x)**2)))
                try:
                    buffers.put_nowait(x)
                except queue.Full:
                    try:
                        buffers.get_nowait()  # discard oldest, report explicitly
                    except queue.Empty:
                        pass
                    else:
                        with lock:
                            counts['dropped'] += 1
                    buffers.put_nowait(x)
        except Exception:
            errors.put('RX failed:\n'+traceback.format_exc())
            stop.set()
        finally:
            try:
                rx.rx_destroy_buffer()
            except Exception:
                logging.exception('RX cleanup failed')

    def consumer():
        try:
            while not stop.is_set():
                try:
                    x = buffers.get(timeout=.1)
                except queue.Empty:
                    with lock:
                        counts['waits'] += 1
                    continue
                if stop.is_set():
                    break
                y, clipped = prepare_tx(x,a.scale)
                tx.tx(y)
                with lock:
                    counts['tx'] += 1
                    counts['clipped'] += clipped
                    counts['tx_peak'] = float(np.abs(y).max())
        except Exception:
            errors.put('TX failed:\n'+traceback.format_exc())
            stop.set()
        finally:
            cleanup_tx(tx,a.tx_channel)

    threads = [threading.Thread(target=producer,daemon=True),threading.Thread(target=consumer,daemon=True)]
    started = time.monotonic()
    try:
        for thread in threads:
            thread.start()
        while not stop.wait(1):
            elapsed = time.monotonic()-started
            with lock:
                c = counts.copy()
            logging.info('RX=%d TX=%d queue=%d dropped=%d waits=%d clip_samples=%d '
                         'RX_RMS=%.1f TX_peak=%.1f TX_submit_rate=%.3f MS/s',
                         c['rx'],c['tx'],buffers.qsize(),c['dropped'],c['waits'],c['clipped'],
                         c['rx_rms'],c['tx_peak'],c['tx']*a.samples/elapsed/1e6)
            if elapsed>=a.seconds:
                break
    finally:
        stop.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=6)
        if any(thread.is_alive() for thread in threads):
            raise RuntimeError('I/O worker still blocked; RF output state is unconfirmed')
    if not errors.empty():
        raise RuntimeError(errors.get())
    logging.info('Relay ended. Software counters do not prove gap-free RF output.')


def cleanup_tx(radio, channel):
    for name, fn in (
        ('maximum TX attenuation',lambda:setattr(radio,f'tx_hardwaregain_chan{channel}',-89.75)),
        ('destroy TX buffer',radio.tx_destroy_buffer)):
        try:
            fn()
            logging.info('Cleanup: %s',name)
        except Exception:
            logging.exception('Cleanup failed: %s',name)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['tone','relay'])
    p.add_argument('--uri',default='auto')
    p.add_argument('--seconds',type=float,default=60)
    p.add_argument('--tx-gain',type=float,default=-60)
    p.add_argument('--rx-gain',type=float,default=20)
    p.add_argument('--rx-channel',type=int,choices=[0,1],default=0)
    p.add_argument('--tx-channel',type=int,choices=[0,1],default=0)
    p.add_argument('--scale',type=float,default=16,
                   help='Fixed relay numerical multiplier, NOT calibrated RF gain')
    p.add_argument('--samples',type=int,default=20000)
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    if (not all(math.isfinite(v) for v in (a.seconds,a.tx_gain,a.rx_gain,a.scale))
            or not 0<a.seconds<=3600 or not -89.75<=a.tx_gain<=0
            or not 0<a.scale<=256 or a.samples<1024 or a.samples%25):
        p.error('Invalid settings; samples must be >=1024 and a multiple of 25')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(),logging.FileHandler('sdr_tx_relay.log',encoding='utf-8')])
    logging.info('MODE=%s RX center=900 MHz TX center=1000 MHz Fs=2.5 MS/s; TX setting=%g dB (NOT dBm)',a.mode,a.tx_gain)
    logging.info('Expected CMU RF1 signal: 1000.100 MHz; logical RX%d/TX%d; scale=%g',a.rx_channel,a.tx_channel,a.scale)
    if a.dry_run:
        logging.info('DRY RUN: no SDR opened')
        return 0
    import adi
    import iio
    tx=rx=None
    delegated=False
    stop=threading.Event()
    try:
        uri=discover(iio) if a.uri=='auto' else a.uri
        logging.info('Connecting %s',uri)
        tx=adi.ad9361(uri=uri)
        tx._ctx.set_timeout(3000)
        def setting(obj,name,value):
            logging.info('SET %s=%s',name,value)
            setattr(obj,name,value)
        setting(tx,f'tx_hardwaregain_chan{a.tx_channel}',-89.75)
        setting(tx,'sample_rate',2500000)
        setting(tx,'tx_rf_bandwidth',1500000)
        setting(tx,'tx_lo',1000000000)
        setting(tx,'tx_enabled_channels',[a.tx_channel])
        setting(tx,'tx_cyclic_buffer',a.mode=='tone')
        if int(tx.sample_rate)!=2500000 or int(tx.tx_lo)!=1000000000:
            raise RuntimeError('TX configuration readback mismatch')
        if a.mode=='relay':
            # Independent contexts keep concurrent buffer operations separate.
            rx=adi.ad9361(uri=uri)
            rx._ctx.set_timeout(3000)
            for name,val in [('rx_lo',900000000),('rx_rf_bandwidth',1500000),
                ('rx_enabled_channels',[a.rx_channel]),
                (f'gain_control_mode_chan{a.rx_channel}','manual'),
                (f'rx_hardwaregain_chan{a.rx_channel}',a.rx_gain),('rx_buffer_size',a.samples)]:
                setting(rx,name,val)
            if int(rx.sample_rate)!=2500000 or int(rx.rx_lo)!=900000000:
                raise RuntimeError('RX configuration readback mismatch')
        setting(tx,f'tx_hardwaregain_chan{a.tx_channel}',a.tx_gain)
        if a.mode=='tone':
            # Integer number of periods avoids a discontinuity in cyclic playback.
            tone=8192*np.exp(2j*np.pi*100000*np.arange(a.samples)/2500000)
            logging.info('Submitting cyclic 100 kHz tone, amplitude 8192 digital counts')
            tx.tx(tone)
            logging.info('Tone active for %.1f seconds. CMU RF1 center=1000.100 MHz.',a.seconds)
            stop.wait(a.seconds)
        else:
            delegated=True
            run_relay(rx,tx,a,stop)
        return 0
    except KeyboardInterrupt:
        logging.info('Stopped by user')
        return 130
    except Exception:
        logging.exception('FAILED')
        return 1
    finally:
        stop.set()
        if not delegated:
            if tx is not None:
                cleanup_tx(tx,a.tx_channel)
            if rx is not None:
                try:
                    rx.rx_destroy_buffer()
                except Exception:
                    logging.exception('RX cleanup failed')
        logging.warning('Cleanup is not guaranteed RF mute. Check CMU output measurement.')


if __name__=='__main__':
    raise SystemExit(main())
