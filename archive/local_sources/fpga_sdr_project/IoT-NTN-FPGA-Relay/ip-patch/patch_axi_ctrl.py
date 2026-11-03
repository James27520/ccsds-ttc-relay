#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_axi_ctrl.py -- add the relay control / status registers to the
LDSDR vendor AXI-Lite IP  (xilinx.com:user:axi_ctrl_v1_0).

Run from E:\\LDSDR_010\\repo\\axi_ctrl :
    python patch_axi_ctrl.py

What it does (idempotent, backs up every file it touches to *.bak):

  axi_ctrl_v1_0.v              add 8 user ports + their instantiations
  axi_ctrl_v1_0_S00_AXI.v      add 8 user ports, 3 read-only status decodes,
                               and the register -> port assignments
  component.xml                add the matching IP-XACT port declarations so
                               the new ports show up on the BD symbol

Register map after patching (byte offsets, 32-bit words):

  0x00  idelay_en[6:0]        (existing)  IDELAY enable
  0x04  idelay_tap[4:0]       (existing)  IDELAY tap
  0x08  phase_inc[11:0]       (existing)  DDS phase increment - free once the
                                          DDS no longer drives the DAC
  0x0C  phy_mode[0]           (existing)  1 = 1R1T, 0 = 2R2T
  0x10  relay_mode[1:0]       NEW  0=bypass 1=relay 2=mute 3=duc_only
  0x14  relay_ddc_freq[31:0]  NEW  DDC NCO phase increment
  0x18  relay_duc_freq[31:0]  NEW  DUC NCO phase increment
  0x1C  relay_gain[11:0]      NEW  digital gain, Q1.11 (0x800 = 1.0)
        relay_dc_en[12]       NEW  DC blocker enable
  0x20  status_sample_cnt     NEW  read-only, adc ch1 samples seen
  0x24  status_clip_cnt       NEW  read-only, saturation events
  0x28  status_out_cnt        NEW  read-only, dac_valid pulses issued
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

WRAP = os.path.join(HERE, "axi_ctrl_v1_0.v")
SLAVE = os.path.join(HERE, "axi_ctrl_v1_0_S00_AXI.v")
IPXACT = os.path.join(HERE, "component.xml")

MARKER = "relay_ddc_freq"

#---------------------------------------------------------------------------
# port declarations shared by both Verilog files
#---------------------------------------------------------------------------
PORTS_OUT = [
    ("relay_mode",     "[1:0]",  "out"),
    ("relay_ddc_freq", "[31:0]", "out"),
    ("relay_duc_freq", "[31:0]", "out"),
    ("relay_gain",     "[11:0]", "out"),
    ("relay_dc_en",    None,     "out"),
]
PORTS_IN = [
    ("status_sample_cnt", "[31:0]", "in"),
    ("status_clip_cnt",   "[31:0]", "in"),
    ("status_out_cnt",    "[31:0]", "in"),
]

IPXACT_WIRE = """      <spirit:port>
        <spirit:name>{name}</spirit:name>
        <spirit:wire>
          <spirit:direction>{direction}</spirit:direction>
{vector}          <spirit:wireTypeDefs>
            <spirit:wireTypeDef>
              <spirit:typeName>wire</spirit:typeName>
              <spirit:viewNameRef>xilinx_anylanguagesynthesis</spirit:viewNameRef>
              <spirit:viewNameRef>xilinx_anylanguagebehavioralsimulation</spirit:viewNameRef>
            </spirit:wireTypeDef>
          </spirit:wireTypeDefs>
        </spirit:wire>
      </spirit:port>
"""


def backup(path):
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print("  backup -> %s" % os.path.basename(bak))
    else:
        print("  backup already exists, kept: %s" % os.path.basename(bak))


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def verilog_port_lines(indent):
    lines = []
    for name, width, direction in PORTS_OUT + PORTS_IN:
        if width:
            lines.append("%s%s wire %-7s %s," % (indent, "output" if direction == "out" else "input ",
                                                 width, name))
        else:
            lines.append("%s%s wire %-7s %s," % (indent, "output" if direction == "out" else "input ",
                                                 "", name))
    return "\n".join(lines) + "\n"


def patch_wrapper(text):
    """axi_ctrl_v1_0.v : port list + instantiation"""
    if MARKER in text:
        return text, False

    # ---- 1. port declarations ----
    pat = re.compile(
        r"(?P<indent>[ \t]*)output wire \[11:0\] phase_inc,\r?\n"
        r"(?P=indent)output wire\s+phy_mode,\r?\n")
    m = pat.search(text)
    if not m:
        raise RuntimeError("wrapper: port anchor not found")
    indent = m.group("indent")
    text = text[:m.end()] + verilog_port_lines(indent) + text[m.end():]

    # ---- 2. instantiation connections ----
    pat = re.compile(
        r"(?P<indent>[ \t]*)\.phase_inc\(phase_inc\),\r?\n"
        r"(?P=indent)\.phy_mode\(phy_mode\),\r?\n")
    m = pat.search(text)
    if not m:
        raise RuntimeError("wrapper: instantiation anchor not found")
    indent = m.group("indent")
    conn = "".join("%s.%s(%s),\n" % (indent, n, n)
                   for n, _, _ in PORTS_OUT + PORTS_IN)
    text = text[:m.end()] + conn + text[m.end():]
    return text, True


