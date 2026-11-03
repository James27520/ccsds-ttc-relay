#!/usr/bin/env python3
"""Mali OpenCL FFT verification and RX-only spectral rule monitor.
Requires numpy, pyopencl; live mode also needs existing adi/iio packages.
GPU required: never silently falls back to CPU. No TX operations.
"""
import argparse
import json
import time
from pathlib import Path
import numpy as np

SOURCE = r'''
__kernel void prepare(__global const float2 *x, __global const float *w,
                      __global float2 *y, int n, int bits) {
    int g=get_global_id(0), i=g%n, b=g/n;
    uint r=0, v=i;
    for(int k=0;k<bits;k++){r=(r<<1)|(v&1);v>>=1;}
    y[b*n+r]=x[g]*w[i];
}
__kernel void stage_fft(__global const float2 *a,__global float2 *b,int n,int m) {
    int g=get_global_id(0), batch=g/(n/2), t=g%(n/2), h=m/2;
    int j=t%h, base=batch*n+(t/h)*m+j;
    float theta=-6.283185307179586f*(float)j/(float)m;
    float c=cos(theta),s=sin(theta);
    float2 v=a[base+h], u=a[base];
    float2 z=(float2)(v.x*c-v.y*s,v.x*s+v.y*c);
    b[base]=u+z; b[base+h]=u-z;
}
__kernel void power_psd(__global const float2 *x,__global float *p,int n,float denom) {
    int g=get_global_id(0),i=g%n,b=g/n;
    float2 v=x[b*n+(i+n/2)%n];
    p[g]=dot(v,v)/denom;
}
'''


