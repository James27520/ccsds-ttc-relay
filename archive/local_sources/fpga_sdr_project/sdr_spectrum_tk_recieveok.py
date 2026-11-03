#!/usr/bin/env python3
"""RX-only spectrum drawn directly with Tk Canvas; no matplotlib GUI.
Run in RK3588 desktop: python3 ~/sdr_spectrum_tk.py
Dependencies: tkinter, numpy, compatible adi/iio. --demo needs no SDR.
Levels are digital FFT amplitude, not dBm/dBFS. No TX buffer is created.
"""
import os
# If a third-party library imports matplotlib, disable its interactive backend.
os.environ['MPLBACKEND'] = 'Agg'
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


def discover(iio):
    try:
        found = dict(iio.scan_contexts())
    except Exception:
        found = {}
    if not any(k.startswith('usb:') for k in found):
        p = subprocess.run(['iio_info', '-s'], capture_output=True, text=True,
                           errors='replace', timeout=15)
        for line in (p.stdout + p.stderr).splitlines():
            match = re.search(r'\[(usb:[^\]\s]+)\]', line)
            if match:
                found[match.group(1)] = line
    print('Found:', found, flush=True)
    devices = [k for k,v in found.items() if k.startswith('usb:') and
               any(s in str(v).lower() for s in ('pluto','ad936','ldsdr','fmcomms'))]
    if len(devices) != 1:
        raise RuntimeError('Need one USB SDR; use iio_info -s and --uri to select explicitly')
    return devices[0]


def fft_data(x, rate):
    x = np.asarray(x)
    if x.ndim != 1 or x.size < 8 or not np.isfinite(x).all():
        raise ValueError('Invalid RX array')
    win = np.hanning(x.size)
    amplitude = np.abs(np.fft.fftshift(np.fft.fft((x-x.mean())*win))) / win.sum()
    db = 20*np.log10(np.maximum(amplitude, 1e-12))
    hz = np.fft.fftshift(np.fft.fftfreq(x.size, 1/rate))
    mask = (np.abs(hz)>3*rate/x.size) & (np.abs(hz)<rate*.45)
    peak = np.flatnonzero(mask)[np.argmax(db[mask])]
    return hz, db, float(np.sqrt(np.mean(np.abs(x)**2))), int(peak)


