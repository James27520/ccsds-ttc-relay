"""Offline cyclic experimental text sequence; conditional comparison, not BER.

Synchronization is text-blind but CRC selects timing and supplies the sequence
anchor. Never combine gaps between independent captures into loss statistics.
No hardware or network operations are provided.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from rf_text_link import FS, RS, BETA, SPAN, build_frame, decode, srrc

SPS, FRAME_BITS, OFFSET = 25, 128, 500_000
FORMAT = "EXPERIMENTAL_TEXT_SEQUENCE_V1"


def _shape(frames, amplitude):
    bits = np.unpackbits(np.frombuffer(b"".join(frames), dtype=np.uint8))
    n = len(bits)*SPS
    up = np.zeros(3*n)
    up[::SPS] = np.tile(1.-2.*bits, 3)
    shaped = np.convolve(up, srrc(BETA, SPS, span=SPAN), "same")[n:2*n]
    signal = shaped*np.exp(2j*np.pi*OFFSET*np.arange(n)/FS)
    signal *= amplitude/np.max(abs(signal))
    return np.rint(np.column_stack((signal.real, signal.imag))*32767).astype("<i2")


def generate_sequence(count=8, amplitude=.1):
    """Return a periodically shaped complete sequence and its source manifest."""
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
        raise ValueError("count must be an integer in 1..1000")
    if not np.isfinite(amplitude) or not 0 < amplitude <= 1:
        raise ValueError("amplitude must satisfy 0 < amplitude <= 1")
    frames = []
    mapping = []
    for seq in range(count):
        text = f"SEQ{seq:03d}:ABCD"
        frame = build_frame(text)
        frames.append(frame)
        mapping.append(dict(seq=seq, text=text, payload_hex=text.encode().hex(),
                            frame_hex=frame.hex(), bit_offset=seq*FRAME_BITS,
                            sample_offset=seq*FRAME_BITS*SPS))
    iq = _shape(frames, amplitude)
    return iq, dict(format=FORMAT, ccsds=False, count=count, frames=mapping,
                    sample_rate_hz=FS, symbol_rate=RS, samples_per_symbol=SPS,
                    beta=BETA, span_symbols=SPAN, offset_hz=OFFSET,
                    amplitude=amplitude, amplitude_reference="normalized complex peak, not RF power",
                    frame_bits=FRAME_BITS, frame_complex_samples=FRAME_BITS*SPS,
                    complex_samples=len(iq), byte_count=iq.nbytes,
                    dtype="signed int16 little-endian", channel_order="I0,Q0,I1,Q1,...",
                    cyclic_shaping="three complete sequences shaped, center sequence retained",
                    sha256=hashlib.sha256(iq.tobytes()).hexdigest())


def _validate(manifest):
    try:
        count = manifest["count"]
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1000:
            raise ValueError()
        fixed = dict(format=FORMAT, ccsds=False, sample_rate_hz=FS, symbol_rate=RS,
                     samples_per_symbol=SPS, beta=BETA, span_symbols=SPAN,
                     offset_hz=OFFSET, frame_bits=FRAME_BITS,
                     frame_complex_samples=FRAME_BITS*SPS,
                     complex_samples=count*FRAME_BITS*SPS, byte_count=count*FRAME_BITS*SPS*4,
                     dtype="signed int16 little-endian", channel_order="I0,Q0,I1,Q1,...")
        if any(manifest.get(k) != v for k, v in fixed.items()):
            raise ValueError()
        if len(manifest["frames"]) != count:
            raise ValueError()
        frames = []
        for seq, entry in enumerate(manifest["frames"]):
            text = f"SEQ{seq:03d}:ABCD"
            frame = build_frame(text)
            expected = dict(seq=seq, text=text, payload_hex=text.encode().hex(),
                            frame_hex=frame.hex(), bit_offset=seq*FRAME_BITS,
                            sample_offset=seq*FRAME_BITS*SPS)
            if any(entry.get(k) != v for k, v in expected.items()):
                raise ValueError()
            frames.append(frame)
        if len(manifest["sha256"]) != 64 or int(manifest["sha256"], 16) < 0:
            raise ValueError()
        if not np.isfinite(manifest["amplitude"]) or not 0 < manifest["amplitude"] <= 1:
            raise ValueError()
        return frames
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid or inconsistent sequence manifest") from exc


def analyze_sequence(raw, manifest, expected_offset_hz=-250_000):
    """Analyze ONE snapshot; count all aligned decisions after a CRC anchor.

    The conditional denominator includes corrupted/non-CRC-accepted regions,
    but excludes filter edges and windows with no known valid anchor. Such
    windows are explicitly retained as acquisition_failed, never BER trials.
    """
    frames = _validate(manifest)
    blind = decode(raw, expected_offset_hz=expected_offset_hz)
    mapping = {entry["payload_hex"]: entry["seq"] for entry in manifest["frames"]}
    accepted = [dict(f, sequence_id=mapping.get(f["payload_hex"])) for f in blind["frames"]]
    known = [f for f in accepted if f["sequence_id"] is not None]
    transitions = []
    for left, right in zip(accepted, accepted[1:]):
        delta = right["bit_offset"]-left["bit_offset"]
        steps, remainder = divmod(delta, FRAME_BITS)
        expected = ((left["sequence_id"]+steps) % manifest["count"]
                    if left["sequence_id"] is not None else None)
        consistent = (not remainder and steps >= 1 and expected is not None
                      and right["sequence_id"] == expected)
        transitions.append(dict(from_seq=left["sequence_id"], to_seq=right["sequence_id"],
                                sample_delta=delta*SPS, frame_steps=steps,
                                unaccepted_frame_slots=max(0, steps-1), consistent=bool(consistent)))
    report = dict(acquisition_failed=not bool(known), accepted_frames=accepted,
                  unexpected_payload_frames=sum(f["sequence_id"] is None for f in accepted),
                  sequence_transitions=transitions, decision_bits=blind["evaluable_symbol_bits"],
                  conditional_compared_bits=0, conditional_bit_errors=0, anchor=None,
                  ber=None, scope="One saved snapshot only; CRC-selected synchronization and known-sequence anchor; conditional errors are not overall BER",
                  blind_decode=blind)
    if known:
        # Reconstruct exactly the selected existing decoder decision stream.
        iq = np.frombuffer(raw, dtype="<i2").reshape(-1, 2)
        z = iq[:, 0].astype(float)+1j*iq[:, 1]
        t = np.arange(len(z))/FS
        corrected = (z-z.mean())*np.exp(-2j*np.pi*blind["carrier_offset_hz"]*t)
        corrected *= np.exp(-1j*blind["carrier_phase_rad"])
        matched = np.convolve(corrected, srrc(BETA, SPS, span=SPAN), "same")
        values = matched[blind["decision_first_sample"]:len(z)-blind["filter_edge_margin_samples"]:SPS]
        bits = ((values.real < 0) ^ blind["selected_polarity_inverted"]).astype(np.uint8)
        reference = np.unpackbits(np.frombuffer(b"".join(frames), dtype=np.uint8))
        anchor = known[0]
        indices = (np.arange(len(bits))-anchor["bit_offset"]+anchor["sequence_id"]*FRAME_BITS) % len(reference)
        report.update(conditional_compared_bits=len(bits),
                      conditional_bit_errors=int(np.count_nonzero(bits != reference[indices])),
                      anchor=dict(seq=anchor["sequence_id"], bit_offset=anchor["bit_offset"],
                                  first_symbol_sample=anchor["first_symbol_sample"]))
    report["passed"] = bool(known and not report["conditional_bit_errors"]
                            and not report["unexpected_payload_frames"]
                            and all(t["consistent"] for t in transitions))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--count", type=int, default=8)
    gen.add_argument("--amplitude", type=float, default=.1)
    gen.add_argument("--out", type=Path, required=True)
    rx = sub.add_parser("analyze")
    rx.add_argument("capture", type=Path)
    rx.add_argument("manifest", type=Path)
    rx.add_argument("--offset", type=float, default=-250_000)
    rx.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.action == "generate":
        iq, report = generate_sequence(args.count, args.amplitude)
        args.out.mkdir(parents=True, exist_ok=False)
        (args.out/"iq_s16le.bin").write_bytes(iq.tobytes())
        (args.out/"manifest.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    else:
        report = analyze_sequence(args.capture.read_bytes(), json.loads(args.manifest.read_text(encoding="utf-8")), args.offset)
        if args.out:
            with args.out.open("x", encoding="utf-8") as f:
                json.dump(report, f, indent=2, allow_nan=False)
    print(json.dumps(report, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
