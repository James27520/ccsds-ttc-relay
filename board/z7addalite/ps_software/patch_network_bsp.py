"""Apply reviewed ADDA/RTL8211E recovery fixes to a NEW generated BSP copy.
Original vendor/generated BSP and previously linked ELF remain unchanged.
"""
import argparse,difflib,hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args();source=a.source.resolve();out=a.out.resolve()
if out.exists():raise SystemExit('Refuse overwrite; choose a new output')
opts=(source/'ps7_cortexa9_0/libsrc/lwip202_v1_2/src/contrib/ports/xilinx/include/lwipopts.h').read_text()
for macro in ['NO_SYS','CONFIG_LINKSPEED_AUTODETECT']:
    if not re.search(r'^#define\s+'+macro+r'\s+1\s*$',opts,re.M):raise SystemExit('Requires reviewed NO_SYS/autodetect configuration: '+macro)
parameters=(source/'ps7_cortexa9_0/include/xparameters.h').read_text()
for macro in ['XPAR_GIGE_PCS_PMA_1000BASEX_CORE_PRESENT','XPAR_GIGE_PCS_PMA_SGMII_CORE_PRESENT']:
    if re.search(r'^#define\s+'+macro+r'\s+1\s*$',parameters,re.M):raise SystemExit('This patch supports RGMII only, not '+macro)
