#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t UINTPTR;typedef unsigned u32;typedef int s32_t;typedef int err_t;
typedef struct {unsigned BaseAddress;} XEmacPs_Config;
typedef struct {XEmacPs_Config Config;} XEmacPs;
typedef struct {XEmacPs emacps;void *send_q,*recv_q;} xemacpsif_s;
struct xemac_s {void *state;int topology_index,type;};
struct netif {void *state;unsigned mtu,flags;char name[2];void *output,*linkoutput;};
#define NO_SYS 1
#define XST_SUCCESS 0
#define ERR_OK 0
#define ERR_IF -1
#define ERR_MEM -2
#define LWIP_DEBUGF(a,b) ((void)0)
#define xil_printf(...) ((void)0)
#define XEMACPS_MTU 1500
#define XEMACPS_HDR_SIZE 14
#define NETIF_FLAG_BROADCAST 1
#define NETIF_FLAG_ETHARP 2
#define NETIF_FLAG_LINK_UP 4
#define XEMACPS_DMACR_OFFSET 0
#define xemac_type_emacps 3
#define IFNAME0 't'
#define IFNAME1 'e'
#define xemacpsif_output NULL
#define low_level_output NULL
static struct netif *NetIf;static XEmacPs_Config *mac_config,config={0};
static int allocations,alloc_calls,alloc_fail,cfg_fail,phy_fail,dma_fail,queue_fail,queues,starts,cleanups,no_config;
static void *mem_malloc(size_t n){++alloc_calls;if(alloc_calls==alloc_fail)return NULL;++allocations;return malloc(n);}
static void mem_free(void *p){assert(p);--allocations;free(p);}
static int xtopology_find_index(unsigned base){(void)base;return 0;}
static XEmacPs_Config *xemacps_lookup_config(unsigned base){(void)base;return no_config?NULL:&config;}
static int XEmacPs_CfgInitialize(XEmacPs *m,XEmacPs_Config *c,unsigned b){(void)b;m->Config=*c;return cfg_fail;}
static int init_emacps(xemacpsif_s *m,struct netif *n){(void)m;(void)n;return phy_fail;}
static void XEmacPs_Stop(XEmacPs *m){(void)m;}
static unsigned XEmacPs_ReadReg(unsigned a,unsigned r){(void)a;(void)r;return 0;}
static void XEmacPs_WriteReg(unsigned a,unsigned r,unsigned v){(void)a;(void)r;(void)v;}
static void setup_isr(struct xemac_s *m){(void)m;}
static int init_dma(struct xemac_s *m){(void)m;return dma_fail;}
static void free_txrx_pbufs(xemacpsif_s *m){(void)m;++cleanups;}
static void *pq_create_queue(void){if(queue_fail)return NULL;++queues;return &queues;}
static void start_emacps(xemacpsif_s *m){(void)m;++starts;}
static void netif_set_link_up(struct netif *n){n->flags|=NETIF_FLAG_LINK_UP;}
#include "init_extracted.inc"
static void attempt(int expected) {struct netif n;memset(&n,0,sizeof n);assert(xemacpsif_init(&n)==expected);assert(!allocations && !NetIf && !(n.flags&NETIF_FLAG_LINK_UP) && !starts);}
int main(void) {
    struct netif n;struct xemac_s *m;int i;
    alloc_fail=1;attempt(ERR_MEM);alloc_fail=3;attempt(ERR_MEM);alloc_fail=0;
    no_config=1;attempt(ERR_IF);no_config=0;
    cfg_fail=1;attempt(ERR_IF);cfg_fail=0;
    phy_fail=1;for(i=0;i<64;++i)attempt(ERR_IF);assert(!queues);phy_fail=0;
    dma_fail=1;for(i=0;i<64;++i)attempt(ERR_IF);assert(!queues && cleanups==64);dma_fail=0;
    queue_fail=1;attempt(ERR_MEM);assert(cleanups==65);queue_fail=0;
    memset(&n,0,sizeof n);assert(xemacpsif_init(&n)==0);assert(queues==1 && starts==1 && allocations==2 && (n.flags&NETIF_FLAG_LINK_UP));
    m=n.state;mem_free(m->state);mem_free(m);
    puts("PASS init: OOM/config failures; 64 PHY failures + 64 DMA failures without queue consumption/leaks; queue failure cleanup; later success");return 0;
}
