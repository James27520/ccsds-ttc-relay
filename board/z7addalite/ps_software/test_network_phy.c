#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "xemac_ieee_reg.h"
typedef uint16_t u16_t; typedef uint32_t u32_t; typedef uint32_t u32;
typedef struct { struct {u32_t BaseAddress;} Config; u32_t IsReady;} XEmacPs;
typedef struct {XEmacPs emacps;} xemacpsif_s;
struct xemac_s {void *state;}; struct netif {void *state;int link;};
#define XLWIP_CONFIG_INCLUDE_GEM 1
#define XPAR_XEMACPS_0_BASEADDR 0
#define XIL_COMPONENT_IS_READY 1
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define FALSE 0
#define TRUE 1
#define xil_printf(...) ((void)printf(__VA_ARGS__))
#define XEMACPS_NWCFG_OFFSET 4
#define XEMACPS_NWCTRL_OFFSET 0
#define XEMACPS_NWSR_OFFSET 8
static u32_t XEmacPs_ReadReg(u32_t base,u32_t offset){(void)base;(void)offset;return 0;}
enum ethernet_link_status {ETH_LINK_UNDEFINED,ETH_LINK_UP,ETH_LINK_DOWN,ETH_LINK_NEGOTIATING};
static enum ethernet_link_status eth_link_status;
static u32_t phymapemac0[32],phymapemac1[32],phyaddrforemac;
static unsigned reads,writes,fail_at,write_fail_at,wait_us,stuck_reset,bmsr_reads,drop_after,clock_changes;
static uint16_t regs[32][32];
static int XEmacPs_PhyRead(XEmacPs *m,u32_t a,u32_t r,u16_t *v) {
    (void)m; ++reads;if(fail_at && reads==fail_at){*v=0xffff;return 1;}
    *v=regs[a][r];if(r==0 && !stuck_reset)*v&=~0x8000u;
    if(r==1 && drop_after && ++bmsr_reads>=drop_after)*v=0;
    return 0;
}
static int XEmacPs_PhyWrite(XEmacPs *m,u32_t a,u32_t r,u16_t v) {
    (void)m;assert(a==1);++writes;if(write_fail_at && writes==write_fail_at)return 1;
    regs[a][r]=v;return 0;
}
static void usleep(unsigned us){wait_us+=us;assert(wait_us<=6000000u);}
static void SetUpSLCRDivisors(u32_t a,int speed){(void)a;assert(speed==10 || speed==100 || speed==1000);++clock_changes;}
static void XEmacPs_SetOperatingSpeed(XEmacPs *m,u32_t speed){(void)m;assert(speed==10 || speed==100 || speed==1000);}
static void netif_set_link_down(struct netif *n){n->link=0;}
static void netif_set_link_up(struct netif *n){n->link=1;}
#include "phy_extracted.inc"
static void reset(void) {
    memset(regs,255,sizeof regs);reads=writes=fail_at=write_fail_at=wait_us=stuck_reset=bmsr_reads=drop_after=clock_changes=0;
    memset(regs[0],0,sizeof regs[0]);regs[0][2]=0x001c;regs[0][3]=0xc915;regs[0][1]=0x24;regs[0][17]=0x8400;memcpy(regs[1],regs[0],sizeof regs[0]);
}
int main(void) {
    XEmacPs mac={{0},1};xemacpsif_s iface={{{0},1}};struct xemac_s emac={&iface};struct netif net={&emac,1};unsigned i,j;
    reset();detect_phy(&mac);assert(!phymapemac0[0] && phymapemac0[1]);
    assert(get_IEEE_phy_speed(&mac,1)==1000 && writes==4);
    reset();memset(regs[0],255,sizeof regs[0]);detect_phy(&mac);assert(phymapemac0[1]);
    reset();memset(regs[1],255,sizeof regs[1]);detect_phy(&mac);assert(!phymapemac0[0] && !phymapemac0[1]);
    reset();regs[1][2]=0x141;detect_phy(&mac);assert(!phymapemac0[1]);
    reset();regs[1][3]=0xc916;detect_phy(&mac);assert(!phymapemac0[1]);
    reset();regs[0][3]=0xc916;detect_phy(&mac);assert(!phymapemac0[1]);
    reset();regs[1][3]=0xc916;assert(get_IEEE_phy_speed(&mac,1)==1 && !writes);assert(phy_current_speed_emacps(&mac,1)==1);
    reset();memcpy(regs[2],regs[1],sizeof regs[1]);detect_phy(&mac);assert(!phymapemac0[1]);
    reset();regs[2][2]=0x141;regs[2][3]=0x1234;detect_phy(&mac);assert(!phymapemac0[1]);
    reset();memset(regs,255,sizeof regs);detect_phy(&mac);for(i=0;i<32;++i)assert(!phymapemac0[i]);
    for(i=1;i<=64;++i){reset();fail_at=i;detect_phy(&mac);for(j=0;j<32;++j)assert(!phymapemac0[j]);}
    reset();detect_phy(&mac);assert(phymapemac0[1]);
    for(i=1;i<=14;++i){reset();fail_at=i;assert(get_IEEE_phy_speed(&mac,1)==1);}
    for(i=1;i<=4;++i){reset();write_fail_at=i;assert(get_IEEE_phy_speed(&mac,1)==1);}
    reset();stuck_reset=1;assert(get_IEEE_phy_speed(&mac,1)==1 && wait_us==1000000);
    reset();regs[1][1]=0;assert(get_IEEE_phy_speed(&mac,1)==1 && wait_us==5000000);
    reset();regs[1][1]=0xffff;assert(get_IEEE_phy_speed(&mac,1)==1);
    reset();regs[1][17]=0xc400;assert(get_IEEE_phy_speed(&mac,1)==1);
    reset();drop_after=3;assert(get_IEEE_phy_speed(&mac,1)==1);
    for(i=0;i<3;++i){reset();regs[1][17]=(uint16_t)(0x400u+i*0x4000u);assert(get_IEEE_phy_speed(&mac,1)==(i==0?10u:i==1?100u:1000u));}
    reset();eth_link_status=ETH_LINK_UP;phyaddrforemac=1;fail_at=1;eth_link_detect(&net);assert(!net.link && !wait_us && !writes);
    reset();eth_link_status=ETH_LINK_NEGOTIATING;fail_at=5;eth_link_detect(&net);assert(!net.link && !clock_changes && !wait_us && !writes);
    reset();eth_link_detect(&net);assert(net.link && eth_link_status==ETH_LINK_UP && !wait_us && !writes);
    puts("PASS RTL8211E addr1 policy (every setup write asserted addr1): 0+1 and only1 accepted; only0/C916/unknown/extra nonzero rejected; all64 scan MDIO faults rejected; retry; 18 setup MDIO faults; bounded timeouts; 10/100/1000; nonblocking reconnect");
    return 0;
}
