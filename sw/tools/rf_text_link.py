"""Offline experimental text link: AAAA | length | UTF-8 | payload CRC16.

This is NOT a CCSDS telecontrol frame. No device/network operations are present.
CRC acceptance is not a bit-error-rate measurement or authentication.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ccsds"))
from ccsds_tm_tx import crc16, srrc

FS, RS, BETA, SPAN = 2_500_000, 100_000, 0.35, 8
PREAMBLE = b"\xaa\xaa"


def _rates(fs, rs):
    if not np.isfinite(fs) or not np.isfinite(rs) or fs <= 0 or rs <= 0:
        raise ValueError("Positive finite sample/symbol rates required")
    sps = int(round(fs / rs))
    if sps < 2 or abs(fs / rs - sps) > 1e-9:
        raise ValueError("An integer number of samples per symbol >=2 is required")
    return sps


def build_frame(text, corrupt_crc=False):
    payload = text.encode("utf-8")
    if not 1 <= len(payload) <= 200:
        raise ValueError("Text must contain 1..200 UTF-8 bytes")
    if not isinstance(corrupt_crc, bool):
        raise ValueError("corrupt_crc must be boolean")
    checksum = crc16(payload) ^ int(corrupt_crc)
    return PREAMBLE + bytes([len(payload)]) + payload + struct.pack(">H", checksum)


def generate_iq(text, amplitude=0.1, sample_rate_hz=FS, symbol_rate=RS,
                offset_hz=500_000, corrupt_crc=False):
    """Return periodically shaped (N,2) signed int16 LE I/Q and a manifest."""
    sps = _rates(sample_rate_hz, symbol_rate)
    if not np.isfinite(amplitude) or not 0 < amplitude <= 1:
        raise ValueError("amplitude must satisfy 0 < amplitude <= 1")
    if not np.isfinite(offset_hz) or abs(offset_hz)+(1+BETA)*symbol_rate/2 >= sample_rate_hz/2:
        raise ValueError("Waveform crosses Nyquist")
    frame = build_frame(text, corrupt_crc)
    bits = np.unpackbits(np.frombuffer(frame, dtype=np.uint8))
    n = len(bits)*sps
    cycles = offset_hz*n/sample_rate_hz
    if abs(cycles-round(cycles)) > 1e-8:
        raise ValueError("Carrier phase must close over the cyclic frame block")
    up = np.zeros(3*n)
    up[::sps] = np.tile(1.0-2.0*bits, 3)
    shaped = np.convolve(up, srrc(BETA, sps, span=SPAN), "same")[n:2*n]
    signal = shaped*np.exp(2j*np.pi*offset_hz*np.arange(n)/sample_rate_hz)
    signal *= amplitude/np.max(abs(signal))
    iq = np.rint(np.column_stack((signal.real, signal.imag))*32767).astype("<i2")
    raw = iq.tobytes()
    manifest = dict(format="EXPERIMENTAL_TEXT_AAAA_LEN_UTF8_CRC16", ccsds=False,
                    text=text, payload_hex=text.encode("utf-8").hex(), frame_hex=frame.hex(),
                    payload_bytes=len(frame)-5, frame_bits=len(bits), complex_samples=n,
                    byte_count=len(raw), dtype="signed int16 little-endian", channel_order="I0,Q0,I1,Q1,...",
                    sample_rate_hz=sample_rate_hz, symbol_rate= symbol_rate, samples_per_symbol=sps,
                    beta=BETA, span_symbols=SPAN, offset_hz=offset_hz,
                    amplitude=amplitude, amplitude_reference="normalized complex peak, not RF power",
                    cyclic_shaping="three frames shaped, center frame retained",
                    crc="CRC-16/CCITT-FALSE over payload only, big-endian",
                    corrupt_crc=corrupt_crc, test_only=corrupt_crc,
                    sha256=hashlib.sha256(raw).hexdigest())
    return iq, manifest


def _frames(bits, first_sample, sps, inverted):
    """Exact preamble search at arbitrary bit positions; never knows TX text."""
    pre = np.unpackbits(np.frombuffer(PREAMBLE, dtype=np.uint8))
    matches = np.flatnonzero(np.correlate(2*bits.astype(np.int16)-1,
                                         2*pre.astype(np.int16)-1, "valid") == 16)
    frames, stats = [], dict(preamble_candidates=0, invalid_lengths=0,
                            incomplete_candidates=0, complete_evaluated_frames=0,
                            crc_rejected_frames=0, crc_evaluated_candidate_bits=0)
    next_bit = 0
    for start in matches:
        start = int(start)
        if start < next_bit:
            continue
        stats["preamble_candidates"] += 1
        if start+24 > len(bits):
            stats["incomplete_candidates"] += 1; continue
        length = int(np.packbits(bits[start+16:start+24])[0])
        if not 1 <= length <= 200:
            stats["invalid_lengths"] += 1; continue
        total = (length+5)*8
        if start+total > len(bits):
            stats["incomplete_candidates"] += 1; continue
        data = np.packbits(bits[start+24:start+total]).tobytes()
        payload, received_crc = data[:-2], int.from_bytes(data[-2:], "big")
        stats["complete_evaluated_frames"] += 1
        stats["crc_evaluated_candidate_bits"] += total
        if crc16(payload) != received_crc:
            stats["crc_rejected_frames"] += 1; continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        frames.append(dict(text=text, payload_hex=payload.hex(), payload_bytes=length,
                           crc16=received_crc, crc_valid=True, bit_offset=start,
                           frame_bits=total, first_symbol_sample=first_sample+start*sps,
                           sample_end_exclusive=first_sample+(start+total)*sps,
                           inverted=bool(inverted)))
        next_bit = start+total
    return frames, stats


def decode(raw_bytes, sample_rate_hz=FS, symbol_rate=RS,
           expected_offset_hz=-250_000, search_hz=20_000):
    """Decode 12-bit sign-extended I/Q; phase/CFO/frame search is text-blind.

    Matching-filter edges are excluded. Bit offsets refer to the selected timing
    decision stream, whose first symbol sample is reported explicitly.
    """
    sps = _rates(sample_rate_hz, symbol_rate)
    if not raw_bytes or len(raw_bytes) % 4:
        raise ValueError("Complete signed int16 LE I/Q groups required")
    if not np.isfinite(expected_offset_hz) or not np.isfinite(search_hz) or not 0 < search_hz < symbol_rate/2:
        raise ValueError("Invalid carrier search")
    if abs(expected_offset_hz)+search_hz+(1+BETA)*symbol_rate/2 >= sample_rate_hz/2:
        raise ValueError("Receive signal/search crosses Nyquist")
    iq = np.frombuffer(raw_bytes, dtype="<i2").reshape(-1, 2)
    if len(iq) < sps*48 or iq.min() < -2048 or iq.max() > 2047:
        raise ValueError("At least 48 symbols of sign-extended 12-bit I/Q required")
    z = iq[:, 0].astype(float)+1j*iq[:, 1]
    t = np.arange(len(z))/sample_rate_hz
    # Mix BEFORE squaring: a +750kHz branch must not alias at2*fcarrier.
    mixed = (z-z.mean())*np.exp(-2j*np.pi*expected_offset_hz*t)
    squared = mixed*mixed
    nfft = 1 << int(np.ceil(np.log2(4*len(z))))
    power = abs(np.fft.fft(squared*np.hanning(len(z)), nfft))**2
    freq = np.fft.fftfreq(nfft, 1/sample_rate_hz)
    bins = np.flatnonzero(abs(freq) <= 2*search_hz)
    peak = int(bins[np.argmax(power[bins])])
    neighborhood = np.log(np.maximum(power[[(peak-1)%nfft, peak, (peak+1)%nfft]], 1e-30))
    denominator = neighborhood[0]-2*neighborhood[1]+neighborhood[2]
    delta = float(np.clip(.5*(neighborhood[0]-neighborhood[2])/denominator, -.5, .5)) if denominator < 0 else 0.0
    residual = float((freq[peak]+delta*sample_rate_hz/nfft)/2)
    corrected = mixed*np.exp(-2j*np.pi*residual*t)
    phase = float(np.angle(np.sum(corrected**2))/2)
    corrected *= np.exp(-1j*phase)
    matched = np.convolve(corrected, srrc(BETA, sps, span=SPAN), "same")
    margin = SPAN*sps//2
    best, ranking = None, None
    for timing in range(sps):
        first = margin+timing
        values = matched[first:len(matched)-margin:sps]
        # CRC count selects data-supported timing; eye opening breaks ties.
        eye = float(np.mean(abs(values.real))/max(np.sqrt(np.mean(abs(values)**2)), 1e-30))
        for inverted in (False, True):
            bits = ((values.real < 0) ^ inverted).astype(np.uint8)
            frames, stats = _frames(bits, first, sps, inverted)
            rank = (len(frames), stats["complete_evaluated_frames"], eye)
            if ranking is None or rank > ranking:
                ranking = rank
                best = dict(frames=frames, **stats, timing_phase_samples=timing,
                            decision_first_sample=first, evaluable_symbol_bits=len(bits),
                            selected_polarity_inverted=inverted)
    for frame in best["frames"]:
        frame["carrier_offset_hz"] = float(expected_offset_hz+residual)
    return dict(format="EXPERIMENTAL_TEXT_AAAA_LEN_UTF8_CRC16", ccsds=False,
                samples=len(z), bytes=len(raw_bytes), sha256=hashlib.sha256(raw_bytes).hexdigest(),
                sample_rate_hz=sample_rate_hz, symbol_rate=symbol_rate,
                expected_offset_hz=expected_offset_hz, residual_frequency_hz=residual,
                carrier_offset_hz=float(expected_offset_hz+residual), carrier_phase_rad=phase,
                carrier_estimator="pre-mix then square-law FFT, residual search; estimate is not evidence without CRC frames",
                timing_trials=sps, polarity_trials=2, filter_edge_margin_samples=margin,
                valid_frame_count=len(best["frames"]), valid_frame_bits=sum(f["frame_bits"] for f in best["frames"]),
                valid_payload_bits=sum(f["payload_bytes"]*8 for f in best["frames"]),
                clip_components=int(np.count_nonzero((iq == -2048) | (iq == 2047))),
                rms_codes=float(np.sqrt(np.mean(abs(z)**2))),
                ber=None, ber_note="CRC acceptance does not establish BER0; no expected payload used",
                candidate_count_scope="selected timing/polarity; incomplete filter edges excluded; candidate bits are not BER trials",
                **best)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    gen = commands.add_parser("generate")
    gen.add_argument("--text", required=True)
    gen.add_argument("--amplitude", type=float, default=.1)
    gen.add_argument("--corrupt-crc", action="store_true")
    gen.add_argument("--out", required=True, type=Path, help="new directory")
    rx = commands.add_parser("decode")
    rx.add_argument("capture", type=Path)
    rx.add_argument("--sample-rate", type=float, default=FS)
    rx.add_argument("--symbol-rate", type=float, default=RS)
    rx.add_argument("--offset", type=float, default=-250_000)
    rx.add_argument("--search-hz", type=float, default=20_000)
    rx.add_argument("--out", type=Path, help="new JSON file")
    args = parser.parse_args(argv)
    if args.action == "generate":
        iq, report = generate_iq(args.text, args.amplitude, corrupt_crc=args.corrupt_crc)
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/"iq_s16le.bin").write_bytes(iq.tobytes())
        (args.out/"manifest.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    else:
        report = decode(args.capture.read_bytes(), args.sample_rate, args.symbol_rate, args.offset, args.search_hz)
        if args.out:
            with args.out.open("x", encoding="utf-8") as f:
                json.dump(report, f, indent=2, allow_nan=False)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
