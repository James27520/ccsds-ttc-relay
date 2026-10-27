#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
typedef uint32_t u32;typedef uint16_t u16;typedef long LONG;
typedef struct {struct {unsigned BaseAddress;} Config;} XEmacPs;
#define Xil_AssertNonvoid(c) assert(c)
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define XST_EMAC_MII_BUSY 2
#define TRUE 1
#define XEMACPS_NWSR_OFFSET 0
#define XEMACPS_PHYMNTNC_OFFSET 1
#define XEMACPS_NWSR_MDIOIDLE_MASK 4
#define XEMACPS_PHYMNTNC_OP_MASK 0
#define XEMACPS_PHYMNTNC_OP_R_MASK 0
#define XEMACPS_PHYMNTNC_OP_W_MASK 0
#define XEMACPS_PHYMNTNC_PHAD_SHFT_MSK 23
#define XEMACPS_PHYMNTNC_PREG_SHFT_MSK 18
static unsigned reads,writes,mode;
static u32 XEmacPs_ReadReg(unsigned base,unsigned reg){(void)base;++reads;assert(reads<=100001);if(reg==1)return 0x1234;if(mode==1)return 0;if(mode==2 && writes)return 0;return 4;}
static void XEmacPs_WriteReg(unsigned base,unsigned reg,u32 value){(void)base;(void)reg;(void)value;++writes;}
#include "mdio_extracted.inc"
int main(void){XEmacPs m={{0}};u16 value=0xffff;
    mode=1;assert(XEmacPs_PhyRead(&m,0,1,&value)==2 && !value && !writes);
    reads=writes=0;mode=2;value=0xffff;assert(XEmacPs_PhyRead(&m,0,1,&value)==1 && !value && reads==100000);
    reads=writes=0;mode=2;assert(XEmacPs_PhyWrite(&m,0,1,0)==1 && reads==100000);
    reads=writes=0;mode=0;assert(XEmacPs_PhyRead(&m,0,1,&value)==0 && value==0x1234);assert(XEmacPs_PhyWrite(&m,0,1,0)==0);
    assert(XEmacPs_PhyRead(&m,0,1,NULL)==1);
    puts("PASS MDIO: busy and stuck read/write bounded at 100000 status reads; cleared failed output; success and NULL output");return 0;}