shutil.copytree(source,out)
lib=out/'ps7_cortexa9_0/libsrc';lwip=lib/'lwip202_v1_2/src/contrib/ports/xilinx'
changes=[];diffs=[]
def modify(path,fn):
    original_bytes=path.read_bytes();old=path.read_text();new=fn(old)
    if old==new:raise RuntimeError('No changes '+str(path))
    path.write_text(new)
    rel=str(path.relative_to(out));changes.append({'file':rel,'original_sha256':hashlib.sha256(original_bytes).hexdigest(),'patched_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='original/'+rel,tofile='patched/'+rel))
def once(text,old,new):
    if text.count(old)!=1:raise RuntimeError(f'Expected exactly one patch anchor: {old[:90]!r}, got {text.count(old)}')
    return text.replace(old,new,1)
def patch_mdio(t):
    for kind in ['Read','Write']:
        start=t.index('LONG XEmacPs_Phy'+kind+'(');end=t.index('\n}\n',start)+3;b=t[start:end]
        b=once(b,'\tLONG Status;','\tLONG Status;\n\tu32 MdioPollBudget = 100000U; /* finite CPU polling budget */')
        b=once(b,'\tdo {','\tdo {\n\t\tif (--MdioPollBudget == 0U) return (LONG)XST_FAILURE;')
        if kind=='Read':
            b=once(b,'\tXil_AssertNonvoid(InstancePtr != NULL);','\tXil_AssertNonvoid(InstancePtr != NULL);\n\tif (PhyDataPtr == NULL) return (LONG)XST_FAILURE;\n\t*PhyDataPtr = 0; /* failed reads never leave old link bits */')
        t=t[:start]+b+t[end:]
    return t
modify(lib/'emacps_v3_8/src/xemacps_control.c',patch_mdio)
for header in [lwip/'include/netif/xemacpsif.h',lwip/'netif/xemacpsif_hw.h']:
    modify(header,lambda t:once(t,'void init_emacps(', 'int init_emacps(')+'\nu32_t phy_current_speed_emacps(XEmacPs *mac, u32_t addr);\n')
def patch_hw(t):
    start=t.index('void init_emacps(');end=t.index('\nvoid init_emacps_on_error',start);b=t[start:end]
    b=once(b,'void init_emacps(', 'int init_emacps(')
    b=once(b,'\txemacpsp = &xemacps->emacps;', '\txemacpsp = &xemacps->emacps;\n\tlink_speed = XST_FAILURE;\n\teth_link_status=ETH_LINK_DOWN;\n\tnetif_set_link_down(netif);\n\tfor (i=0; i<32; ++i) { phymapemac0[i]=FALSE; phymapemac1[i]=FALSE; }')
    b=once(b,'xil_printf("In %s:Emac Mac Address set failed...\\r\\n",__func__);', 'xil_printf("In %s:Emac Mac Address set failed...\\r\\n",__func__);\n\t\treturn XST_FAILURE;')
    b=once(b,'for (i = 31; i > 0; i--)','for (i = 0; i < 32; i++)')
    fallback=b.index('\t/* If no PHY was detected, use broadcast PHY address of 0 */')
    fallback_end=b.index('\n#endif',fallback)
    b=b[:fallback]+'''\tif (!phyfoundforemac0 && !phyfoundforemac1) {
\t\txil_printf("PHY_ERROR no unique supported PHY; network down\\r\\n");
\t\treturn XST_FAILURE;
\t}'''+b[fallback_end:]
    b=once(b,'\tif (link_speed == XST_FAILURE) {','\tif (link_speed != 10 && link_speed != 100 && link_speed != 1000) {')
    b=once(b,'\t\txil_printf("Assert due to phy setup failure \\n\\r",__func__);','\t\txil_printf("PHY setup failed; network remains down\\r\\n");\n\t\tnetif_set_link_down(netif);\n\t\treturn XST_FAILURE;')
    pos=b.rfind('\n}');b=b[:pos]+'\n\treturn XST_SUCCESS;'+b[pos:]
    return t[:start]+b+t[end:]
modify(lwip/'netif/xemacpsif_hw.c',patch_hw)
def patch_init(t):
    send_start=t.index('static err_t _unbuffered_low_level_output(');send_end=t.index('\n}',send_start)+2
    t=t[:send_start]+once(t[send_start:send_end],'return ERR_OK;', 'return status == XST_SUCCESS ? ERR_OK : ERR_IF;')+t[send_end:]
    t=once(t,'\t\t_unbuffered_low_level_output(xemacpsif, p);\n\t\terr = ERR_OK;', '\t\terr = _unbuffered_low_level_output(xemacpsif, p);')
    t=once(t,'\tlow_level_init(netif);\n\treturn ERR_OK;', '\treturn low_level_init(netif);')
    start=t.index('static err_t low_level_init(struct netif *netif)\n{');end=t.index('\nvoid HandleEmacPsError',start);b=t[start:end]
    b=once(b,'\txemacpsif->recv_q = pq_create_queue();\n\tif (!xemacpsif->recv_q)\n\t\treturn ERR_MEM;', '\txemacpsif->recv_q = NULL; /* queue allocated only after successful PHY */')
    b=once(b,'\tinit_emacps(xemacpsif, netif);','''\tif (init_emacps(xemacpsif, netif) != XST_SUCCESS) {
\t\tXEmacPs_Stop(&xemacpsif->emacps);
\t\tmem_free(xemacpsif); mem_free(xemac); NetIf = NULL;
\t\treturn ERR_IF;
\t}''')
    b=once(b,'\tinit_dma(xemac);','''\tif (init_dma(xemac) != XST_SUCCESS) {
\t\tXEmacPs_Stop(&xemacpsif->emacps); free_txrx_pbufs(xemacpsif);
\t\tmem_free(xemacpsif); mem_free(xemac); NetIf = NULL; return ERR_IF;
\t}
\txemacpsif->recv_q = pq_create_queue();
\tif (!xemacpsif->recv_q) {
\t\tXEmacPs_Stop(&xemacpsif->emacps); free_txrx_pbufs(xemacpsif);
\t\tmem_free(xemacpsif); mem_free(xemac); NetIf = NULL;
\t\treturn ERR_MEM;
\t}''')
    b=once(b,'\tif (xemacpsif == NULL) {','\tif (xemacpsif == NULL) {\n\t\tNetIf = NULL;')
    b=once(b,'\txemac = mem_malloc(sizeof *xemac);','\tmemset(xemacpsif, 0, sizeof *xemacpsif);\n\txemac = mem_malloc(sizeof *xemac);')
    b=once(b,'netif->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP |\n\t\t\t\t\t\t\t\t\t\t\tNETIF_FLAG_LINK_UP;', 'netif->flags = NETIF_FLAG_BROADCAST | NETIF_FLAG_ETHARP;')
    b=once(b,'\tstatus = XEmacPs_CfgInitialize(', '\tif (!mac_config || xemac->topology_index < 0) {\n\t\tmem_free(xemacpsif); mem_free(xemac); NetIf = NULL; return ERR_IF;\n\t}\n\tstatus = XEmacPs_CfgInitialize(')
    b=once(b,'\tnetif->state = (void *)xemac;','\tnetif->state = (void *)xemac;\n\tnetif_set_link_up(netif);')
    # No driver error may continue into PHY initialization or DMA.
    b=once(b,'xil_printf("In %s:EmacPs Configuration Failed....\\r\\n", __func__);',
      'xil_printf("In %s:EmacPs Configuration Failed....\\r\\n", __func__);\n\t\tmem_free(xemacpsif); mem_free(xemac); NetIf = NULL; return ERR_IF;')
    b=once(b,'\tif (xemac == NULL) {\n', '\tif (xemac == NULL) {\n\t\tmem_free(xemacpsif); NetIf = NULL;\n')
    return t[:start]+b+t[end:]
modify(lwip/'netif/xemacpsif.c',patch_init)
def patch_dma(t):
    t=once(t,'\t/* Allocate 64k for Rx and Tx bds each to take care of extreme cases */',
      '\t/* Stable per-MAC slice: retries/errors must not consume the BD arena. */\n\tbd_space_index = (index / XLWIP_CONFIG_N_RX_DESC) * 0x40000U;\n\tif (bd_space_index + 0x40000U > sizeof bd_space) return ERR_IF;\n\t/* Allocate 64k for Rx and Tx bds each to take care of extreme cases */')
    start=t.index('void free_txrx_pbufs(');end=t.index('\nvoid free_onlytx_pbufs',start);b=t[start:end]
    old='''\tfor (index = index1; index < (index1 + XLWIP_CONFIG_N_TX_DESC); index++) {
\t\tp = (struct pbuf *)rx_pbufs_storage[index];
\t\tpbuf_free(p);

\t}'''
    new='''\tindex1 = get_base_index_rxpbufsstorage(xemacpsif);
\tfor (index = index1; index < (index1 + XLWIP_CONFIG_N_RX_DESC); index++) {
\t\tif (rx_pbufs_storage[index] != 0) {
\t\t\tp = (struct pbuf *)rx_pbufs_storage[index];
\t\t\tpbuf_free(p);
\t\t\trx_pbufs_storage[index] = 0;
\t\t}
\t}'''
    return t[:start]+once(b,old,new)+t[end:]
modify(lwip/'netif/xemacpsif_dma.c',patch_dma)

def patch_phy(t):
    start=t.index('void detect_phy(XEmacPs *xemacpsp)');end=t.index('\nu32_t phy_setup_emacps',start)
    b='''void detect_phy(XEmacPs *xemacpsp)
{
    u16_t id1,id2;
    u32_t addr,count=0;
    u32_t *map=(xemacpsp->Config.BaseAddress==XPAR_XEMACPS_0_BASEADDR)?phymapemac0:phymapemac1;
    for (addr=0; addr<32; ++addr) map[addr]=FALSE;
    for (addr=0; addr<32; ++addr) {
        if (XEmacPs_PhyRead(xemacpsp,addr,2,&id1)!=XST_SUCCESS ||
            XEmacPs_PhyRead(xemacpsp,addr,3,&id2)!=XST_SUCCESS) {
            xil_printf("PHY_ERROR MDIO scan addr=%u\\r\\n",addr);
            for (addr=0; addr<32; ++addr) map[addr]=FALSE;
            return;
        }
        if (id1==0 || id1==0xFFFFU) continue;
        if (id1==0x001CU && (id2 & 0xFFF0U)==0xC910U) {map[addr]=TRUE; ++count;}
        else xil_printf("PHY_ERROR unsupported addr=%u id=%04x:%04x\\r\\n",addr,id1,id2);
    }
    if (count!=1) for (addr=0; addr<32; ++addr) map[addr]=FALSE;
}
'''
    t=t[:start]+b+t[end:]
    start=t.index('static u32_t get_Realtek_phy_speed(');end=t.index('\n#endif',start)
    return t[:start]+(ROOT/'network_phy_policy.inc').read_text()+t[end:]
modify(lwip/'netif/xemacpsif_physpeed.c',patch_phy)
def patch_link(t):
    for name in ['phy_link_detect','phy_autoneg_status']:
        start=t.index('static u32_t '+name+'(XEmacPs');end=t.index('\n}',start)+2;b=t[start:end]
        old='\tXEmacPs_PhyRead(xemacp, phy_addr, IEEE_STATUS_REG_OFFSET, &status);'
        if b.count(old)!=2:raise RuntimeError('Unexpected MDIO monitor')
        b=b.replace(old,'\tif (XEmacPs_PhyRead(xemacp, phy_addr, IEEE_STATUS_REG_OFFSET, &status)!=XST_SUCCESS || status==0xFFFFU) return 0;')
        if name=='phy_link_detect':b=once(b,'if (status & IEEE_STAT_LINK_STATUS)','if ((status & 0x24U) == 0x24U)')
        t=t[:start]+b+t[end:]
    t=once(t,'link_speed = phy_setup_emacps(xemacp,','link_speed = phy_current_speed_emacps(xemacp,')
    # Don't mark link up after the link-monitor's re-negotiation attempt failed.
    old='''\t\t\t\tXEmacPs_SetOperatingSpeed(xemacp, link_speed);'''
    new='''\t\t\t\tif (link_speed!=10 && link_speed!=100 && link_speed!=1000) {
\t\t\t\t\tnetif_set_link_down(netif); eth_link_status=ETH_LINK_NEGOTIATING; return;
\t\t\t\t}
\t\t\t\tXEmacPs_SetOperatingSpeed(xemacp, link_speed);'''
    return once(t,old,new)
modify(lwip/'netif/xadapter.c',patch_link)
(out/'network_patch.diff').write_text(''.join(diffs));(out/'network_patch_manifest.json').write_text(json.dumps(changes,indent=2)+'\n')
print('Patched',len(changes),'files in new BSP copy:',out)