class GPUFFT:
    def __init__(self,n,batch,rate,index=0):
        import pyopencl as cl
        self.cl=cl
        devices=[]
        for platform in cl.get_platforms():
            for device in platform.get_devices(device_type=cl.device_type.GPU):
                devices.append(device)
        for i,d in enumerate(devices):
            print(f'GPU[{i}] {d.platform.name} / {d.name} / driver {d.driver_version}',flush=True)
        if not 0<=index<len(devices):
            raise RuntimeError('Requested OpenCL GPU not found; no CPU fallback')
        self.device=devices[index]
        self.ctx=cl.Context([self.device])
        self.q=cl.CommandQueue(self.ctx,properties=cl.command_queue_properties.PROFILING_ENABLE)
        program=cl.Program(self.ctx,SOURCE).build()
        self.prepare=cl.Kernel(program,'prepare')
        self.stage=cl.Kernel(program,'stage_fft')
        self.power=cl.Kernel(program,'power_psd')
        self.n,self.batch,self.rate=n,batch,rate
        self.window=np.hanning(n).astype(np.float32)
        mf=cl.mem_flags
        self.w=cl.Buffer(self.ctx,mf.READ_ONLY|mf.COPY_HOST_PTR,hostbuf=self.window)
        self.input=cl.Buffer(self.ctx,mf.READ_ONLY,n*batch*8)
        self.a=cl.Buffer(self.ctx,mf.READ_WRITE,n*batch*8)
        self.b=cl.Buffer(self.ctx,mf.READ_WRITE,n*batch*8)
        self.p=cl.Buffer(self.ctx,mf.WRITE_ONLY,n*batch*4)
        self.denom=np.float32(rate*np.sum(self.window.astype(np.float64)**2))

    def compute(self,frames,return_fft=False):
        cl=self.cl
        x=np.ascontiguousarray(frames,dtype=np.complex64)
        if x.shape!=(self.batch,self.n):
            raise ValueError(f'Expected {(self.batch,self.n)}, got {x.shape}')
        started=time.perf_counter()
        upload=cl.enqueue_copy(self.q,self.input,x,is_blocking=False)
        events=[self.prepare(self.q,(x.size,),None,self.input,self.w,self.a,
                             np.int32(self.n),np.int32(self.n.bit_length()-1))]
        src,dst=self.a,self.b
        for exponent in range(1,self.n.bit_length()):
            events.append(self.stage(self.q,(x.size//2,),None,src,dst,
                                     np.int32(self.n),np.int32(1<<exponent)))
            src,dst=dst,src
        events.append(self.power(self.q,(x.size,),None,src,self.p,np.int32(self.n),self.denom))
        p=np.empty(x.shape,np.float32)
        download=cl.enqueue_copy(self.q,p,self.p,is_blocking=False)
        download.wait()
        timing={'wall_ms':1000*(time.perf_counter()-started),
                'kernels_ms':sum(e.profile.end-e.profile.start for e in events)/1e6,
                'copy_ms':((upload.profile.end-upload.profile.start)+
                           (download.profile.end-download.profile.start))/1e6}
        transformed=None
        if return_fft:
            transformed=np.empty(x.shape,np.complex64)
            cl.enqueue_copy(self.q,transformed,src).wait()
        return p,timing,transformed


def cpu_psd(x,window,rate):
    z=np.fft.fft(x*window,axis=1)
    return np.fft.fftshift(abs(z)**2,axes=1)/(rate*np.sum(window.astype(np.float64)**2))


class Frames:
    def __init__(self,n,batch):
        self.n,self.batch,self.hop=n,batch,n//2
        self.pending=np.empty(0,np.complex64)
        self.start=0
    def feed(self,x):
        self.pending=np.concatenate((self.pending,np.asarray(x,dtype=np.complex64)))
        need=self.n+(self.batch-1)*self.hop
        while len(self.pending)>=need:
            block=np.stack([self.pending[i*self.hop:i*self.hop+self.n] for i in range(self.batch)])
            sample_start=self.start
            self.pending=self.pending[self.batch*self.hop:]
            self.start+=self.batch*self.hop
            yield sample_start,block


class Detector:
    def __init__(self,freq,center,allow_low,allow_high,channel_width,threshold):
        self.freq=freq
        self.valid=(abs(freq-center)<600000)&(abs(freq-center)>3000)
        self.allowed=(freq>=allow_low)&(freq<=allow_high)
        self.width=channel_width
        self.threshold=threshold
        self.baseline=None
        self.history=[]
        self.active=False
        self.on=self.off=0
        labels=np.floor((self.freq-self.freq[0])/self.width).astype(int)
        self.regions=[]
        for label in np.unique(labels[self.valid]):
            for allowed in (True,False):
                mask=self.valid&(labels==label)&(self.allowed==allowed)
                if mask.any():
                    self.regions.append((mask,allowed))
    def calibrate(self,psd):
        self.history.append(np.mean(psd,axis=0))
    def finish(self):
        if not self.history:
            raise RuntimeError('No baseline samples')
        self.baseline=np.maximum(np.mean(self.history,axis=0),1e-25)
        self.history=[]
    def inspect(self,psd):
        # Decisions advance for EACH FFT frame, not just the display average.
        abnormal=False
        max_rise=-999.
        occupied=[]
        for row in psd:
            hits=[]
            for mask,allowed in self.regions:
                rise=float(10*np.log10(max(float(row[mask].sum()),1e-25)/self.baseline[mask].sum()))
                if rise>self.threshold:
                    hits.append(dict(low_hz=float(self.freq[mask].min()),
                                     high_hz=float(self.freq[mask].max()),rise_db=rise,allowed=allowed))
            abnormal=any(not h['allowed'] for h in hits)
            self.on=self.on+1 if abnormal else 0
            self.off=self.off+1 if not abnormal else 0
            if self.on>=3: self.active=True
            if self.off>=10: self.active=False
            occupied=hits
            max_rise=max((h['rise_db'] for h in hits),default=0.)
        return {'out_of_band_alarm':self.active,'occupied_regions':occupied,'max_rise_db':max_rise}


def verify(engine,loops):
    n,b,fs=engine.n,engine.batch,engine.rate
    rng=np.random.default_rng(42)
    x=(rng.normal(size=(b,n))+1j*rng.normal(size=(b,n))).astype(np.complex64)
    x+=np.complex64(30)*np.exp(2j*np.pi*100000*np.arange(n)/fs).astype(np.complex64)
    _,_,z=engine.compute(x,True)
    expected=np.fft.fft(x*engine.window,axis=1)
    error=float(np.linalg.norm(z-expected)/np.linalg.norm(expected))
    if not np.isfinite(error) or error>2e-4:
        raise RuntimeError(f'GPU FFT accuracy FAILED, relative L2 error={error}')
    rows=[]
    for _ in range(3): engine.compute(x)
    for _ in range(loops):
        _,timing,_=engine.compute(x)
        rows.append(timing)
    cpu=[]
    for _ in range(loops):
        started=time.perf_counter(); cpu_psd(x,engine.window,fs)
        cpu.append(1000*(time.perf_counter()-started))
    interval=1000*b*(n//2)/fs
    report=dict(gpu=engine.device.name,relative_fft_error=error,batch_interval_ms=interval,
                gpu_total_median_ms=float(np.median([r['wall_ms'] for r in rows])),
                gpu_total_p95_ms=float(np.percentile([r['wall_ms'] for r in rows],95)),
                gpu_kernels_median_ms=float(np.median([r['kernels_ms'] for r in rows])),
                numpy_reference_median_ms=float(np.median(cpu)))
    print(json.dumps(report,indent=2),flush=True)
    print('NumPy is a reference, not a fully optimized CPU baseline. Live detection/IIO add extra cost.')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['check','live'])
    p.add_argument('--gpu',type=int,default=0)
    p.add_argument('--fft',type=int,default=4096)
    p.add_argument('--batch',type=int,default=8)
    p.add_argument('--rate',type=int,default=2500000)
    p.add_argument('--center-mhz',type=float,default=900.)
    p.add_argument('--gain',type=float,default=20.)
    p.add_argument('--channel',type=int,choices=[0,1],default=0)
    p.add_argument('--uri',default='auto')
    p.add_argument('--seconds',type=float,default=120)
    p.add_argument('--allow-low-mhz',type=float,default=900.075)
    p.add_argument('--allow-high-mhz',type=float,default=900.125)
    p.add_argument('--threshold-db',type=float,default=10.)
    p.add_argument('--output',default='gpu_monitor_output')
    a=p.parse_args()
    if a.fft<256 or a.fft>16384 or a.fft&(a.fft-1) or not 1<=a.batch<=32:
        p.error('FFT must be power of two in 256..16384; batch 1..32')
    if a.rate!=2500000:
        p.error('First hardware prototype fixes 2.5 MS/s and 1.5 MHz RF bandwidth')
    if a.seconds<=0 or a.allow_low_mhz>=a.allow_high_mhz:
        p.error('Invalid duration or allowed band')
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    engine=GPUFFT(a.fft,a.batch,a.rate,a.gpu)
    report=verify(engine,20)
    (out/'benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if a.mode=='check': return
    # Reuse the existing standalone Tk script ONLY for device discovery, no GUI starts.
    import adi
    import iio
    from sdr_spectrum_tk import discover
    input('Close other SDR apps. Turn CMU RF OUTPUT OFF for noise baseline, then press Enter: ')
    radio=None
    try:
        uri=discover(iio) if a.uri=='auto' else a.uri
        radio=adi.ad9361(uri=uri)
        radio._ctx.set_timeout(3000)
        for name,value in [('rx_enabled_channels',[a.channel]),('sample_rate',a.rate),
            ('rx_rf_bandwidth',1500000),('rx_lo',int(a.center_mhz*1e6)),
            (f'gain_control_mode_chan{a.channel}','manual'),
            (f'rx_hardwaregain_chan{a.channel}',a.gain),('rx_buffer_size',a.batch*a.fft//2)]:
            print('SET',name,value,flush=True);setattr(radio,name,value)
        if int(radio.rx_lo)!=int(a.center_mhz*1e6) or int(radio.sample_rate)!=a.rate:
            raise RuntimeError('Frequency/sample rate readback mismatch')
        freq=a.center_mhz*1e6+np.fft.fftshift(np.fft.fftfreq(a.fft,1/a.rate))
        detector=Detector(freq,a.center_mhz*1e6,a.allow_low_mhz*1e6,a.allow_high_mhz*1e6,25000,a.threshold_db)
        frames=Frames(a.fft,a.batch)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            for _,x in frames.feed(radio.rx()):
                power,_,_=engine.compute(x);detector.calibrate(power)
        detector.finish()
        np.savez(out/'baseline.npz',frequency_hz=freq,psd=detector.baseline,rx_gain=a.gain)
        radio.rx_destroy_buffer()
        input('Baseline saved. Turn CMU ON at 900.100 MHz, then press Enter: ')
        frames=Frames(a.fft,a.batch)
        start=last=time.monotonic(); batches=0;total_samples=0
        with (out/'detections.jsonl').open('w',encoding='utf-8') as log:
            while time.monotonic()-start<a.seconds:
                raw=np.asarray(radio.rx());total_samples+=raw.size
                for sample_start,x in frames.feed(raw):
                    begin=time.perf_counter()
                    power,timing,_=engine.compute(x)
                    detection=detector.inspect(power);batches+=1
                    elapsed_ms=1000*(time.perf_counter()-begin)
                    record=dict(sample_start=sample_start,elapsed_s=time.monotonic()-start,
                                gpu_ms=timing['wall_ms'],processing_ms=elapsed_ms,**detection)
                    log.write(json.dumps(record)+'\n')
                    if time.monotonic()-last>=1:
                        average=power.mean(axis=0)
                        peak=np.argmax(np.where(detector.valid,average,-1))
                        print(f'peak={freq[peak]/1e6:.6f} MHz | alarm={detection["out_of_band_alarm"]} '
                              f'occupied={len(detection["occupied_regions"])} | GPU={timing["wall_ms"]:.2f} ms '
                              f'processing={elapsed_ms:.2f} ms | delivered={total_samples/(time.monotonic()-start)/1e6:.3f} MS/s',flush=True)
                        np.savetxt(out/'spectrum_latest.csv',np.column_stack((freq,10*np.log10(np.maximum(average,1e-25)))),
                                   delimiter=',',header='frequency_Hz,PSD_dB_counts_squared_per_Hz',comments='')
                        log.flush();last=time.monotonic()
        print('Finished. Counters do not prove no hardware sample loss; this version does not control TX.')
    finally:
        if radio is not None:
            radio.rx_destroy_buffer()


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped')
