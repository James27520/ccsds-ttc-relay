/* Native offline execution of the exact IQ transaction; no hardware APIs. */
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>

struct spi_device { int unused; } spi;
struct pdata { struct { unsigned char pp_conf[3]; } port_ctrl; } pdata;
struct phy { struct spi_device *spi; struct pdata *pdata; } phy = {&spi, &pdata};
static struct phy *ad9361_phy = &phy;
static int probe_ready = 1;
static volatile uint32_t relay_spi_error_count;
#define R_RELAY_MODE 0x10
#define RELAY_MODE_MUTE 2
#define REG_PARALLEL_PORT_CONF_1 0x10
#define PP_TX_SWAP_IQ 0x80
#define PP_RX_SWAP_IQ 0x40
static unsigned mode, reg010, writes, reads;
static unsigned atten[2];
static int atten_error, silent_atten_error, read_error_at, mismatch_at, fail_write_at, fail_rollback;

static unsigned Xil_In32(unsigned address) { assert(address==R_RELAY_MODE); return mode; }
static void relay_set_mode(unsigned v) { mode=v; }
static int probe_read_atten(unsigned ch,uint32_t *v) {
    assert(ch<2); *v=atten[ch];
    if (atten_error || silent_atten_error) ++relay_spi_error_count;
    return atten_error ? -EIO : 0;
}
static int ad9361_spi_read(struct spi_device *s,unsigned r) {
    assert(s==&spi && r==0x10); ++reads;
    if ((int)reads==read_error_at) { ++relay_spi_error_count; return -EIO; }
    return ((int)reads==mismatch_at) ? (int)(reg010^1) : (int)reg010;
}
static int ad9361_spi_write(struct spi_device *s,unsigned r,unsigned v) {
    assert(s==&spi && r==0x10 && v<=255); ++writes;
    if (fail_rollback && writes==2) { ++relay_spi_error_count; return -EIO; }
    reg010=v; /* transfer may reach the chip before returning failure */
    if ((int)writes==fail_write_at) { ++relay_spi_error_count; return -EIO; }
    return 0;
}
#include "relay_iqswap.h"

static void reset(void) {
    ad9361_phy=&phy;probe_ready=1;mode=2;reg010=0xc8;
    pdata.port_ctrl.pp_conf[0]=0xc8;
    relay_spi_error_count=0;writes=reads=0;
    atten[0]=atten[1]=89000;
    atten_error=silent_atten_error=read_error_at=mismatch_at=fail_write_at=fail_rollback=0;
}
int main(void) {
    reset();assert(diag_iqswap(0,0)==0);assert(reg010==0x88);
    assert(pdata.port_ctrl.pp_conf[0]==0x88 && mode==2); /* RX only, TX untouched */
    assert(diag_iqswap(0,1)==0);assert(reg010==0xc8);
    assert(diag_iqswap(1,0)==0);assert(reg010==0x48);
    assert(pdata.port_ctrl.pp_conf[0]==0x48); /* TX only, RX untouched */
    assert(diag_iqswap(1,1)==0);assert(reg010==0xc8);
    puts("PASS: both sides and both values preserve all other register/cache bits");

    reset();mode=1;assert(diag_iqswap(0,0)<0 && writes==0 && mode==2);
    reset();atten[0]=29999;assert(diag_iqswap(0,0)<0 && writes==0 && mode==2);
    reset();atten[1]=29999;assert(diag_iqswap(1,0)<0 && writes==0 && mode==2);
    reset();atten[0]=atten[1]=30000;assert(diag_iqswap(0,0)==0);
    puts("PASS: mode gate, both actual attenuation gates, exact 30000mdB boundary");

    reset();atten_error=1;assert(diag_iqswap(0,0)<0 && writes==0);
    reset();silent_atten_error=1;assert(diag_iqswap(0,0)<0 && writes==0);
    reset();read_error_at=1;assert(diag_iqswap(0,0)<0 && writes==0);
    puts("PASS: explicit and counter-only SPI errors reject before any register write");

    reset();mismatch_at=2;assert(diag_iqswap(0,0)<0);
    assert(writes==2 && reg010==0xc8 && pdata.port_ctrl.pp_conf[0]==0xc8 && mode==2);
    reset();fail_write_at=1;assert(diag_iqswap(1,0)<0);
    assert(writes==2 && reg010==0xc8 && pdata.port_ctrl.pp_conf[0]==0xc8 && mode==2);
    reset();read_error_at=2;assert(diag_iqswap(0,0)<0);
    assert(writes==2 && reg010==0xc8 && mode==2);
    puts("PASS: exact-byte readback mismatch, partial write error, read failure all roll back");

    reset();mismatch_at=2;fail_rollback=1;assert(diag_iqswap(0,0)<0);
    assert(mode==2 && pdata.port_ctrl.pp_conf[0]==0xc8);
    reset();probe_ready=0;assert(diag_iqswap(0,0)<0 && writes==0 && mode==2);
    reset();ad9361_phy=0;assert(diag_iqswap(0,0)<0 && writes==0 && mode==2);
    reset();assert(diag_iqswap(2,0)<0 && writes==0);
    reset();assert(diag_iqswap(0,2)<0 && writes==0);
    puts("PASS: rollback failure, unavailable initialization and invalid arguments stay muted");
    reset();reg010=pdata.port_ctrl.pp_conf[0]=0x88;
    assert(diag_iqswap(0,1)==0 && reg010==0xc8);
    assert(diag_iqswap(0,0)==0 && reg010==0x88);
    assert(pdata.port_ctrl.pp_conf[0]==0x88 && (reg010 & PP_TX_SWAP_IQ));
    puts("PASS: corrected RX0/TX1 default remains reversibly diagnosable without altering TX bit");
    return 0;
}
