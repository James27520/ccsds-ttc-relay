# Continuous experimental text receiver

`stream_rx <output-prefix> [--stdio]` reads **2,500,000 complex samples/s**, interleaved little-endian signed `int16` I,Q with each value sign-extended from 12 bits (`-2048..2047`). A partial IQ group or another sample encoding is an error. Input is bytes from a local `iio_readdev` pipe, not a debug UART transfer. The program never configures the radio, opens a COM port, starts/stops a transmitter, or accepts a known payload or transmitter manifest.

This receiver implements the existing experimental `AAAA | length | payload | CRC16` wire format in `sw/tools/rf_text_link.py`, with business payload lengths 1..49 (17 bytes of G1 envelope plus at most 32 UTF-8 body bytes) and CRC-16/CCITT-FALSE over the payload only. G1 messages from `sw/ground_station/protocol.py` are transported unchanged as `payload_hex`. The consumer validates UTF-8 and canonical G1 after CRC acceptance. Longer legacy experimental text frames are outside this business receiver's specification. This is not CCSDS framing, authentication, or a BER measurement.

## Build and run

```sh
cc -O3 -std=c99 -Wall -Wextra -Werror stream_rx.c -lm -pthread -o stream_rx
# Example invocation after the caller has configured/verified the RX scan mask:
iio_readdev -b 32768 cf-ad9361-lpc voltage0 voltage1 | ./stream_rx /tmp/business_rx --live
```

The device/channel names are examples; the caller verifies the actual RX mask and sample format. One input thread drains the pipe into a fixed 32 × 64 KiB queue while the main thread performs DSP. The queue holds 524288 complex samples (209.7 ms); a full queue blocks its producer, never grows or silently discards samples. `--live` records each full-queue episode as an upstream continuity risk. Without `--live`, an unpaced offline file may fill the queue normally and is decoded in full.

TX runs independently; this program contains no TX control. Linux SIGINT/SIGTERM requests stop; the consumer wakes within its 100 ms condition timeout, finishes its current work and publishes stopped status. The owner stops the upstream IIO reader as well. Process exit terminates any remaining blocked input thread; SIGKILL cannot publish final status. Exit 0 means normal EOF or handled stop; 1 means input/publication failure; 2 means incorrect arguments.

The Linux build requires C99, libc, libm and POSIX threads (`-pthread`). The MinGW host build uses Windows threads/condition variables and needs `-D__USE_MINGW_ANSI_STDIO=1` for standard 64-bit format specifiers. Host scalar tests do not establish ARM throughput.

The distributable `bin/stream_rx_armv7` is a static ARMv7 hard-float Linux executable targeting Cortex-A9, generated with Zig 0.14.1's musl toolchain. `build_manifest.json` records source and executable hashes, target, flags, format and DSP parameters without machine-specific paths. The same tested executable is copied to the ignored `build/stream_rx` development location. From the repository root, reproduce it with:

```powershell
New-Item -ItemType Directory -Force board/terminal/stream_rx/build | Out-Null
& 'D:/RelayTools/toolchains/zig-python/ziglang/zig.exe' cc -target arm-linux-musleabihf -mcpu=cortex_a9 -O3 -std=c99 -Wall -Wextra -Werror -static -s board/terminal/stream_rx/stream_rx.c -lm -pthread -o board/terminal/stream_rx/build/stream_rx
```

The native host report does not establish board compatibility or sustained board throughput. The actual board pipeline must be benchmarked independently, including TX-active operation and input samples processed per elapsed second.

## Bounded output

The prefix's parent directory must already exist. There must be one receiver writer per prefix. Output uses same-directory temporary files followed by replacement; readers see complete JSON rather than partially updated JSON.

* `<prefix>.status.json`: latest status object, replaced at each decoded window and on startup/EOF/stop. `samples`, `clips` (I/Q component count), and `rms` cover raw input consumed from stdin. `recent_rms` and `recent_clips` cover the latest read block (at most 65536 bytes / 16384 complex samples), avoiding dilution of a later level increase by historical low-level samples. Raw read-block statistics may lead frontend processing by at most one such block. `frames` counts CRC-valid physical frame observations, with overlap observations suppressed by absolute frame-end position. `rejects` is the number of complete CRC-rejected candidates in selected timing/polarity windows; overlapping windows and shifted AAAA headers can contribute repeated candidates. `windows`, `max_decode_ms`, `last_decode_ms`, `carrier_offset_hz`, `messages`, `uptime_ms`, `input_error`, `eof`, and `stopped` aid monitoring.
* `<prefix>.messages.json`: array of at most 128 distinct CRC-valid payloads in arrival order. Each item has `payload_hex`, `payload_bytes`, `crc16`, `crc_valid`, `carrier_offset_hz`, and `first_symbol_sample`. Exact byte-identical payloads are suppressed while present. Oldest entries are evicted, so previously evicted payloads can appear again. This is payload-level FIFO history; G1 ID conflicts and application-level deduplication remain the consumer's responsibility.
* `--stdio`: additionally emits newline-delimited `{ "type": "frame", "frame": {...} }` on a newly retained payload and `{ "type": "status", "status": {...} }` on status publication. Diagnostics go to stderr. Without this flag stdout is silent. The bounded files are still written in either mode. No append-only IQ, log or event files are created.

