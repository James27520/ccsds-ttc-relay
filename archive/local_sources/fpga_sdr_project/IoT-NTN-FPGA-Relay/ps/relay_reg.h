/******************************************************************************
 * relay_reg.h -- register map of the PL bent-pipe relay data path
 *
 * Target : LDSDR (Zynq XC7Z010 + AD9361), bare-metal (no-OS) application
 * Added  : relay_dq.v in design_1, behind the vendor axi_ctrl_v1_0 IP
 *
 * The PL now relays ADC -> (DDC -> DC block -> DUC -> gain) -> DAC entirely in
 * fabric.  The PS only writes a few control words at start-up and may read the
 * diagnostic counters; it never touches the sample stream.
 *
 * Register map (byte offsets from the axi_ctrl base address):
 *
 *   0x00  IDELAY_EN      R/W  7   (vendor) IDELAY enable
 *   0x04  IDELAY_TAP     R/W  5   (vendor) IDELAY tap
 *   0x08  DDS_PHASE_INC  R/W 12   (vendor) DDS phase increment - unused now
 *   0x0C  PHY_MODE       R/W  1   (vendor) 1 = 1R1T, 0 = 2R2T
 *   0x10  RELAY_MODE     R/W  2   0=bypass 1=relay 2=mute 3=duc_only
 *   0x14  RELAY_DDC_FREQ R/W 32   DDC NCO phase increment
 *   0x18  RELAY_DUC_FREQ R/W 32   DUC NCO phase increment
 *   0x1C  RELAY_GAIN     R/W 12   digital gain, Q1.11 (0x800 = 1.0)
 *         RELAY_DC_EN    R/W  1   bit 12 : DC blocker enable (relay mode only)
 *   0x20  ST_SAMPLE_CNT  RO  32   channel-1 samples received
 *   0x24  ST_CLIP_CNT    RO  32   saturation events
 *   0x28  ST_OUT_CNT     RO  32   dac_valid pulses issued
 *
 * Frequency word
 * --------------
 *   freq_word = round( f_offset / fs * 2^32 )        (unsigned 32-bit)
 *   net translation of the relay = (DUC_FREQ - DDC_FREQ) / 2^32 * fs
 *
 *   fs = 30.72 MHz examples:
 *     +10 kHz -> 0x000D1B71     +100 kHz -> 0x00D55555    +480 kHz -> 0x04000000
 *     -10 kHz -> 0xFFF2E48F     -100 kHz -> 0xFF2AAAAB    -480 kHz -> 0xFC000000
 *
 * IMPORTANT before using this
 * ---------------------------
 *  1) AD9361 BIST must be OFF, otherwise the internal tone generator replaces
 *     the DAC data and the relay output never reaches the antenna:
 *     comment out the three ad9361_spi_write(..., 0x3f4/0x3f5/0x3f6, ...) lines.
 *  2) ad9361_set_tx_attenuation() takes MILLI-decibels.  The vendor code passes
 *     70 (= 0.07 dB, almost full power).  Measure the TX output before
 *     connecting anything to it.
 *****************************************************************************/
#ifndef RELAY_REG_H_
#define RELAY_REG_H_

#include "xil_io.h"
#include "xparameters.h"

/*---------------------------------------------------------------------------
 * base address (same window the vendor IP already used)
 *-------------------------------------------------------------------------*/
#ifndef XPAR_AXI_CTRL_0_BASEADDR
#error "XPAR_AXI_CTRL_0_BASEADDR is not defined - check xparameters.h"
#endif

#define RELAY_BASE        XPAR_AXI_CTRL_0_BASEADDR

#define R_IDELAY_EN       (RELAY_BASE + 0x00)
#define R_IDELAY_TAP      (RELAY_BASE + 0x04)
#define R_DDS_PHASE_INC   (RELAY_BASE + 0x08)
#define R_PHY_MODE        (RELAY_BASE + 0x0C)

#define R_RELAY_MODE      (RELAY_BASE + 0x10)
#define R_RELAY_DDC_FREQ  (RELAY_BASE + 0x14)
#define R_RELAY_DUC_FREQ  (RELAY_BASE + 0x18)
#define R_RELAY_GAIN      (RELAY_BASE + 0x1C)

#define R_ST_SAMPLE_CNT   (RELAY_BASE + 0x20)
#define R_ST_CLIP_CNT     (RELAY_BASE + 0x24)
#define R_ST_OUT_CNT      (RELAY_BASE + 0x28)

/*---------------------------------------------------------------------------
 * relay_mode values
 *-------------------------------------------------------------------------*/
