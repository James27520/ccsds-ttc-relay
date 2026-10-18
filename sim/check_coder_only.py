"""check_coder_only.py -- compare the hardcoded-frame CADU dump with the
verified reference build_cadu()."""

import sys

import numpy as np

SW_DIR = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
OUT = r"E:\ccsds_fpga\sim\out"
sys.path.insert(0, SW_DIR)
from ccsds_tm_tx import build_cadu, bytes_to_bits, randomize  # noqa: E402

FRAME = bytes.fromhex("02a00000180043435344532d36472d4e544e14d2")


def main():
    vals = [int(x) for x in open(f"{OUT}\\coder_only_bits.txt") if x.strip()]
    got_bytes = np.array(vals[:22], dtype=">u2").tobytes()
    got = bytes_to_bits(got_bytes)

    ref_cadu, info = build_cadu(FRAME)
    ref = np.asarray(ref_cadu, dtype=np.uint8)

    print("=" * 72)
    print(" coder-only: FPGA CADU vs build_cadu(hardcoded frame)")
    print("=" * 72)
    print(f"  frame            : {FRAME.hex()}")
    print(f"  expected CADU    : {np.packbits(ref).tobytes().hex()}")
    print(f"  FPGA CADU        : {got_bytes.hex()}")

    d = np.nonzero(got != ref)[0]
    if len(d) == 0:
        print("\n  RESULT: IDENTICAL -- randomiser, convolutional coder and ASM"
              " insertion all match the reference bit for bit.")
        return 0

    print(f"\n  RESULT: {len(d)} differing bits, first at {d[0]}")
    # help localise: ASM occupies bits 0..31, coded frame 32..351
    if d[0] < 32:
        print("    -> the ASM region differs (synchronizer problem)")
    else:
        idx = (d[0] - 32) // 2
        print(f"    -> coded region, first bad symbol index {idx}"
              f" (input bit {idx})")
        print(f"       randomized input bits : {randomize(bytes_to_bits(FRAME))[:24]}")
        print(f"       FPGA coded  [32:64]   : {got[32:64]}")
        print(f"       refer coded [32:64]   : {ref[32:64]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