Frame sample positions are relative to process input and compensate the causal frontend FIR delay. Filter edges cannot be evaluated; a finite file ending inside a frame need not recover that frame. CFO estimates without a CRC-valid frame are diagnostics only. A `status` file can be stale when no samples arrive, so its age must be checked by the polling backend.

## DSP and performance limits

The frontend validates raw IQ, counts clipped components, accumulates exact integer block energy, and mixes the nominal **-250 kHz** carrier to DC using a periodic oscillator. It low-passes with a 61-tap Hamming FIR (100 kHz cutoff), and decimates by five. At 500 ksample/s it applies the reference algorithm: square-law Hann-windowed carrier estimation with residual search +/-20 kHz, logarithmic parabolic peak interpolation, frequency and BPSK phase correction, normalized 41-tap SRRC (`beta=.35`, span 8), all five symbol timing phases and both polarities, AAAA framing and CRC acceptance. The CFO estimation branch integrates groups of four squared samples and uses a 16384-point FFT at 125 ksample/s, preserving the full 65.536 ms observation duration. This integrate-and-dump filter reduces high-frequency components but is not an ideal anti-alias filter; CRC acceptance remains required. The symbol path retains every 500 ksample/s sample. Cortex-A9 builds use explicit NEON for raw validation/statistics/mixing, the FIR, FFT butterflies and SRRC. Portable host builds use scalar fallbacks. Timing ranking is valid-frame count, complete candidate count, then eye opening, matching the Python implementation. There is no carrier-residual scanning repair.

Windows contain 32768 decimated samples, with 28672-sample hop and 4096-sample overlap. The overlap exceeds the maximum 54-byte business wire frame (2160 decimated samples) plus matched-filter edges, allowing a complete frame crossing an ordinary window boundary to be considered. Frequency drift or a transient can still cause CRC rejection. Filtering state and mixer phase persist across read blocks and windows.

One regular hop represents **57.344 ms** of input. `fft_ms`, `carrier_ms` and `matched_ms` expose the latest stage costs. `max_decode_ms` includes the window DSP and candidate scan; it excludes the continuously running frontend, file publication and pipe I/O. Measure sustained whole-process input rate, CPU use, and the IIO/DMA overflow evidence on the actual board while TX is active. `loss_measured` deliberately remains `false`: this raw stream has no sequence counter and cannot prove that hardware or pipe samples were never lost. Host speed is not an ARM throughput guarantee. The current implementation uses a few MB of fixed working memory and retains no growing sample buffer.

## Host acceptance tests

From the repository root:

```powershell
& 'D:/AMDDesignTools/2026.1/tps/mingw/8.3.0/win64.o/nt/bin/gcc.exe' -O3 -std=c99 -D__USE_MINGW_ANSI_STDIO=1 -Wall -Wextra -Werror board/terminal/stream_rx/stream_rx.c -lm -o board/terminal/stream_rx/stream_rx_host.exe
python board/terminal/stream_rx/test_stream_rx.py board/terminal/stream_rx/stream_rx_host.exe --capture-dir D:/RelayTools/work/six_line_20261031/duplex_rxfirst_recovered --report board/terminal/stream_rx/host_acceptance.json
```

Tests use generated IQ for a maximum-length G1 frame (49 payload bytes) crossing a window boundary, a Chinese G1 message with +250 Hz residual CFO, a rejected 50-byte payload, corrupt CRC, noise, malformed sample encoding, truncated IQ, a sudden level increase with exact RMS/clip checks and 135 distinct payloads with a 128-entry retention bound. Optional real captures are decoded without any expected payload supplied to the native process. The test compares the native output to an independent invocation of the existing Python decoder on the first raw IQ window; it does not read previous result or manifest files. `host_acceptance.json` records the actual host run and measured timings.

## Reception health and recovery

The terminal polls a single session-specific script. It verifies the current Linux boot, USB identity before/after the transaction, all three PID/start-time records, selected channels and DMA, renews the RX lease, then returns statistics. Full `iio_info` remains part of configuration/start identification, not periodic TX monitoring.

Status includes acquired/consumed sample counts, current queue occupancy, capacity, high water, backpressure episodes, cumulative pipe-read/consumer-wait/frontend/DSP/publication time and process CPU time. Host snapshots also retain CPU online/load/ticks, process statistics and UART poll duration. Read time includes waiting for the producer; elapsed stage time includes scheduling delays. The raw stream has no hardware sample sequence number: `loss_measured=false` is a limitation, never evidence of zero loss.

The controller observes nonoverlapping intervals of at least 3 seconds. Processing below 2.45 MSPS or a half-full queue gives a visible performance warning; sustained unhealthy intervals totaling 12 seconds rebuild RX. A full live queue or 8 seconds without sample progress also requests recovery. Two healthy intervals (at least 6 seconds) clear a transient warning. Two automatic rebuilds are allowed per 120 seconds; a further failure stops RX/TX but retains the verified connection, readbacks and message history, exposing “恢复接收”. Recovery starts a fresh DSP process, so partial windows cannot bridge the interruption. Old TX is never restarted; pending messages become manual retries. Input-format, CRC-report integrity, USB, boot or ownership failures still disconnect.

Before starting RX, the owner records Linux CPU present/possible/online state. For the verified two-core board booted with `maxcpus=1`, it brings the already-present CPU1 online only after idle-DMA/TX-off checks. This uses CPU hotplug for the current boot, not an overclock or persistent bootloader change. Unsupported or single-core configurations remain subject to the same throughput checks.
