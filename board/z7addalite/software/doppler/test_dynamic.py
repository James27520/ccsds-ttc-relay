"""Independent injected waveforms -> real C estimator/decoder -> tracker.

The truth frequency is used ONLY by the waveform source and scoring. The C
tracker receives estimates extracted from noisy ADC samples, never the truth.
All results are host simulation, not RF or flight measurements.
"""
import argparse
import csv
import ctypes as ct
import importlib.util
import json
from pathlib import Path
import time
import numpy as np

HERE = Path(__file__).resolve().parent
FS = 31.25e6
IF = 6.75e6
N = 131072


class Config(ct.Structure):
    _fields_ = [('link', ct.c_uint32), ('channel', ct.c_uint32)] + [
        (n, ct.c_double) for n in ('alpha', 'beta', 'max_shift_hz', 'max_rate_hz_s',
                                   'max_residual_hz', 'max_residual_rate_hz_s',
                                   'innovation_hz', 'min_quality')] + [
        (n, ct.c_uint32) for n in ('fresh_ms', 'hold_ms', 'observation_max_age_ms')]


class Prediction(ct.Structure):
    _fields_ = [('start_ms', ct.c_uint32), ('duration_ms', ct.c_uint32),
               ('rf_hz', ct.c_double), ('cfo_hz', ct.c_double), ('rate_hz_s', ct.c_double)]


class Tracker(ct.Structure):
    _fields_ = [('config', Config), ('prediction', Prediction), ('mode', ct.c_int),
               ('model_valid', ct.c_uint), ('measured', ct.c_uint)] + [
        (n, ct.c_uint32) for n in ('measurement_ms', 'sequence', 'accepted', 'rejected')] + [
        ('residual_hz', ct.c_double), ('residual_rate_hz_s', ct.c_double)]


class Output(ct.Structure):
    _fields_ = [('state', ct.c_int)] + [(n, ct.c_double) for n in
        ('prediction_hz', 'residual_hz', 'total_hz', 'correction_hz', 'rate_hz_s')] + [
        ('measurement_age_ms', ct.c_uint32), ('valid', ct.c_uint)]


class Trace(ct.Structure):
    _fields_ = [('plan', Output)] + [(n, ct.c_double) for n in
        ('measured_cfo_hz', 'applied_correction_hz', 'applied_rate_hz_s')] + [
        (n, ct.c_uint32) for n in ('capture_ms', 'sequence', 'clipped_samples')] + [
        ('planned', ct.c_uint), ('crc_ok', ct.c_uint), ('plan_result', ct.c_int),
        ('observation_result', ct.c_int)]


class Command(ct.Structure):
    _fields_ = [('version', ct.c_uint8), ('rx_mhz', ct.c_uint16),
               ('tx_mhz', ct.c_uint16), ('seq', ct.c_uint8)]


class Frame(ct.Structure):
    _fields_ = [('command', Command), ('body', ct.c_uint8 * 8), ('bit_offset', ct.c_size_t)] + [
        (n, ct.c_uint) for n in ('asm_errors', 'inverted', 'path_metric', 'end_state')]


class Stats(ct.Structure):
    _fields_ = [('carrier_hz', ct.c_double), ('carrier_phase', ct.c_double),
               ('input_rms', ct.c_double), ('symbol_candidates', ct.c_size_t), ('timing_trials', ct.c_uint)]


class Plan(ct.Structure):
    _fields_ = [('center_hz', ct.c_double), ('rate_hz_s', ct.c_double), ('search_hz', ct.c_double)]


def make_source():
    path = HERE.parents[3] / 'sw/ccsds/ccsds_tm_tx.py'
    spec = importlib.util.spec_from_file_location('reference_tx', path)
    tx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tx)
    bits = np.unpackbits(np.frombuffer(bytes.fromhex('1acffc1dbcd9014c82bf4b2c0b3894c10ddfdc50'), dtype=np.uint8))
    up = np.zeros(len(bits)*25*9)
    up[::25] = np.tile(1.-2.*bits.astype(float), 9)
    shaped = np.convolve(up, tx.srrc(.35, 25, 8), 'same')
    return shaped * (3000 / max(abs(shaped)))


