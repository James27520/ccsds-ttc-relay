"""check_tx_chain.py -- feed the ModelSim-captured FPGA CADU into the already
hardware-verified Python ground receiver.

The point of this script is that it does NOT re-implement anything: it imports
the exact decoder that passed the two-board RF loopback test
(sw/ttc/ccsds_tm_tx.py :: decode_cadu), so a clean decode here means the
patched euryspace core produces a waveform that the real ground station can
read.

Run:  python check_tx_chain.py
"""

import struct
import sys

import numpy as np

SW_DIR = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
CAPTURE = r"E:\ccsds_fpga\sim\out\cadu_words.txt"

sys.path.insert(0, SW_DIR)
from ccsds_tm_tx import (  # noqa: E402
    ASM,
    build_cadu,
    build_tm_frame,
    bytes_to_bits,
    decode_cadu,
    parse_tm_frame,
)

EXPECTED_PAYLOAD = b"CCSDS-6G-NTN-7010-TTC-FPGA-PORT!"
# 4 byte ASM + 2 x (6 header + 32 payload + 2 FECF) bytes = 4 + 80 = 84
CADU_BYTES = 84


def load_capture(path):
    words = []
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if line:
                words.append(int(line))
    return np.array(words, dtype=">u2")


def main():
    print("=" * 72)
    print(" FPGA CCSDS TX chain  ->  verified Python ground receiver")
    print("=" * 72)

    words = load_capture(CAPTURE)
    print(f"captured words        : {len(words)}")
    raw = words.tobytes()
    print(f"captured bytes        : {len(raw)}")

    asm = struct.pack(">I", ASM)
    print(f"looking for ASM       : {asm.hex()}")

    hits = []
    start = 0
    while True:
        i = raw.find(asm, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    print(f"ASM occurrences       : {len(hits)} at byte offsets {hits[:8]}")

    if not hits:
        print("\nRESULT: FAIL -- the ASM never appears in the captured stream.")
        print("        The frame is not reaching the symbol mapper intact.")
        return 1

    # spacing between ASM hits tells us the frame period the serialiser used
    if len(hits) > 1:
        deltas = np.diff(hits)
        print(f"ASM spacing (bytes)   : {sorted(set(deltas.tolist()))[:6]}"
              f"   ({CADU_BYTES} = one CADU)")

    ok = 0
    frames = []
    for idx, off in enumerate(hits):
        if off + CADU_BYTES > len(raw):
            break
        cadu = np.unpackbits(np.frombuffer(raw[off:off + CADU_BYTES], dtype=np.uint8))
        frame, info = decode_cadu(cadu)
        if frame is None:
            print(f"  frame @{off:5d}: decode failed ({info.get('reason')})")
            continue
        parsed = parse_tm_frame(frame)
        if parsed is None:
            print(f"  frame @{off:5d}: not parseable")
            continue
        status = "CRC OK" if parsed["crc_ok"] else "CRC BAD"
        payload_ok = parsed["payload"] == EXPECTED_PAYLOAD
        print(f"  frame @{off:5d}: SCID=0x{parsed['scid']:03X} VCID={parsed['vcid']} "
              f"MCFC={parsed['mcfc']:3d} FHP=0x{parsed['fhp']:03X} {status} "
              f"(rx=0x{parsed['crc_rx']:04X} calc=0x{parsed['crc_calc']:04X}) "
              f"payload={'OK' if payload_ok else parsed['payload'][:16]!r}")
        if parsed["crc_ok"]:
            ok += 1
        frames.append(parsed)

    print()
    print(f"frames decoded        : {ok}/{len(hits)}")
    if ok == 0:
        print("\nRESULT: FAIL -- ASM found but the coded payload does not decode.")
        print("        Suspects: convolutional encoder taps/order, randomizer")
        print("        sequence, or the ASM being coded when it must not be.")
        return 1

    good_payload = [f for f in frames if f["crc_ok"] and f["payload"] == EXPECTED_PAYLOAD]
    print(f"payload byte-exact    : {len(good_payload)}/{ok}")

    # what the Python transmitter would have produced for the same frame,
    # assuming the FPGA framer built the same header (SCID 0x2A, MCFC 0)
    ref_frame = build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0,
                               data=EXPECTED_PAYLOAD, fecf=True)
    ref_cadu, _ = build_cadu(ref_frame)
    print(f"reference CADU bits   : {len(ref_cadu)} (4 byte ASM + 2x160 coded)")
    print(f"reference frame bytes : {ref_frame.hex()}")

    if ok > 0:
        print("\nRESULT: PASS -- the patched FPGA chain is decodable by the")
        print("        verified ground receiver.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
