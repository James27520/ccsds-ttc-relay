#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_main_c.py -- make the LDSDR bare-metal app drive the PL relay.

Run from E:\\LDSDR_010\\zynq_dev_fmcomms3.sdk\\9361\\src :
    python patch_main_c.py

Idempotent; the original is kept as main.c.bak.

Changes
-------
1. #include "relay_reg.h"
2. test frequency plan moved into a clearly marked #define block
     RX_LO = 900 MHz, TX_LO = 1000 MHz, fs = 30.72 MSPS
   (these match the relay configuration that already worked over USB;
    change the three #defines to move the link)
3. TX attenuation 70 mdB (~0.07 dB, i.e. almost full power) -> 30 dB.
   The driver documents attenuation_mdb as milli-decibels
   ("Example: 10000 (10 dB)"), so the original value was almost certainly
   a decimal-point slip.  30 dB is a safe first-power-up value; lower it
   once the actual output level has been measured.
4. AD9361 BIST commented out.  0x3F4 = 0x03 means BIST enable + TX
   injection point + tone mode, which makes the chip generate its own
   digital tone INSTEAD of using the DAC data coming from the PL.  With
   BIST on, the relay output can never reach the antenna.
5. while(1) replaced with the relay bring-up sequence + health check.
"""
import io
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(HERE, "main.c")
ENC = "gb18030"          # the file carries Chinese comments in GB18030

MARK = "relay_reg.h"


def main():
    if not os.path.exists(MAIN):
        print("!! main.c not found at", MAIN)
        return 1

    src = io.open(MAIN, encoding=ENC, errors="replace").read()

    if MARK in src:
        print("main.c is already patched, nothing to do")
        return 0

    orig = src

    #-------------------------------------------------------------------
    # 1. include
    #-------------------------------------------------------------------
    anchor = '#include "xil_io.h"'
    if anchor not in src:
        print("!! include anchor not found")
        return 1
    src = src.replace(anchor, anchor + '\n#include "relay_reg.h"', 1)

    #-------------------------------------------------------------------
    # 2. frequency plan + 3. TX attenuation
    #-------------------------------------------------------------------
    pat = re.compile(
        r"uint32_t sample_rate\s*=\s*[^;]+;\s*\n"
        r"uint64_t tx_lo_freq\s*=\s*[^;]+;\s*\n"
        r"uint64_t rx_lo_freq\s*=\s*[^;]+;\s*\n"
        r"uint32_t bandwidth\s*=\s*[^;]+;\s*\n"
        r"int32_t gain\s*=\s*[^;]+;\s*\n"
        r"uint32_t txatt\s*=\s*[^;]+;")
    m = pat.search(src)
    if not m:
        print("!! parameter block anchor not found")
        return 1
    newblock = """/* ================= TEST FREQUENCY PLAN (edit here) =================
 * RX_LO / TX_LO are the AD9361 local oscillator frequencies.
 * The digital DDC/DUC inside the PL then provides fine offset and
 * Doppler/frequency-offset correction on top of them.
 * These values match the link that already worked over USB.
 * =================================================================== */
uint32_t sample_rate = 30720000;      /* 30.72 MSPS                        */
uint64_t tx_lo_freq  = 1000000000ULL; /* TX LO 1000 MHz                    */
uint64_t rx_lo_freq  =  900000000ULL; /* RX LO  900 MHz                    */
uint32_t bandwidth   = 18000000;      /* RF bandwidth 18 MHz               */
int32_t  gain        = 0;             /* RX gain index (MGC)               */
/* TX attenuation in MILLI-dB.  30000 = 30 dB.
 * The vendor example was 70 (= 0.07 dB, essentially full power) - that is
 * almost certainly a decimal-point slip.  Measure the TX output before
 * lowering this. */
uint32_t txatt       = 30000;"""
    src = src[:m.start()] + newblock + src[m.end():]

    #-------------------------------------------------------------------
    # 4. BIST off  +  5. relay bring-up
    #-------------------------------------------------------------------
    pat = re.compile(
        r"[ \t]*//bist test mode.*?\n"
        r".*?ad9361_spi_write\(ad9361_phy->spi,\s*0x3f4,.*?\n"
        r".*?ad9361_spi_write\(ad9361_phy->spi,\s*0x3f5,.*?\n"
        r".*?ad9361_spi_write\(ad9361_phy->spi,\s*0x3f6,.*?\n"
        r"[ \t]*printf\(\"initial done\.\\n\\r\"\);\s*\n"
        r"[ \t]*while\(1\);",
        re.S)
    m = pat.search(src)
    if not m:
        print("!! BIST / while(1) block anchor not found")
        return 1

    newtail = """	/* ================= BIST MUST STAY OFF =================
	 * The original code enabled the AD9361 internal BIST:
	 *     ad9361_spi_write(ad9361_phy->spi, 0x3f4, 0x03);//tx tone
	 *     ad9361_spi_write(ad9361_phy->spi, 0x3f5, 0x01);//no rf loop
	 *     ad9361_spi_write(ad9361_phy->spi, 0x3f6, 0x00);
	 * 0x3F4 = REG_BIST_CONFIG: bit0 = BIST_ENABLE, bit[3:2] =
	 * BIST_CTRL_POINT.  0x03 therefore means "BIST on, inject at TX,
	 * tone mode" - the chip then generates its own digital tone and
	 * REPLACES the DAC data coming from the PL, so the relayed signal
	 * never reaches the antenna.  Left commented out on purpose.
	 * ====================================================== */

	/* ---- PL relay bring-up ---------------------------------------- */
	relay_set_mode(RELAY_MODE_MUTE);      /* safe state while configuring */
	relay_set_ddc_freq(0);                /* no down-conversion offset     */
	relay_set_duc_freq(0);                /* no up-conversion offset       */
	relay_set_gain(RELAY_GAIN_UNITY, 0);  /* unity gain, DC blocker off    */
	relay_set_mode(RELAY_MODE_RELAY);     /* ADC -> DDC -> DUC -> DAC      */

	printf("\\r\\n===== PL relay enabled =====\\r\\n");
	printf("  RX_LO       = %u Hz\\r\\n", (unsigned int)rx_lo_freq);
	printf("  TX_LO       = %u Hz\\r\\n", (unsigned int)tx_lo_freq);
	printf("  sample_rate = %u Hz\\r\\n", (unsigned int)sample_rate);
	printf("  TX atten    = %u mdB (%u dB)\\r\\n",
	       (unsigned int)txatt, (unsigned int)(txatt / 1000));
	printf("  relay mode  = RELAY, DDC=0, DUC=0, gain=1.0\\r\\n");

	/* ---- health check --------------------------------------------- */
	{
		u32 n_in = 0, n_out = 0, n_clip = 0;
		int rc = relay_health_check(&n_in, &n_out, &n_clip);
		printf("  status      : in=%u out=%u clip=%u rc=%d\\r\\n",
		       (unsigned int)n_in, (unsigned int)n_out,
		       (unsigned int)n_clip, rc);
		if (rc != 0) {
			relay_set_mode(RELAY_MODE_MUTE);
			printf("  !! no data flowing through the PL relay - MUTED\\r\\n");
		} else {
			printf("  relay OK\\r\\n");
		}
	}
	printf("============================\\r\\n");

	/* To demonstrate the digital frequency translation, replace the
	 * relay_set_duc_freq(0) call above with e.g.
	 *     relay_set_duc_freq(relay_freq_word(100000, sample_rate));
	 * for a +100 kHz offset.
	 */

	while (1) {
		/* the PL relays on its own; the CPU is idle here on purpose */
	}"""
    src = src[:m.start()] + newtail + src[m.end():]

    if src == orig:
        print("!! nothing changed - anchors matched but produced no edit")
        return 1

    #-------------------------------------------------------------------
    # write
    #-------------------------------------------------------------------
    bak = MAIN + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(MAIN, bak)
        print("backup ->", os.path.basename(bak))
    io.open(MAIN, "w", encoding=ENC, newline="\n").write(src)
    print("patched:", MAIN)

    # quick verification
    chk = io.open(MAIN, encoding=ENC, errors="replace").read()
    tests = [("relay_reg.h include", '#include "relay_reg.h"' in chk),
             ("BIST commented", chk.count("0x3f4, 0x03") == 0),
             ("relay bring-up", "relay_set_mode(RELAY_MODE_RELAY)" in chk),
             ("health check", "relay_health_check" in chk),
             ("no bare while(1)", not re.search(r"while\s*\(\s*1\s*\)\s*;", chk))]
    ok = True
    for name, res in tests:
        print("   %-22s %s" % (name, "OK" if res else "FAIL"))
        ok = ok and res

    # what values did we end up with
    for pat, label in ((r"sample_rate\s*=\s*(\d+)", "sample_rate"),
                       (r"tx_lo_freq\s*=\s*(\d+)", "tx_lo_freq"),
                       (r"rx_lo_freq\s*=\s*(\d+)", "rx_lo_freq"),
                       (r"txatt\s*=\s*(\d+)", "txatt (mdB)")):
        mm = re.search(pat, chk)
        print("   %-22s %s" % (label, mm.group(1) if mm else "?"))

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
