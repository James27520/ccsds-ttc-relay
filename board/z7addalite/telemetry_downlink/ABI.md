# Finite telemetry transmitter ABI v1

Base `0x43C01000`, aperture 4 KiB; all accesses aligned 32-bit. Backend matches
`tc_axil_frontend`. Full `WSTRB=0xf` is required for every write. Reads are
combinational. Invalid accesses return the frontend's SLVERR; rejected writes
also latch DIAG. No automatic repetition exists.

| Offset | Access | Meaning |
|---|---|---|
| 00 | RO | STATUS: bit0 owner/busy, bit1 ready to SEND, bit2 sticky fault, bit3 sticky completion, bit4 DAC active (synchronized), bit5 consumed, bit6 recovery_pending (`stop_request OR stop_ack_sync[2]`), bit7 peripheral_reset (`reset25`) |
| 04 | RO | DIAG bits: 0 bad address, 1 partial write, 2 busy write, 3 invalid length/value, 4 buffer overflow, 5 not ready/consumed, 6 STOP completion, 7 DAC configuration loss |
| 08 | WO | CLEAR_BUFFER: write 1 when idle; clears word count, bit length, consumed, completion and DIAG |
| 0C | WO | DATA: append one 32-bit word (maximum 128 words / 512 bytes) |
| 10 | RW | BIT_LENGTH: 1..4096, cannot exceed loaded words times 32 |
| 14 | WO | SEND_ONCE: write 1; requires ready and valid length; immediately owns RAM until completion/cancellation |
| 18 | WO | STOP: write 1; cancellation handshake retains owner until DAC acknowledges; idle STOP is harmless |
| 1C | RO | MAGIC `0x544D5431` (`TMT1`) |
| 20 | RO | ABI version 1 |
| 24 | RO | Configured bit length |
| 28 | RO | Number of loaded words, 0..128 |
| 30 | RO | Top-level DAC configuration diagnostic: result[31:28], step[23:16], register[15:8], read value[7:0] |
| 34 | RO | Top-level DAC configuration bit0 verified, bit1 finished (success or failure) |

Normal flow: wait idle, CLEAR_BUFFER, append DATA words, set BIT_LENGTH, poll
ready, SEND_ONCE, poll owner until zero. Each packet requires CLEAR_BUFFER to
rearm; completion, STOP, and configuration loss cannot automatically restart.
DATA/CLEAR_BUFFER/BIT_LENGTH/SEND_ONCE are rejected while owned. Polling STATUS
is required: mailbox acceptance is not packet completion. STOP may finish a
packet before its request reaches DAC; in that race normal completion wins.
All writes are rejected while STATUS.bit7 is set. Software must defer MMIO
writes during peripheral reset and wait for STATUS.bit6 to clear before
CLEAR_BUFFER or a new SEND: ownership release can precede the STOP return
level's synchronization. STATUS remains readable during reset. This lets PS
avoid intentionally rejected writes on platforms whose MMIO primitives do
not recover AXI SLVERR responses.

Bits transmit MSB first within each word, in write order. The final word's low
unused bits are ignored. Bit 1 maps to positive sine and bit 0 to inverted sine.
`SYMBOL_CYCLES=2500` at DAC clock 250 MHz gives 100 ksymbol/s. DDS uses a 32-bit
phase accumulator with increment 1554778161, giving approximately 90.5 MHz,
and a 64-entry rounded sine table with fixed signed peak 128 (128/32768 full
scale). `dac_sample` is signed 16-bit; external integration holds DAC2 at zero.
Idle samples are exactly zero. `tx_active`, `tx_bit`, and single-cycle
`tx_symbol_start` are DAC-domain observability outputs.

Inputs `config_verified` and `dac_reset` belong to the DAC domain; root must
synchronize the verified condition and arrange paired mailbox resets in both
domains on system reset, PS reset, or clock unlock, with synchronous release.
The sample output is immediately gated by DAC reset or verified deassertion.
An interrupted packet aborts and stays consumed. STOP uses a retained level
and acknowledgement synchronization, so it also catches commands in transit.
There are no multibit status CDC buses; the dual-port RAM stays owned while
read. Apply bundled-data max delays to `tm_cmd_mailbox` (3 ns destination
250 MHz) and `tm_done_mailbox` (20 ns destination 25 MHz), following existing
`tc_mailbox` constraints.

Standalone simulation compiles this module, existing `tc_mailbox.v`, and
`sim/tb_tm_packet_tx.sv`. It checks full DAC samples against an independent
rounded sine/phase model, all bits across RAM word boundaries, exact default
2500-clock symbols, finite packet termination, ownership, error handling,
STOP, verified loss, paired reset, and successful transmission after reset.
