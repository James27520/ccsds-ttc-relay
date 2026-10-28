# DAC clock / interface review (offline, 2026-10-28)

The preserved r4c AD9516 table supports ADC 125 MSPS together with DAC
**250 MSPS input samples per I/Q channel and 1000 MSPS analog conversion**.
Calling this a 250 MSPS DAC without naming the input rate is ambiguous.
No hardware was accessed for this review.

## Clock derivation and primary evidence

Local schematic: `D:/Z7ADDALite资料/02硬件资料/原理图/Z7ADDALite_SCH_RevB.pdf`,
page 12. The reference is a 10 MHz TCXO. OUT5 drives DACCLKP/N;
OUT7 drives AD_CLK_P/N; OUT6 is PL_CLK_P/N; OUT8 drives DAC_REF_P/N.
AD9516 is the -3 variant. Its local datasheet is
`D:/Z7ADDALite资料/02硬件资料/芯片手册/AD9516.pdf` (English Rev.C).

`../telecontrol_system/src/tc_boot_words.vh:11` onwards programs R=1,
A=8, B=12, P=16 (0x011=01,012=00,013=08,014=0c,015=00,016=05).
AD9516 pp38-39 gives N=P*B+A: 200, so VCO=2000 MHz.
Table60 p76 decodes 0x1e1=02 as internal VCO, divider enabled;
0x1e0=00 means /2. Distribution clock is therefore 1000 MHz.

`tc_boot_words.vh:54-69` programs 0x197=80 (Divider2 bypass),
0x198=00 (no direct-VCO bypass), hence OUT5=1000 MHz. AD9516
Table58 pp73-74 maps Divider2 to OUT4/5. Divider3 serves OUT6/7:
0x199=33 means (3+1)+(3+1)=/8, 0x19c=20 bypasses second stage,
hence ADC/PL clocks=125 MHz (Table59 pp74-75).
Changing Divider3 from the old 0x11 to r4c 0x33 does not change OUT5.

Use the raw ADC DCO IBUFDS output to feed a separate MMCM 125->250 MHz,
as in `D:/RelayTools/work/adda_link/adda_probe/src/adda_probe_top.v:24`
and `scripts/sample_clock_ip.tcl:4`. Preserve ADC BUFIO/BUFG paths and
ADC timing constraints. DCI must run before FIFO alignment and remain
running while samples are muted. The AD9122 PLL stays off (0x0a=00).
ADC125, MMCM250, and DAC1000 share a frequency source; FIFO initialization
absorbs their phase relationship. Lock does not itself prove DAC FIFO health.

## Encoding, interpolation and timing

[AD9122 Rev.C primary datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD9122.pdf)
pp18,23,26-27,31-36 supports the configured R2 ID, signed word format,
DCI delay, interpolation, DDR order, FIFO and bandwidth choices.
0x03=00 selects two's complement, I first, word bus; 0x1b=a4 bypasses
premodulation/NCO and keeps channels independent. 0x1c=00,1d=00,1e=01
enable HB1/HB2 and bypass HB3, giving 4x interpolation. DCI high carries I
(DAC1), low carries Q (DAC2). Use ODDR D1=I, D2=Q and another ODDR
D1=1,D2=0 for DCI, both SAME_EDGE, same 250 MHz clock. FRAME stays low.
Zero signed samples are midscale; do not use offset-binary 0x8000 as mute.

The initial carrier choice is 90.5 MHz. At 250 MSPS the conventional
HB1 lowpass guaranteed passband ends at 100 MHz. A 100.5 MHz narrowband
carrier remains feasible with reduced image rejection (Table16 p36 gives
80.4% total bandwidth / 0.0012 dB ripple / 80 dB rejection); occupied
bandwidth must be considered. This review does not assert measured RF quality.

0x16=03 requires R2 silicon; read 0x7f bits[5:2]=0011 (0x0c masked by3c).
The older local Chinese Rev.A ID description differs; current English Rev.C
p18 and p30 are explicit. Reject R1 because it lacks programmable DCI delay.
Rev.C p32 Table13: DCI delay3 gives setup=-0.47 ns, hold=1.38 ns.
Data and DCI are edge aligned at the pins; do not add an external 90-degree
DCI shift. For STA use an abstract +1 ns capture reference to select the
proper DDR edge pairs, with transformed setup=.53 ns, hold=.38 ns.
Adding the existing explicit 0.10 ns PCB skew budget gives:

```tcl
# Replace hierarchy with actual forwarded DCI ODDR clock pin.
create_generated_clock -name dac_capture_ref -source [get_pins tx_io/oddr_inst/C] -edges {1 2 3} -edge_shift {1.000 1.000 1.000} [get_ports dac_dci_p]
set_output_delay -clock dac_capture_ref -max 0.630 [get_ports {dac_data_p[*]}]
set_output_delay -clock dac_capture_ref -min -0.480 [get_ports {dac_data_p[*]}]
set_output_delay -clock dac_capture_ref -clock_fall -add_delay -max 0.630 [get_ports {dac_data_p[*]}]
set_output_delay -clock dac_capture_ref -clock_fall -add_delay -min -0.480 [get_ports {dac_data_p[*]}]
```

This virtual phase is a timing model, not a physical DCI delay. It enforces
latest current transition DCI+0.37ns and earliest following transition
DCI+1.48ns. The 100ps board budget is an assumption, not a measured PCB value.
No broad false paths are appropriate on DAC data or DCI. Preserve the
100ps clock uncertainty and analyze positive and negative DDR edges.

## Analog path (schematic page 11 visually checked)

J6 is DAC1 and J7 is DAC2, despite ambiguous TX_IN/TX_OUT labels.
Each has 49.9-ohm current-to-voltage shunts, a unity differential AD8000
stage (four 510-ohm resistors), a 49.9-ohm output series resistor, and 0-ohm
DC coupling link (R98/R109). AD8000 supplies are +/-3.3V. No installed
reconstruction lowpass is shown (C175/C177 are NC).
With 19.6mA nominal full-scale current (AD9122 default 10k FSADJ), the
ideal differential peak is about 19.6mA*(49.9 || 1020)=0.932V, giving
approximately 0.933 Vpp into 50 ohms or 1.865 Vpp unloaded. This is a
low-frequency circuit estimate including loading of the 510-ohm network,
not a measured 90.5MHz SMA level. Scale it by signed amplitude/32768.
Polarity is inverted by this difference stage; BPSK can absorb the phase sign.
Begin with a low digital amplitude and zero DAC2. Receiving SDR input range
and any existing attenuation still require system-specific verification.

## Configuration interface and offline verification

`tm_dac_config` inputs: clk25, active-high reset, start_allowed, sdi.
Outputs: sdo, sdo_enable (1=drive), cs_n, sclk, verified, finished,
diagnostic[31:0]. Connect through IOBUF I=sdo/T=~sdo_enable/O=sdi.
Top owns DAC RESET#; only assert start_allowed after ADC boot completes and
MMCM lock is stable. It must remain true throughout operation. A prerequisite
loss invalidates verification; explicit reset is required for another attempt.
finished means terminal success OR failure; only verified permits modulation.

The 26 writes preserve the vendor flow (0x17=04), plus bounded FIFO
request/acknowledgement assertion and deassertion reads, safe level check
(07/0f/1f), and 14 critical register reads. The 0x1f level is retained as
the vendor's allowed +1 result (Rev.C p34), rather than implementing adaptive
phase-offset retuning. No automatic reconfiguration retry occurs on failure.
The SPI engine derives from frozen r4c spi_rw24, narrowed to 8+8 bits, with
write echo fault detection. SDIO releases one clk after the eighth command
rising edge and before its falling edge. HALF_CYCLES>=2 is mandatory;
default50 yields 250kHz SCLK at clk25. Deadline default1s covers all polling.

Diagnostic high nibble: 0 idle,1 verified,2 critical read mismatch,3 deadline,
4 prerequisite lost,5 driven-pin echo mismatch. Bits23:16 are step,15:8
register address,7:0 last read. A passing result ends at step42/register01.
Critical reads cover 7f,00,03,08,0a,10,11,16,1b,1c,1d,1e,17,01.
This proves SPI configuration, not analog output or high-speed LVDS capture;
SED and spectrum/receiver checks remain separate hardware acceptance work.

Run `scripts/run_dac_config_sim.ps1`. The resolved three-state BFM checks
every critical read gate, disconnected reads, clamped write pin, FIFO ack
never arriving or never clearing, unsafe FIFO level, turnaround overlap,
no precondition-early start, no retry, and invalidation after clock loss.
Vivado2026.1 xvlog/xelab/xsim passed on 2026-10-28, using accelerated
SPI_HALF_CYCLES=2 / deadline10000 cycles. Default-rate hardware was not run.