def waveform(envelope, cfo, slope, curvature, seed, snr=12., noise_only=False):
    t = np.arange(N) / FS
    env = np.interp((np.arange(N)+110000+seed*19)*.08, np.arange(len(envelope)), envelope)
    # Phase is the analytic integral of injected instantaneous frequency.
    phase = 2*np.pi*((IF+cfo)*t + .5*slope*t*t + curvature*t**3/6) + .71
    clean = env*np.cos(phase)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, np.sqrt(np.mean(clean**2))*10**(-snr/20), N)
    data = np.rint((0 if noise_only else clean)+noise+137)
    return np.clip(data, -8192, 8191).astype(np.int16), cfo+slope*t+.5*curvature*t*t


def load_library(path):
    lib = ct.CDLL(str(path.resolve()))
    p = ct.POINTER
    lib.dp_defaults.argtypes = [p(Config), ct.c_uint32, ct.c_uint32]
    lib.dp_init.argtypes = [p(Tracker), p(Config)]
    lib.dp_set_prediction.argtypes = [p(Tracker), p(Prediction)]
    lib.dp_set_mode.argtypes = [p(Tracker), ct.c_int]
    lib.dp_plan.argtypes = [p(Tracker), ct.c_uint32, p(Output)]
    lib.adda_receive.argtypes = [p(ct.c_int16), ct.c_size_t, p(Frame), p(Stats)]
    lib.adda_receive_planned.argtypes = [*lib.adda_receive.argtypes, p(Plan)]
    lib.adp_receive.argtypes = [p(Tracker), p(ct.c_int16), ct.c_size_t,
        ct.c_uint32, ct.c_uint32, ct.c_uint32, ct.c_uint32, p(Frame), p(Stats), p(Trace)]
    return lib


