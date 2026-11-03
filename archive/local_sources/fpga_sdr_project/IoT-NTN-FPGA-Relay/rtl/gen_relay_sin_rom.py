#!/usr/bin/env python3
"""Regenerate relay_sin_rom.v (quarter-wave sine LUT, ASCII only).
Usage: python gen_relay_sin_rom.py [output_dir]
"""
import math, os, sys

N = 1024        # points in one quadrant
AMP = 2047      # 12-bit signed full scale

def main():
    dst = sys.argv[1] if len(sys.argv) > 1 else "."
    vals = [int(round(AMP*math.sin((math.pi/2.0)*(k+0.5)/N))) for k in range(N)]
    L = []
    a = L.append
    a("`timescale 1ns / 1ps")
    a("// relay_sin_rom.v -- Quarter-wave sine LUT (AUTO-GENERATED, do not edit)")
    a("module relay_sin_rom (")
    a("    input  wire        clk,")
    a("    input  wire [9:0]  addr_a,")
    a("    input  wire [9:0]  addr_b,")
    a("    output reg  [11:0] data_a,")
    a("    output reg  [11:0] data_b")
    a(");")
    a("    reg [11:0] rom [0:%d];" % (N-1))
    a("    initial begin")
    for k in range(0, N, 4):
        a(("        " + "".join("rom[%4d] = 12'd%4d; " % (k+j, vals[k+j])
                                for j in range(4) if k+j < N)).rstrip())
    a("    end")
    a("    always @(posedge clk) begin")
    a("        data_a <= rom[addr_a];")
    a("        data_b <= rom[addr_b];")
    a("    end")
    a("endmodule")
    out = os.path.join(dst, "relay_sin_rom.v")
    open(out, "w", encoding="ascii").write("\n".join(L)+"\n")
    print("written", out)

if __name__ == "__main__":
    main()
