"""Measure a complex tone in captured interleaved little-endian int16 I/Q.

Levels refer to ADC codes, not calibrated RF power. Use identical receiver
settings for signal-on, signal-off and relay-muted comparisons.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def analyze(raw, sample_rate_hz, expected_offset_hz, *, adc_bits=12, search_hz=20000):
    if not raw or len(raw) % 4:
        raise ValueError('Expected complete interleaved int16 I/Q samples')
    if not np.isfinite(sample_rate_hz) or sample_rate_hz <= 0:
        raise ValueError('Invalid sample rate')
    if not 2 <= adc_bits <= 16:
        raise ValueError('Invalid ADC bit count')
    if not np.isfinite(expected_offset_hz) or not 0 < search_hz < sample_rate_hz/2:
        raise ValueError('Invalid search interval')
    if abs(expected_offset_hz) + search_hz >= sample_rate_hz/2:
        raise ValueError('Search interval crosses Nyquist')
    iq = np.frombuffer(raw, dtype='<i2').reshape(-1, 2)
    n = len(iq)
    if n < 32:
        raise ValueError('At least 32 complex samples are required')
    full_scale = 1 << (adc_bits - 1)
    if iq.min() < -full_scale or iq.max() > full_scale-1:
        raise ValueError('Sample codes exceed the declared signed ADC format')
    z = iq[:, 0].astype(float) + 1j*iq[:, 1]
    window = np.hanning(n)
    spectrum = np.fft.fftshift(np.fft.fft((z-z.mean()) * window))
    freq = np.fft.fftshift(np.fft.fftfreq(n, 1/sample_rate_hz))
    power = abs(spectrum)**2 / (n*np.sum(window**2))
    search = abs(freq-expected_offset_hz) <= search_hz
    bins = np.flatnonzero(search)
    if len(bins) < 3:
        raise ValueError('Search interval needs at least three FFT bins')
    peak = int(bins[np.argmax(power[bins])])
    delta = 0.0
    if 0 < peak < n-1:
        left, center, right = np.log(np.maximum(power[peak-1:peak+2], 1e-30))
        denom = left-2*center+right
        if denom < 0:
            delta = float(np.clip(.5*(left-right)/denom, -.5, .5))
    noise_mask = (abs(freq-expected_offset_hz) > 2*search_hz) & (abs(freq) > search_hz)
    if not noise_mask.any():
        raise ValueError('No bins remain for the noise estimate')
    band = float(power[search].sum())
    noise_per_bin = float(np.median(power[noise_mask]))
    def db(value):
        return float(10*np.log10(max(value, 1e-30)))
    return dict(samples=n, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                sample_rate_hz=sample_rate_hz, adc_bits=adc_bits,
                expected_offset_hz=expected_offset_hz, search_half_width_hz=search_hz,
                fft_bin_hz=sample_rate_hz/n,
                peak_offset_hz=float(freq[peak]+delta*sample_rate_hz/n),
                band_power_dbfs=db(band/full_scale**2),
                band_to_median_noise_db=db(band/max(noise_per_bin*len(bins), 1e-30)),
                rms_codes=float(np.sqrt(np.mean(abs(z)**2))),
                min_code=int(iq.min()), max_code=int(iq.max()),
                clip_components=int(np.count_nonzero((iq == -full_scale) | (iq == full_scale-1))),
                mean_i=float(z.real.mean()), mean_q=float(z.imag.mean()),
                level_reference='ADC full-scale complex magnitude; not RF dBm')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--sample-rate', type=float, required=True)
    parser.add_argument('--offset', type=float, required=True)
    parser.add_argument('--adc-bits', type=int, default=12)
    parser.add_argument('--search-hz', type=float, default=20000)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = analyze(args.capture.read_bytes(), args.sample_rate, args.offset,
                     adc_bits=args.adc_bits, search_hz=args.search_hz)
    text = json.dumps(result, indent=2) + '\n'
    if args.out:
        args.out.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