#define RELAY_MODE_BYPASS   0u   /* DAC <- ADC, raw                       */
#define RELAY_MODE_RELAY    1u   /* DDC -> DC block -> DUC -> gain        */
#define RELAY_MODE_MUTE     2u   /* DAC <- 0 (safe state)                 */
#define RELAY_MODE_DUC_ONLY 3u   /* DUC -> gain (pure frequency shift)    */

/*---------------------------------------------------------------------------
 * helpers
 * (marked unused so that including this header does not produce
 *  -Wunused-function warnings for the helpers an application does not call)
 *-------------------------------------------------------------------------*/
#define RELAY_UNUSED __attribute__((unused))
#define RELAY_GAIN_UNITY    0x800u    /* Q1.11, 1.0 */
#define RELAY_GAIN_HALF     0x400u
#define RELAY_GAIN_2X       0xFFFu    /* ~2.0, clips unless input is small */

static void RELAY_UNUSED relay_set_mode(u32 mode)
{
    Xil_Out32(R_RELAY_MODE, mode & 0x3u);
}

/* fs_hz = current AD9361 sampling frequency (e.g. 30720000)
 *
 * NOTE: the rounding is done through a *signed* intermediate.  Casting a
 * negative double straight to an unsigned type is undefined behaviour; on
 * ARM GCC it saturates to 0, which silently kills every negative frequency
 * offset (the word comes back as 0x00000000). */
static u32 RELAY_UNUSED relay_freq_word(s32 offset_hz, u32 fs_hz)
{
    double    w = ((double)offset_hz * 4294967296.0) / (double)fs_hz;
    long long v = (long long)(w + (w >= 0.0 ? 0.5 : -0.5));
    return (u32)((unsigned long long)v & 0xFFFFFFFFULL);
}

static void RELAY_UNUSED relay_set_ddc_freq(u32 word) { Xil_Out32(R_RELAY_DDC_FREQ, word); }
static void RELAY_UNUSED relay_set_duc_freq(u32 word) { Xil_Out32(R_RELAY_DUC_FREQ, word); }

static void RELAY_UNUSED relay_set_gain(u32 q11, u32 dc_en)
{
    Xil_Out32(R_RELAY_GAIN, (q11 & 0xFFFu) | ((dc_en & 0x1u) << 12));
}

static u32 RELAY_UNUSED relay_get_sample_cnt(void) { return Xil_In32(R_ST_SAMPLE_CNT); }
static u32 RELAY_UNUSED relay_get_clip_cnt  (void) { return Xil_In32(R_ST_CLIP_CNT);   }
static u32 RELAY_UNUSED relay_get_out_cnt   (void) { return Xil_In32(R_ST_OUT_CNT);    }

/*---------------------------------------------------------------------------
 * start-up sequence
 *   fs_hz : AD9361 sampling frequency actually in use
 *   ddc_hz, duc_hz : desired DDC / DUC offsets (net shift = duc - ddc)
 *-------------------------------------------------------------------------*/
static void RELAY_UNUSED relay_startup(u32 fs_hz, s32 ddc_hz, s32 duc_hz, u32 gain_q11)
{
    /* 1. mute while configuring */
    relay_set_mode(RELAY_MODE_MUTE);

    /* 2. frequency plan, gain, DC blocker off */
    relay_set_ddc_freq(relay_freq_word(ddc_hz, fs_hz));
    relay_set_duc_freq(relay_freq_word(duc_hz, fs_hz));
    relay_set_gain(gain_q11, 0u);

    /* 3. go */
    relay_set_mode(RELAY_MODE_RELAY);
}

/*---------------------------------------------------------------------------
 * health check: returns 0 on success
 *   the PL pipeline is 6 clocks deep, so out_cnt tracks sample_cnt with a
 *   constant offset; both must advance between two calls.
 *-------------------------------------------------------------------------*/
static int RELAY_UNUSED relay_health_check(u32 *sample_cnt, u32 *out_cnt, u32 *clip_cnt)
{
    u32 s1, o1, s2, o2;
    s1 = relay_get_sample_cnt();
    o1 = relay_get_out_cnt();
    /* the snapshot register updates every 4096 samples, so give it time */
    {
        volatile int i;
        for (i = 0; i < 200000; i++) { }
    }
    s2 = relay_get_sample_cnt();
    o2 = relay_get_out_cnt();

    if (sample_cnt) *sample_cnt = s2;
    if (out_cnt)    *out_cnt    = o2;
    if (clip_cnt)   *clip_cnt   = relay_get_clip_cnt();

    if (s2 == s1) return -1;      /* no ADC data at all  */
    if (o2 == o1) return -2;      /* ADC runs but no DAC output */
    return 0;
}

#endif /* RELAY_REG_H_ */