def worker(a, frames, events, commands, stop):
    radio = None
    stage = 'initialize'
    try:
        lo, gain, rate = a.center_mhz*1e6, a.gain, 2500000
        if not a.demo:
            stage = 'import adi/iio'
            import adi
            import iio
            uri = discover(iio) if a.uri=='auto' else a.uri
            stage = 'connect '+uri
            events.put(stage)
            radio = adi.ad9361(uri=uri)
            radio._ctx.set_timeout(3000)
            for name, val in [('rx_enabled_channels',[a.channel]), ('sample_rate',rate),
                ('rx_rf_bandwidth',1500000), ('rx_lo',int(lo)),
                (f'gain_control_mode_chan{a.channel}','manual'),
                (f'rx_hardwaregain_chan{a.channel}',gain), ('rx_buffer_size',16384)]:
                stage = f'set {name}={val}'
                events.put(stage)
                setattr(radio,name,val)
            lo, rate = int(radio.rx_lo), int(radio.sample_rate)
            gain = float(getattr(radio,f'rx_hardwaregain_chan{a.channel}'))
        rng = np.random.default_rng()
        started, report = time.monotonic(), 0
        while not stop.is_set():
            try:
                new_lo,new_gain = commands.get_nowait()
            except queue.Empty:
                pass
            else:
                stage = 'apply frequency/gain'
                if radio is not None:
                    radio.rx_destroy_buffer()
                    radio.rx_lo=int(new_lo)
                    setattr(radio,f'rx_hardwaregain_chan{a.channel}',new_gain)
                    lo=int(radio.rx_lo)
                    gain=float(getattr(radio,f'rx_hardwaregain_chan{a.channel}'))
                else:
                    lo,gain=new_lo,new_gain
                events.put(f'Applied RX center {lo/1e6:.6f} MHz; gain {gain:g} dB')
            stage='read RX'
            if radio is None:
                x=rng.normal(size=16384)+1j*rng.normal(size=16384)
                if int((time.monotonic()-started)/5)%2==0:
                    x+=70*np.exp(2j*np.pi*(a.target_mhz*1e6-lo)*np.arange(16384)/rate)
                stop.wait(.02)
            else:
                x=np.asarray(radio.rx())
            now=time.monotonic()
            if now>=report:
                hz,db,rms,peak=fft_data(x,rate)
                packet=dict(hz=hz,db=db,rms=rms,peak=peak,iq=x.copy(),lo=lo,
                            gain=gain,rate=rate,time=now)
                try:
                    frames.put_nowait(packet)
                except queue.Full:
                    try:
                        frames.get_nowait()
                    except queue.Empty:
                        pass
                    frames.put_nowait(packet)
                report=now+.2
    except Exception as exc:
        traceback.print_exc()
        events.put(f'ERROR at {stage}: {exc}')
    finally:
        if radio is not None:
            try:
                radio.rx_destroy_buffer()
            except Exception as exc:
                events.put('RX cleanup failed: '+str(exc))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uri',default='auto')
    p.add_argument('--center-mhz',type=float,default=1000.)
    p.add_argument('--target-mhz',type=float,default=1000.1)
    p.add_argument('--gain',type=float,default=10.)
    p.add_argument('--channel',type=int,choices=[0,1],default=0)
    p.add_argument('--demo',action='store_true')
    a=p.parse_args()
    if not all(np.isfinite(v) for v in (a.center_mhz,a.target_mhz,a.gain)) or min(a.center_mhz,a.target_mhz)<=0:
        p.error('Invalid frequency/gain')
    import tkinter as tk
    from tkinter import ttk
    print('SDR_SPECTRUM_TK v1 | renderer: Tk Canvas | NO matplotlib GUI',flush=True)
    root=tk.Tk()
    root.title('SDR Spectrum - Pure Tk - RX ONLY')
    root.geometry('1100x720')
    frames,events,commands=queue.Queue(1),queue.Queue(),queue.Queue(1)
    stop=threading.Event()
    latest=[None]
    head=tk.StringVar(value='RX ONLY | Connecting...')
    status=tk.StringVar(value='No TX buffer submitted. Digital levels are NOT dBm/dBFS.')
    ttk.Label(root,textvariable=head,font=('TkDefaultFont',11)).pack(fill='x',padx=12,pady=10)
    canvas=tk.Canvas(root,bg='#101a2b',highlightthickness=0)
    canvas.pack(fill='both',expand=True,padx=12)
    controls=ttk.Frame(root,padding=12)
    controls.pack(fill='x')
    lo_var=tk.StringVar(value=str(a.center_mhz))
    gain_var=tk.StringVar(value=str(a.gain))
    for col,(label,var) in enumerate([('RX center MHz',lo_var),('RX gain dB',gain_var)]):
        ttk.Label(controls,text=label).grid(row=0,column=col*2,padx=5)
        ttk.Entry(controls,textvariable=var,width=13).grid(row=0,column=col*2+1,padx=5)
    ttk.Label(root,textvariable=status,wraplength=1000).pack(fill='x',padx=12,pady=6)
    ttk.Label(root,text='Dashed orange: expected tone. Red dot: strongest non-DC bin (may be noise). Close window to stop.').pack(pady=5)

    def apply():
        try:
            lo,gain=float(lo_var.get())*1e6,float(gain_var.get())
            if not np.isfinite(lo) or lo<=0 or not np.isfinite(gain):
                raise ValueError('Invalid value')
            if not thread.is_alive():
                raise ValueError('Receiver stopped; restart script')
            commands.put_nowait((lo,gain))
            status.set('Applying...')
        except (ValueError,queue.Full) as exc:
            status.set('Could not apply: '+str(exc))

    def save():
        d=latest[0]
        if d is None:
            return
        base=Path.cwd()/datetime.now().strftime('sdr_tk_%Y%m%d_%H%M%S_%f')
        try:
            np.savez(str(base)+'.npz',iq=d['iq'],sample_rate=d['rate'],rx_lo=d['lo'],gain=d['gain'])
            np.savetxt(str(base)+'.csv',np.column_stack(((d['lo']+d['hz'])/1e6,d['db'])),
                       delimiter=',',header='frequency_MHz,FFT_dB_re_1_count',comments='')
            status.set('Saved IQ and spectrum: '+str(base))
        except Exception as exc:
            status.set('Save failed: '+str(exc))
    ttk.Button(controls,text='Apply',command=apply).grid(row=0,column=4,padx=12)
    ttk.Button(controls,text='Save IQ + CSV',command=save).grid(row=0,column=5,padx=5)

    def draw(d):
        canvas.delete('all')
        w,h=max(canvas.winfo_width(),300),max(canvas.winfo_height(),200)
        left,right,top,bottom=70,w-25,25,h-55
        low,high=-110,80
        def sy(v):
            return bottom-(np.clip(v,low,high)-low)/(high-low)*(bottom-top)
        for value in range(-100,81,20):
            y=sy(value)
            canvas.create_line(left,y,right,y,fill='#2e3e53')
            canvas.create_text(left-10,y,text=str(value),anchor='e',fill='#b7c9df')
        canvas.create_text(left,10,text='FFT amplitude [dB re 1 count]',anchor='w',fill='#b7c9df')
        for frac in np.linspace(0,1,6):
            x=left+frac*(right-left)
            freq=(d['lo']+(frac-.5)*d['rate'])/1e6
            canvas.create_line(x,top,x,bottom,fill='#2e3e53')
            canvas.create_text(x,bottom+18,text=f'{freq:.3f}',fill='#b7c9df')
        canvas.create_text((left+right)/2,h-10,text='RF frequency [MHz]',fill='#b7c9df')
        # Max pool to pixel columns so a narrow spectral line stays visible.
        n=len(d['db'])
        stride=max(1,int(np.ceil(n/max(1,right-left))))
        starts=np.arange(0,n,stride)
        ys=np.maximum.reduceat(d['db'],starts)
        xs=left+starts/(n-1)*(right-left)
        points=np.column_stack((xs,sy(ys))).ravel().tolist()
        canvas.create_line(*points,fill='#42cbf5',width=1)
        frac=(a.target_mhz*1e6-d['lo'])/d['rate']+.5
        if 0<=frac<=1:
            x=left+frac*(right-left)
            canvas.create_line(x,top,x,bottom,fill='#ffb04b',dash=(5,5))
        i=d['peak']
        x=left+i/(n-1)*(right-left)
        y=sy(d['db'][i])
        canvas.create_oval(x-4,y-4,x+4,y+4,fill='#f57575',outline='')

    def poll():
        while not events.empty():
            try:
                event=events.get_nowait()
            except queue.Empty:
                break
            print(event,flush=True)
            status.set(event)
        try:
            latest[0]=frames.get_nowait()
        except queue.Empty:
            pass
        d=latest[0]
        if d is not None:
            age=time.monotonic()-d['time']
            prefix='STALE - ' if age>2 else ('DEMO - ' if a.demo else '')
            head.set(f'{prefix}RX {d["lo"]/1e6:.6f} MHz | RMS {d["rms"]:.2f} counts | '
                     f'Peak {(d["lo"]+d["hz"][d["peak"]])/1e6:.6f} MHz | gain {d["gain"]:g} dB')
            draw(d)
        root.after(200,poll)

    def close():
        stop.set()
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    thread=threading.Thread(target=worker,args=(a,frames,events,commands,stop),daemon=True)
    thread.start()
    root.after(200,poll)
    try:
        root.mainloop()
    finally:
        stop.set()
        thread.join(timeout=5)


if __name__=='__main__':
    main()
