"""One bounded UART transaction; shell builtins check the owned RX processes.

The script is created once per verified boot/session. No iio_info, awk or
per-file shell command is needed during steady-state polling.
"""
import shlex


def snapshot_script(radio):
    q = shlex.quote
    d = radio.stream
    body = ['#!/bin/sh', 'fail() { echo "RXERROR $1 $2"; exit 0; }',
            'readv() { IFS= read -r v < "$1" || fail identity read; }',
            # A process can exit between the ownership check and metrics read.
            # Absence is recoverable; unreadable/reused/live malformed is not.
            'readp() { pid=$1; ticks=$2; name=$3; '
            'if ! { IFS= read -r pstat < "/proc/$pid/stat"; } 2>/dev/null; then '
            'test ! -e "/proc/$pid/stat" && fail unavailable "$name"; '
            'fail identity "$name"; fi; '
            'fields=${pstat##*) }; set -- $fields; '
            'test "$#" -ge 20 || fail identity "$name"; '
            'state=$1; shift 19; '
            'test "$1" = "$ticks" || fail identity "$name"; '
            'case "$state" in Z) fail unavailable "$name";; R|S|D|I) ;; '
            '*) fail identity state;; esac; }']
    for path, value in [('/proc/sys/kernel/random/boot_id', radio._fingerprint['linux_boot_id']),
                        (radio.phy+'/name', 'ad9361-phy'),
                        (radio.tx+'/name', 'cf-ad9361-dds-core-lpc'),
                        (radio.rx+'/name', 'cf-ad9361-lpc')]:
        body += [f'readv {q(path)}; test "$v" = {q(value)} || fail identity mapping']
    for name in ('reader', 'decoder', 'guard'):
        pid, ticks = radio.stream_owners[name]
        if not pid.isdigit() or not ticks.isdigit():
            raise ValueError('接收进程身份无效')
        body += [f'readv {q(d+"/"+name+".owned")}; test "$v" = {q(pid+" "+ticks)} || fail identity {name}',
                 f'readp {pid} {ticks} {name}']
    mask = ('0', '0', '1', '1') if radio.rx_channel == 2 else ('1', '1', '0', '0')
    for n, value in enumerate(mask):
        body += [f'readv {q(radio.rx+f"/scan_elements/in_voltage{n}_en")}; test "$v" = {value} || fail identity mask']
    body += [f'readv {q(radio.rx+"/buffer/enable")}; test "$v" = 1 || fail unavailable dma',
             # Read and validate everything before the first success marker;
             # late RX exits must not produce a partially successful response.
             'readv /sys/devices/system/cpu/online; cpu_online=$v',
             'readv /proc/loadavg; loadavg=$v',
             'readv /proc/stat; cpu_ticks=$v']
    for name in ('decoder', 'reader'):
        pid, ticks = radio.stream_owners[name]
        body += [f'readp {pid} {ticks} {name}; {name}_stat=$pstat']
    body += [f'readv /proc/sys/kernel/random/boot_id; test "$v" = {q(radio._fingerprint["linux_boot_id"])} || fail identity boot',
             'boot=$v',
             'read -r up rest < /proc/uptime; up=${up%%.*}',
             f'echo $((up + 90)) > {q(d+"/deadline.next")} && mv {q(d+"/deadline.next")} {q(d+"/deadline")} || fail identity lease',
             'echo RXSNAP1',
             f'if test -f {q(d+"/rx.status.json")}; then cat {q(d+"/rx.status.json")} {q(d+"/rx.messages.json")}; else echo "null []"; fi',
             'echo; echo RXMETRICS',
             'printf "%s\\n" "$cpu_online" "$loadavg" "$cpu_ticks" "$decoder_stat" "$reader_stat" "$boot"']
    return ('\n'.join(body)+'\n').encode('ascii')
