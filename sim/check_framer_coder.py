"""check_framer_coder.py -- locate exactly which stage of the FPGA TX chain
disagrees with the verified software reference.

Reads the two dumps produced by tb_framer_coder.vhd and asks three separate
questions:

  Q1  does the FPGA framer build the same 20 byte frame as build_tm_frame()?
  Q2  does the FPGA coder turn the FPGA's OWN frame into the Python CADU?
      (this isolates randomiser + convolutional coder + ASM from the framer)
  Q3  does the FPGA coder turn Python's frame into the Python CADU?

A PASS on Q2 with a FAIL on Q1 means the coding chain is correct and only the
header/CRC bytes differ; a FAIL on Q2 means the randomiser or the convolutional
encoder is still wrong.
"""

import struct
import sys

import numpy as np

SW_DIR = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
OUT = r"E:\ccsds_fpga\sim\out"
sys.path.insert(0, SW_DIR)
from ccsds_tm_tx import (  # noqa: E402
    ASM,
    build_cadu,
    build_tm_frame,
    bytes_to_bits,
)

PAYLOAD = b"CCSDS-6G-NTN"


def load_chunks(path, count):
    vals = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                vals.append(int(line))
    vals = vals[:count]
    if len(vals) != count:
        raise SystemExit(f"{path}: expected {count} chunks, got {len(vals)}")
    return np.array(vals, dtype=">u2").tobytes()


def bits_of(data):
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return -1 if len(a) == len(b) else n


def show_diff(name, got, ref):
    i = first_diff(got, ref)
    if i < 0:
        print(f"  {name}: IDENTICAL ({len(got)} bits)")
        return True
    byte, bit = divmod(i, 8)
    print(f"  {name}: first difference at bit {i} (byte {byte}, bit {7-bit} of "
          f"that byte)  got={got[i]} ref={ref[i]}")
    print(f"    got[{(i//8)*8}:(i//8)*8+16] = {got[(i//8)*8:(i//8)*8+16]}")
    print(f"    ref[{(i//8)*8}:(i//8)*8+16] = {ref[(i//8)*8:(i//8)*8+16]}")
    return False


def main():
    print("=" * 72)
    print(" FPGA framer / coder isolation")
    print("=" * 72)

    fpga_frame = load_chunks(f"{OUT}\\framer_bits.txt", 10)   # 160 bit = 20 B
    fpga_cadu = load_chunks(f"{OUT}\\coder_bits.txt", 22)    # 352 bit = 44 B

    ref_frame = build_tm_frame(scid=0x2A, vcid=0, mcfc=0, vcfc=0,
                               data=PAYLOAD, fecf=True)
    print(f"\npayload fed to framer : {PAYLOAD!r}")

    print("\n--- Q1: FPGA framer vs build_tm_frame ---")
    print(f"  fpga frame : {fpga_frame.hex()}")
    print(f"  ref  frame : {ref_frame.hex()}")
    q1 = show_diff("frame", bits_of(fpga_frame), bytes_to_bits(ref_frame))

    # field-by-field view of the FPGA frame, using Python's own parser
    from ccsds_tm_tx import parse_tm_frame  # noqa: E402
    p = parse_tm_frame(fpga_frame)
    print(f"  fpga frame parsed : SCID=0x{p['scid']:03X} VCID={p['vcid']} "
          f"MCFC={p['mcfc']} VCFC={p['vcfc']} OCF={p['ocf']} "
          f"CRC rx=0x{p['crc_rx']:04X} calc=0x{p['crc_calc']:04X} "
          f"payload={p['payload']!r}")

    print("\n--- Q2: FPGA coder on the FPGA's own frame (isolates coding) ---")
    ref_cadu_from_fpga_frame, _ = build_cadu(fpga_frame)
    q2 = show_diff("cadu", bits_of(fpga_cadu), ref_cadu_from_fpga_frame)

    print("\n--- Q3: FPGA coder on Python's frame ---")
    ref_cadu_from_ref_frame, _ = build_cadu(ref_frame)
    q3 = show_diff("cadu", bits_of(fpga_cadu), ref_cadu_from_ref_frame)

    print("\n--- reference CADU bytes (Python) ---")
    print(f"  {np.packbits(ref_cadu_from_ref_frame).tobytes().hex()}")
    print(f"  fpga cadu : {fpga_cadu.hex()}")

    print("\n--- verdict ---")
    print(f"  Q1 framer        : {'PASS' if q1 else 'FAIL'}")
    print(f"  Q2 coder (own)   : {'PASS' if q2 else 'FAIL'}")
    print(f"  Q3 coder (python): {'PASS' if q3 else 'FAIL'}")
    if q2:
        print("  -> randomiser + convolutional coder + ASM are bit-exact.")
    else:
        print("  -> the coding stage still differs; Q1 tells whether the frame"
              " content is also involved.")
    return 0 if (q2 and q3) else 1


if __name__ == "__main__":
    sys.exit(main())
