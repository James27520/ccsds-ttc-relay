"""diag_coder.py -- decide whether the FPGA convolutional stage really matches
ccsds_tm_tx.conv_encode, by modelling the VHDL parallel encoder line by line.

Three questions:
  A) Does the VHDL parallel encoder (vector form + MSB-first serialisation)
     reproduce conv_encode()?
  B) Does Viterbi-decoding the captured FPGA CADU payload return
     randomize(fpga_frame)?
  C) Does the captured FPGA CADU payload equal conv_encode(randomize(fpga_frame))?
"""

import sys

import numpy as np

SW_DIR = r"E:\fpga_sdr_project\ccsds_ttc_loopback\sw\ttc"
OUT = r"E:\ccsds_fpga\sim\out"
sys.path.insert(0, SW_DIR)
from ccsds_tm_tx import (  # noqa: E402
    bytes_to_bits,
    conv_decode_viterbi,
    conv_encode,
    randomize,
)


def load_chunks(path, count):
    vals = [int(x) for x in open(path) if x.strip()][:count]
    return np.array(vals, dtype=">u2").tobytes()


def vhdl_parallel_encode(v):
    """Faithful model of ccsds_tx_coder.vhd CONVOLUTIONAL_PARALLEL.

    v is the 160 bit frame, MSB first (v[0] is transmitted first).
    Returns the 320 bit coded vector in transmission order.
    """
    n = len(v)

    def bit(i):
        return int(v[i]) if 0 <= i < n else 0

    dat_o = np.zeros(2 * n, dtype=np.uint8)
    for j in range(n):
        p1 = bit(j) ^ bit(j + 3) ^ bit(j + 4) ^ bit(j + 5) ^ bit(j + 6)
        p2 = bit(j) ^ bit(j + 1) ^ bit(j + 3) ^ bit(j + 4) ^ bit(j + 6)
        dat_o[2 * j + 1] = p1
        dat_o[2 * j] = 1 ^ p2
    # serialisation is MSB first: dat_o(319) goes out first
    return dat_o[::-1]


def main():
    fpga_frame = load_chunks(f"{OUT}\\framer_bits.txt", 10)
    fpga_cadu = load_chunks(f"{OUT}\\coder_bits.txt", 22)

    fb = bytes_to_bits(fpga_frame)
    cb = bytes_to_bits(fpga_cadu)

    print("=" * 72)
    print(" A) VHDL parallel encoder  vs  conv_encode")
    print("=" * 72)
    rnd = randomize(fb)
    # The VHDL vector has index 159 transmitted first, so vector index j
    # corresponds to Python bit (n-1-j). Feed the model accordingly.
    got = vhdl_parallel_encode(rnd[::-1])
    ref = conv_encode(rnd)
    diff = np.nonzero(got != ref)[0]
    print(f"  randomize(fpga_frame) first 32 bits : {rnd[:32]}")
    print(f"  model coded  first 32 bits          : {got[:32]}")
    print(f"  python coded first 32 bits          : {ref[:32]}")
    if len(diff) == 0:
        print("  -> IDENTICAL over all 320 bits")
    else:
        print(f"  -> {len(diff)} differing bits, first at {diff[0]}")
        # is it a swap of the two branches?
        swapped = got.reshape(-1, 2)[:, ::-1].reshape(-1)
        d2 = np.nonzero(swapped != ref)[0]
        print(f"     branch-swapped model: {len(d2)} differing bits"
              f"{'' if len(d2) else '  <-- MATCHES'}")
        # is it the reverse-time mirror?
        rev = vhdl_parallel_encode(rnd[::-1])[::-1]
        d3 = np.nonzero(rev != ref)[0]
        print(f"     time-reversed model : {len(d3)} differing bits"
              f"{'' if len(d3) else '  <-- MATCHES'}")

    print()
    print("=" * 72)
    print(" B) Viterbi(FPGA cadu payload)  vs  randomize(fpga_frame)")
    print("=" * 72)
    enc = cb[32:32 + 2 * len(fb)]
    dec = conv_decode_viterbi(enc)
    n = min(len(dec), len(rnd))
    d = np.nonzero(dec[:n] != rnd[:n])[0]
    print(f"  viterbi decoded first 32 bits : {dec[:32]}")
    print(f"  randomize(frame) first 32 bits: {rnd[:32]}")
    if len(d) == 0:
        print("  -> IDENTICAL: the FPGA encoder IS conv_encode, and the "
              "randomiser alignment is right")
    else:
        print(f"  -> {len(d)} differing bits, first at {d[0]}")

    print()
    print("=" * 72)
    print(" C) FPGA cadu payload  vs  conv_encode(randomize(fpga_frame))")
    print("=" * 72)
    ref_cadu = np.concatenate([bytes_to_bits(np.frombuffer(bytes.fromhex("1acffc1d"),
                                                            dtype=np.uint8)), ref])
    d = np.nonzero(cb[:len(ref_cadu)] != ref_cadu)[0]
    if len(d) == 0:
        print("  -> IDENTICAL")
    else:
        print(f"  -> {len(d)} differing bits, first at {d[0]}")


if __name__ == "__main__":
    main()
