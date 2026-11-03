import sys, time
sys.path.insert(0, r"E:\LDSDR_010\rk3588")
from serial_port import SerialPort

PORT = "COM11"
OUT = r"E:\LDSDR_010\new_board_iio.txt"


def rd(sp, secs):
    t0 = time.time(); o = bytearray()
    while time.time() - t0 < secs:
        d = sp.read()
        if d: o += d
        else: time.sleep(0.03)
    return bytes(o)


sp = SerialPort(PORT, 115200)
time.sleep(0.4); sp.read()
sp.write("\r\n"); time.sleep(1.2)
b = rd(sp, 1.2).decode("ascii", "replace")
if "login:" in b:
    sp.write("root\r\n"); time.sleep(1.5); rd(sp, 0.8)
    sp.write("analog\r\n"); time.sleep(3.0); rd(sp, 1)
sp.write("stty -echo 2>/dev/null; export PS1='NB> '\r\n"); time.sleep(1.0); rd(sp, 0.6)

f = open(OUT, "w", encoding="utf-8")


def W(s):
    print(s); f.write(s + "\n"); f.flush()


def cmd(c, wait=1.5):
    sp.write(c + "\r\n"); time.sleep(wait)
    t = rd(sp, 0.7).decode("ascii", "replace")
    return "\n".join(s.replace("NB>", "").strip() for s in t.splitlines()
                     if s.replace("NB>", "").strip() and s.strip() != c)


probes = [
    ("网络", "ip addr show usb0 2>&1 | head -6"),
    ("IIO 工具", "which iio_attr iio_info iio_readdev iio_writedev 2>&1"),
    ("设备0 通道", "ls /sys/bus/iio/devices/iio:device0/ 2>/dev/null | tr '\\n' ' '"),
    ("RX_LO 可用范围", "cat /sys/bus/iio/devices/iio:device0/out_altvoltage0_RX_LO/frequency_available 2>&1 | head -3"),
    ("TX_LO 当前值", "cat /sys/bus/iio/devices/iio:device0/out_altvoltage1_TX_LO/frequency 2>&1"),
    ("采样率", "cat /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency 2>&1"),
    ("采样率范围", "cat /sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency_available 2>&1 | head -3"),
    ("RF 带宽", "cat /sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth 2>&1"),
    ("带宽范围", "cat /sys/bus/iio/devices/iio:device0/in_voltage_rf_bandwidth_available 2>&1 | head -3"),
    ("设备0 型号", "cat /sys/bus/iio/devices/iio:device0/name 2>&1"),
    ("设备1 (RX DMA)", "cat /sys/bus/iio/devices/iio:device1/name 2>&1; "
                        "cat /sys/bus/iio/devices/iio:device1/scan_elements/*_en 2>/dev/null | tr '\\n' ' '"),
    ("设备2 (TX DMA)", "cat /sys/bus/iio/devices/iio:device2/name 2>&1"),
    ("设备3", "cat /sys/bus/iio/devices/iio:device3/name 2>&1"),
    ("DMA 缓冲", "cat /sys/module/industrialio_buffer_dma/parameters/* 2>/dev/null; "
                 "cat /sys/bus/iio/devices/iio:device1/buffer/length 2>&1"),
    ("FPGA HDL 版本", "cat /sys/kernel/debug/iio/iio:device0/* 2>/dev/null | head -3"),
    ("dmesg 关键", "dmesg 2>/dev/null | grep -iE 'dma|cf_axi|hdl|zynq|gem|eth' | head -10"),
]
for name, c in probes:
    W("\n### %s\n$ %s\n%s" % (name, c, cmd(c)))

f.close(); sp.close()
print("\n存到 %s" % OUT)