def new_tracker(lib, mode, start=0, cfo=2000, rate=20, duration=20000):
    cfg, tracker = Config(), Tracker()
    lib.dp_defaults(ct.byref(cfg), 1, 0)
    assert lib.dp_init(ct.byref(tracker), ct.byref(cfg)) == 0
    prediction = Prediction(start, duration, 100.5e6, cfo, rate)
    assert lib.dp_set_prediction(ct.byref(tracker), ct.byref(prediction)) == 0
    assert lib.dp_set_mode(ct.byref(tracker), mode) == 0
    return tracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    lib, envelope = load_library(args.library), make_source()
    rows = []
    scenarios = [
        # name, true CFO, true slope, true curvature, model CFO, model slope
        ('matched_prediction', 1500., 30., 0., 1500., 30.),
        ('static_bias', 1500., 0., 0., 1200., 0.),
        ('ramp_bias', 2500., 37., 0., 2100., 30.),
        ('smooth_bias', 2300., 80., 12., 2000., 70.),
        ('acquisition_stress', 48000., 30., 0., 47700., 25.),
        ('chirp_stress', 1500., 200000., 0., 1200., 190000.),
        ('negative_chirp_stress', 1500., -200000., 0., 1200., -190000.),
    ]
    for scenario, f0, slope, curve, prediction, pred_rate in scenarios:
        for trial in range(8):
            samples, truth = waveform(envelope, f0, slope, curve, trial+71, snr=10+trial%3*3)
            ptr = samples.ctypes.data_as(ct.POINTER(ct.c_int16))
            for mode in ('uncompensated_reference', 'prediction_only', 'legacy_measurement', 'hybrid'):
                frame, stats, trace = Frame(), Stats(), Trace()
                planned = mode in ('prediction_only', 'hybrid')
                rate = pred_rate if planned else 0.
                begin = time.perf_counter()
                if mode == 'legacy_measurement':
                    rc = lib.adda_receive(ptr, N, ct.byref(frame), ct.byref(stats))
                elif mode == 'hybrid':
                    tracker = new_tracker(lib, 3, start=1, cfo=prediction, rate=pred_rate,
                                          duration=100 if 'chirp_stress' in scenario else 20000)
                    rc = lib.adp_receive(ct.byref(tracker), ptr, N, 1, 21, 0, 1,
                                         ct.byref(frame), ct.byref(stats), ct.byref(trace))
                    assert trace.planned, (scenario, trace.plan_result)
                    rate = -trace.applied_rate_hz_s
                else:
                    plan = Plan(IF+(prediction if planned else 0), rate, 0)
                    rc = lib.adda_receive_planned(ptr, N, ct.byref(frame), ct.byref(stats), ct.byref(plan))
                elapsed = (time.perf_counter()-begin)*1000
                success = rc == 1 and bytes(frame.body).hex() == '01640092090077ab'
                if rc == 1:
                    assert success, 'A valid CRC must also contain the exact transmitted body'
                applied = stats.carrier_hz - IF + rate*np.arange(N)/FS
                residual = truth-applied
                rows.append(dict(scenario=scenario, trial=trial, mode=mode, crc_ok=success,
                    estimated_start_cfo_hz=stats.carrier_hz-IF, applied_rate_hz_s=rate,
                    residual_rms_hz=float(np.sqrt(np.mean(residual**2))),
                    residual_p95_hz=float(np.percentile(abs(residual), 95)),
                    residual_max_hz=float(max(abs(residual))), host_decode_ms=elapsed))

    # Genuine cross-capture observations, including deliberate loss. Model and
    # source differ; the C filter sees only the actual estimator output.
    tracker = new_tracker(lib, 3)
    tracking = []
    for i in range(24):
        t_ms = 100+i*400
        t = t_ms*.001
        true_cfo = 2350+22*t+15*np.sin(.8*t)
        true_rate = 22+12*np.cos(.8*t)
        missing = i in (7, 8, 9, 10, 11)
        samples, _ = waveform(envelope, true_cfo, true_rate, -9.6*np.sin(.8*t), i+171,
                              snr=14, noise_only=missing)
        frame, stats, trace = Frame(), Stats(), Trace()
        before = tracker.accepted
        rc = lib.adp_receive(ct.byref(tracker), samples.ctypes.data_as(ct.POINTER(ct.c_int16)),
            N, t_ms, t_ms+100, 1, i+1, ct.byref(frame), ct.byref(stats), ct.byref(trace))
        if missing:
            assert rc==0 and tracker.accepted==before
        else:
            assert rc==1 and tracker.accepted==before+1, (i, rc, trace.observation_result)
        tracking.append(dict(capture_ms=t_ms, available=not missing, state=trace.plan.state,
            predicted_hz=trace.plan.prediction_hz, filtered_residual_hz=trace.plan.residual_hz,
            requested_cfo_hz=trace.plan.total_hz, measured_cfo_hz=trace.measured_cfo_hz if rc==1 else None,
            applied_correction_hz=trace.applied_correction_hz, crc_ok=rc==1, truth_hz=true_cfo,
            observation_result=trace.observation_result, accepted=tracker.accepted))
    assert any(r['state']==4 for r in tracking), 'Missing frames must expose HOLD'
    assert tracker.accepted==19
    # Stale model must fall back to unchanged receive, without inventing a
    # new accepted measurement or extending model validity.
    samples, _ = waveform(envelope, 2500, 0, 0, 20)
    ptr = samples.ctypes.data_as(ct.POINTER(ct.c_int16))
    frame, stats, trace = Frame(), Stats(), Trace()
    before = tracker.accepted
    assert lib.adp_receive(ct.byref(tracker),ptr,N,21000,21100,1,99,
        ct.byref(frame),ct.byref(stats),ct.byref(trace))==1
    assert not trace.planned and trace.plan_result==2 and tracker.accepted==before
    # Runtime OFF is the normal existing decoder, not the uncompensated arm.
    lib.dp_set_mode(ct.byref(tracker), 0)
    frame2, stats2 = Frame(), Stats()
    rc = lib.adda_receive(ptr,N,ct.byref(frame),ct.byref(stats))
    assert lib.adp_receive(ct.byref(tracker),ptr,N,1,2,1,100,
        ct.byref(frame2),ct.byref(stats2),ct.byref(trace))==rc
    assert bytes(frame.body)==bytes(frame2.body)
    assert stats.carrier_hz==stats2.carrier_hz and stats.carrier_phase==stats2.carrier_phase
    # Clipping, uncertain capture epoch and wrong link cannot train the filter.
    tracker = new_tracker(lib, 3, cfo=2200, rate=0)
    clipped = samples.copy()
    clipped[:200] = 8191
    lib.adp_receive(ct.byref(tracker),clipped.ctypes.data_as(ct.POINTER(ct.c_int16)),N,
        100,200,1,1,ct.byref(frame),ct.byref(stats),ct.byref(trace))
    assert trace.clipped_samples>=200 and tracker.accepted==0 and trace.observation_result==3
    lib.adp_receive(ct.byref(tracker),ptr,N,200,300,21,2,
        ct.byref(frame),ct.byref(stats),ct.byref(trace))
    assert not trace.planned and not trace.plan.valid and tracker.accepted==0
    tracker.config.channel=1
    lib.adp_receive(ct.byref(tracker),ptr,N,300,400,1,3,
        ct.byref(frame),ct.byref(stats),ct.byref(trace))
    assert not trace.planned and trace.plan_result==4 and tracker.accepted==0
    # An already corrected sample stream must not be confused with the raw ADC
    # observations used here; that algebra is independently covered in C.
    # Reject invalid mixer contracts before allocation/indexing.
    for bad in (Plan(float('nan'),0,1000), Plan(IF,float('inf'),1000),
                Plan(IF,0,1), Plan(FS/4,0,40000), Plan(IF,0,-1)):
        assert lib.adda_receive_planned(ptr,N,ct.byref(frame),ct.byref(stats),ct.byref(bad))<0

    summary = []
    for scenario, *_ in scenarios:
        for mode in ('uncompensated_reference','prediction_only','legacy_measurement','hybrid'):
            group = [r for r in rows if r['scenario']==scenario and r['mode']==mode]
            summary.append(dict(scenario=scenario,mode=mode,frames=len(group),
                crc_pass=sum(r['crc_ok'] for r in group),
                rms_hz=float(np.sqrt(np.mean([r['residual_rms_hz']**2 for r in group]))),
                p95_hz=max(r['residual_p95_hz'] for r in group),
                max_hz=max(r['residual_max_hz'] for r in group),
                host_ms_median=float(np.median([r['host_decode_ms'] for r in group]))))
    for group in summary:
        if group['mode']=='hybrid':
            assert group['crc_pass']==group['frames'], group
            assert group['rms_hz']<50, group
        if group['scenario']=='matched_prediction' and group['mode']=='prediction_only':
            assert group['crc_pass']==group['frames'], group
    report = dict(kind='HOST SYNTHETIC, not board/RF execution', sample_rate_hz=FS, samples=N,
        seed_rule='trial+71 and cross-capture index+171', tracker_bytes=ct.sizeof(Tracker),
        uncompensated_reference_is_not_default_firmware=True,
        summary=summary, rows=rows, tracking=tracking,
        limitations=['Raw ADC synthesis, not calibrated RF', 'Host timing is not Cortex-A9 timing',
                     '100.5 MHz control receiver only; business relay unmodified',
                     'Stress scenarios are algorithm boundaries, not an orbital trajectory'])
    (args.out/'dynamic_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for name,data in [('dynamic_frames',rows),('dynamic_tracking',tracking)]:
        with (args.out/(name+'.csv')).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    print(f'PASS four-arm waveform comparison: {len(rows)} captures; cross-capture tracking: 24; runtime OFF/expiry/contracts')
    for r in summary:
        print(f"{r['scenario']:20s} {r['mode']:25s} CRC {r['crc_pass']}/{r['frames']} residual RMS {r['rms_hz']:.3f} Hz")


if __name__=='__main__':
    main()
