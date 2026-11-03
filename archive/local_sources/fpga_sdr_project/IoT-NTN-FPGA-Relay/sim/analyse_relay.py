#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyse_relay.py -- verify the relay datapath dumps produced by tb_relay.v

The stimulus is a complex tone at exactly fs/64, and every frequency word is a
power-of-two fraction of fs, so the output always has an integer number of
samples per period.  Taking a whole number of 64-sample blocks and using a
rectangular window puts the tone exactly on an FFT bin, which makes both the
frequency and the amplitude measurement exact (no window scalloping).

Run from E:\\LDSDR_010\\sim_relay after the ModelSim run.
"""
import os
import sys
import numpy as np

FS = 30.72e6
FSIG = FS / 64.0            # input tone offset = 480 kHz
HANN_GAIN = None            # unused for the exact method

# amplitude bookkeeping: one complex mixer multiplies by 2047/2048
MIX = 2047.0 / 2048.0

TOL_A = 0.02                # 2 % amplitude tolerance
HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    a = np.loadtxt(p, dtype=np.int64)
    return a[:, 0] + 1j * a[:, 1]


def whole_blocks(x, blk=64):
    m = (len(x) // blk) * blk
    return x[:m]


def tone_of(x, fs=FS):
    """Exact tone estimate using an integer number of periods."""
    x = whole_blocks(x)
    n = len(x)
    if n < 64:
        return float('nan'), float('nan')
    X = np.fft.fftshift(np.fft.fft(x))
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / fs))
    k = int(np.argmax(np.abs(X)))
    return float(f[k]), float(np.abs(X[k]) / n)


def report_tone(tag, x, exp_f, exp_a, fs=FS):
    if x is None:
        print("%-22s MISSING" % tag)
        return False
    f, a = tone_of(x, fs)
    ok_f = abs(f - exp_f) <= 1.0
    ok_a = abs(a - exp_a) <= TOL_A * max(exp_a, 1.0)
    print("%-22s f=%+9.1f kHz (exp %+9.1f) %s   amp=%8.1f (exp %8.1f) %s   n=%d"
          % (tag, f / 1e3, exp_f / 1e3, "OK" if ok_f else "**BAD**",
             a, exp_a, "OK" if ok_a else "**BAD**", len(x)))
    return ok_f and ok_a


def report_dc(tag, x, exp_a):
    """Output should be a constant complex value of magnitude exp_a."""
    if x is None:
        print("%-20s MISSING" % tag)
        return False
    x = whole_blocks(x)
    m = abs(x.mean())
    s = float(np.std(x))
    ok = abs(m - exp_a) <= TOL_A * max(exp_a, 1.0) and s < 0.02 * max(exp_a, 1.0)
    print("%-20s DC magnitude=%8.1f (exp %8.1f) %s   residual std=%6.2f   n=%d"
          % (tag, m, exp_a, "OK" if ok else "**BAD**", s, len(x)))
    return ok


def report_zero(tag, x):
    if x is None:
        print("%-20s MISSING" % tag)
        return False
    pk = float(np.max(np.abs(x)))
    ok = pk == 0.0
    print("%-20s max|out|=%6.0f  %s" % (tag, pk, "OK" if ok else "**BAD**"))
    return ok


def report_clip(tag, x):
    if x is None:
        print("%-22s MISSING" % tag)
        return False
    comp = np.maximum(np.abs(x.real), np.abs(x.imag))
    pk = float(comp.max())
    frac = float(np.mean(comp >= 2047))
    ok = (pk >= 2040.0) and (frac > 0.01)
    print("%-22s peak|I|or|Q|=%6.0f  saturated=%.1f%% of samples  %s"
          % (tag, pk, frac * 100.0, "OK" if ok else "**BAD**"))
    return ok


def main():
    print("fs = %.2f MHz   input tone = %+.1f kHz (fs/64)   mixer unity gain = %.6f"
          % (FS / 1e6, FSIG / 1e3, MIX))
    print("-" * 112)

    r = []
    # T1 : NCO phasor through the DUC, DC input, unity gain
    r.append(("T1  NCO phasor", report_tone("T1 NCO", load("nco.txt"),
                                            FSIG, 2047.0 * MIX)))
    # T2 : bypass
    r.append(("T2  bypass", report_tone("T2 bypass", load("bypass.txt"),
                                        FSIG, 2000.0)))
    # T3 : relay, ddc == duc  ->  net translation 0
    r.append(("T3  relay net 0", report_tone("T3 relay_netzero", load("relay_netzero.txt"),
                                             FSIG, 2000.0 * MIX * MIX)))
    # T4 : DUC only, +fs/64  ->  tone moves to fs/32
    r.append(("T4  DUC +fs/64", report_tone("T4 duc_only", load("duc_only.txt"),
                                            2 * FSIG, 2000.0 * MIX)))
    # T5 : relay, ddc=+fs/64, duc=0  ->  net -fs/64  ->  DC
    r.append(("T5  relay -fs/64", report_dc("T5 relay_minus", load("relay_minus.txt"),
                                            2000.0 * MIX)))
    # T6 : mute
    r.append(("T6  mute", report_zero("T6 mute", load("mute.txt"))))
    # T7 : DUC only, freq 0, gain 0.5
    r.append(("T7  gain 0.5", report_tone("T7 gain_half", load("gain_half.txt"),
                                          FSIG, 2000.0 * MIX * 0.5)))
    # T8 : gain ~2.0 -> saturation
    r.append(("T8  clip", report_clip("T8 clip", load("clip.txt"))))

    # ---- 2R2T : per-channel sample rate is dq_data_clk / 4 ----
    FS2 = FS / 4.0
    FSIG2 = FS2 / 64.0
    print("-" * 112)
    print("2R2T : per-channel fs = %.2f MHz, tone = %+.1f kHz" % (FS2 / 1e6, FSIG2 / 1e3))
    # T9 : DUC only +fs_ch/64 -> tone moves to fs_ch/32
    r.append(("T9  r2t DUC ch1", report_tone("T9 r2t_duc ch1", load("r2t_duc.txt"),
                                             2 * FSIG2, 2000.0 * MIX, FS2)))
    r.append(("T9  r2t DUC ch2", report_tone("T9 r2t_duc ch2", load("r2t_duc.txt_ch2.txt"),
                                             2 * FSIG2, 2000.0 * MIX, FS2)))
    # T10 : relay ddc == duc -> net 0
    r.append(("T10 r2t net0 ch1", report_tone("T10 r2t_net0 ch1", load("r2t_netzero.txt"),
                                              FSIG2, 2000.0 * MIX * MIX, FS2)))
    r.append(("T10 r2t net0 ch2", report_tone("T10 r2t_net0 ch2", load("r2t_netzero.txt_ch2.txt"),
                                              FSIG2, 2000.0 * MIX * MIX, FS2)))

    print("-" * 112)
    npass = sum(1 for _, ok in r if ok)
    for name, ok in r:
        if not ok:
            print("  FAILED : %s" % name)
    print("RESULT: %d/%d checks passed" % (npass, len(r)))
    return 0 if npass == len(r) else 1


if __name__ == "__main__":
    sys.exit(main())