def patch_slave(text):
    """axi_ctrl_v1_0_S00_AXI.v : ports, read mux, assigns"""
    if MARKER in text:
        return text, False

    # ---- 1. port declarations ----
    pat = re.compile(
        r"(?P<indent>[ \t]*)output wire \[11:0\] phase_inc,\r?\n"
        r"(?P=indent)output wire\s+phy_mode,\r?\n")
    m = pat.search(text)
    if not m:
        raise RuntimeError("slave: port anchor not found")
    indent = m.group("indent")
    text = text[:m.end()] + verilog_port_lines(indent) + text[m.end():]

    # ---- 2. read-only status decodes (0x8 / 0x9 / 0xA -> counters) ----
    pat = re.compile(
        r"(?P<indent>[ \t]*)4'h8\s*:\s*reg_data_out\s*<=\s*slv_reg8;\r?\n"
        r"(?P=indent)4'h9\s*:\s*reg_data_out\s*<=\s*slv_reg9;\r?\n"
        r"(?P=indent)4'hA\s*:\s*reg_data_out\s*<=\s*slv_reg10;\r?\n")
    m = pat.search(text)
    if not m:
        raise RuntimeError("slave: read-mux anchor not found")
    indent = m.group("indent")
    rep = ("%s4'h8   : reg_data_out <= status_sample_cnt;\n"
           "%s4'h9   : reg_data_out <= status_clip_cnt;\n"
           "%s4'hA   : reg_data_out <= status_out_cnt;\n"
           % (indent, indent, indent))
    text = text[:m.start()] + rep + text[m.end():]

    # ---- 3. register -> port assignments ----
    pat = re.compile(
        r"(?P<indent>[ \t]*)assign\s+phase_inc\s*=\s*slv_reg2\[11:0\];\r?\n"
        r"(?P=indent)assign\s+phy_mode\s*=\s*slv_reg3\[0\];\r?\n")
    m = pat.search(text)
    if not m:
        raise RuntimeError("slave: assign anchor not found")
    indent = m.group("indent")
    rep = (
        "%sassign  relay_mode     = slv_reg4[1:0];\n"
        "%sassign  relay_ddc_freq = slv_reg5;\n"
        "%sassign  relay_duc_freq = slv_reg6;\n"
        "%sassign  relay_gain     = slv_reg7[11:0];\n"
        "%sassign  relay_dc_en    = slv_reg7[12];\n"
        % (indent, indent, indent, indent, indent))
    text = text[:m.end()] + rep + text[m.end():]
    return text, True


def patch_ipxact(text):
    """component.xml : declare the new ports so they appear on the BD symbol"""
    if MARKER in text:
        return text, False

    def block(name, width, direction):
        if width:
            lo, hi = width.strip("[]").split(":")
            vec = ("          <spirit:vector>\n"
                   "            <spirit:left spirit:format=\"long\">%s</spirit:left>\n"
                   "            <spirit:right spirit:format=\"long\">%s</spirit:right>\n"
                   "          </spirit:vector>\n" % (lo, hi))
        else:
            vec = ""
        return IPXACT_WIRE.format(name=name, direction=direction, vector=vec)

    anchor = re.search(r"[ \t]*<spirit:port>\s*\r?\n[ \t]*<spirit:name>s00_axi_aclk</spirit:name>",
                       text)
    if not anchor:
        raise RuntimeError("component.xml: s00_axi_aclk port anchor not found")

    ins = "".join(block(n, w, d) for n, w, d in PORTS_OUT + PORTS_IN)
    text = text[:anchor.start()] + ins + text[anchor.start():]
    return text, True


def main():
    ok = True
    for path, fn, label in ((WRAP, patch_wrapper, "axi_ctrl_v1_0.v"),
                            (SLAVE, patch_slave, "axi_ctrl_v1_0_S00_AXI.v"),
                            (IPXACT, patch_ipxact, "component.xml")):
        if not os.path.exists(path):
            print("!! missing: %s" % path)
            ok = False
            continue
        print("[%s]" % label)
        text = read(path)
        try:
            new, changed = fn(text)
        except RuntimeError as exc:
            print("  !! %s" % exc)
            ok = False
            continue
        if not changed:
            print("  already patched, skipped")
            continue
        backup(path)
        write(path, new)
        if MARKER not in read(path):
            print("  !! verification failed")
            ok = False
            continue
        print("  patched OK")

    print()
    if ok:
        print("ALL PATCHED.")
        print("Next, in Vivado Tcl console (see modify_bd.tcl):")
        print("  update_ip_catalog -rebuild")
        print("  reset_target all [get_ips design_1_axi_ctrl_v1_0_0_1]")
        print("  generate_target all [get_ips design_1_axi_ctrl_v1_0_0_1]")
    else:
        print("SOME STEPS FAILED - files were backed up as *.bak, restore if needed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
