"""Serial monitor protocol; no hardware is opened by importing this module."""
from dataclasses import dataclass, field
import re


def decimal(text, name, minimum, maximum):
    # Deliberately reject whitespace, Unicode digits, signs and line endings.
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]{1,5}", text):
        raise ValueError(f"{name}须为ASCII十进制整数，范围 {minimum}–{maximum}")
    value = int(text)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name}范围为 {minimum}–{maximum}")
    return value


def command_bytes(action, values=()):
    simple = {"status", "help", "selftest", "arm on", "arm off", "waveformtest",
              "network on", "network off", "capture cancel", "decode", "auto on", "auto off"}
    if action in simple and not values:
        line = action
    elif action == "nettest" and len(values) == 5:
        limits = (("RX MHz", 70, 6000), ("TX MHz", 70, 6000),
                  ("SEQ", 0, 255), ("GAIN dB", 0, 76), ("ATT dB", 0, 89))
        numbers = [decimal(text, *limit) for text, limit in zip(values, limits)]
        line = "nettest " + " ".join(map(str, numbers))
    elif action == "capture" and len(values) == 3:
        mode, channel, k = values
        if mode not in ("training", "normal"):
            raise ValueError("采集模式须为training或normal")
        channel = decimal(channel, "CHANNEL", 0, 1)
        k = decimal(k, "K", 0, 3)
        line = f"capture {mode} {channel} {k}"
    else:
        raise ValueError("不支持的命令或参数")
    return (line + "\r\n").encode("ascii")


@dataclass
class BoardState:
    # Unknown until reported by the connected board; connecting is not a reset.
    network: int | None = None
    armed: int | None = None
    automatic: int | None = None
    capture_enabled: bool | None = None
    capture_state: int | None = None
    capture_valid: int | None = None
    counters: dict = field(default_factory=dict)
    origin: str = "UNKNOWN"
    last_result: str = "尚未收到板端执行结果"

    def receive(self, line):
        if line.startswith("BOOT ADDA "):
            if "capture=ENABLED" in line:
                self.capture_enabled = True
            elif "capture=DISABLED" in line:
                self.capture_enabled = False
        if line.startswith("CONTROLLER "):
            data = dict(re.findall(r"([a-z_]+)=([0-9]+)(?= |$)", line))
            required = {"auto", "capture_state", "capture_valid", "consumed"}
            if required <= data.keys() and data["auto"] in ("0", "1") and data["capture_valid"] in ("0", "1") and int(data["capture_state"]) <= 7:
                self.automatic = int(data["auto"])
                self.capture_state = int(data["capture_state"])
                self.capture_valid = int(data["capture_valid"])
        if line.startswith("CAPTURE "):
            match = re.fullmatch(r"CAPTURE state=([0-7]) valid=([01]) error=([A-Za-z0-9_]+) epoch=([0-9]+) copied_words=([0-9]+)", line)
            if match:
                self.capture_state, self.capture_valid = int(match[1]), int(match[2])
                self.last_result = f"采集阶段 {match[1]}，epoch={match[4]}，已复制 {match[5]} 字，error={match[3]}"
        if line.startswith("STATUS "):
            pairs = re.findall(r"(?:^| )([a-z]+)=([0-9]+)(?= |$)", line[7:])
            data = {key: int(value) for key, value in pairs}
            required = {"network", "armed", "decoded", "applied", "pending", "retries", "failures", "gain", "att"}
            if required <= data.keys() and data["network"] in (0, 1) and data["armed"] in (0, 1):
                self.network, self.armed = data["network"], data["armed"]
                self.counters = data
        elif line == "ADDA PS control core: network=OFF armed=OFF; selftest is local only":
            self.network, self.armed = 0, 0
            self.automatic, self.capture_state, self.capture_valid = None, None, None
            self.capture_enabled = None
            self.counters = {}
            self.origin = "UNKNOWN"
            self.last_result = "板端控制程序启动，等待状态查询"
        elif line == "ARMED only validated ADC_NORMAL may forward":
            self.armed = 1
        elif line == "DISARMED":
            self.armed = 0
        elif line.startswith("NETWORK_LOST"):
            self.network = 0
        elif line.startswith("NETWORK_OFF "):
            self.network, self.armed, self.automatic = 0, 0, 0
            self.last_result = "板端网络、自动模式及ARM已关闭"
        elif line.startswith("NETWORK_ON "):
            # Socket/netif creation alone does not establish a physical link.
            self.last_result = "板端网络已启动；点击读取状态确认链路可用性"
        elif line.startswith("NETWORK_INIT "):
            self.last_result = "板端正在初始化网络并等待PHY协商"
        elif line.startswith("AUTO_ON "):
            self.automatic, self.armed = 1, 1
            self.last_result = "自动采集与ARM已开启，仅有效ADC_NORMAL帧允许转发"
        elif line == "AUTO_OFF":
            self.automatic, self.armed = 0, 0
            self.last_result = "自动模式已停止，ARM已关闭"
        elif line.startswith("AUTO_STOP "):
            self.automatic = 0
            self.last_result = line
        match = re.search(r"(?:^| )source=(ADC_NORMAL|ADC_TEST|SYNTHETIC|UART_NETTEST)(?= |$)", line)
        if match:
            self.origin = match[1]
        if line.startswith("WAVEFORMTEST_PASS "):
            self.last_result = "合成波形解调自检通过；未发UDP，不代表真实ADC接收"
        elif line.startswith("WAVEFORMTEST_FAIL "):
            self.last_result = "合成波形解调自检失败"
        elif line.startswith("PATTERN_PASS "):
            self.last_result = "板端内部测试码快照检查通过；不代表模拟输入接收"
        elif line.startswith("PATTERN_FAIL "):
            self.last_result = "板端内部测试码快照检查失败"
        elif line.startswith("SELFTEST_PASS "):
            self.last_result = "内部数字帧自检通过；不代表真实ADC接收"
        elif line.startswith("SELFTEST_FAIL "):
            self.last_result = "内部自检失败"
        elif line.startswith("ACK "):
            rc = re.search(r"(?:^| )rc=(-?[0-9]+)(?= |$)", line)
            self.last_result = "板端报告匹配ACK，指令已确认" if rc and rc[1] == "0" else "ACK未通过板端校验"
        elif line.startswith("UDP_SEND_ATTEMPT "):
            self.last_result = "已尝试UDP发送，等待匹配ACK"
        elif line.startswith("DECODED "):
            self.last_result = "板端报告解出有效帧；尚不代表指令已转发或执行"
        elif line.startswith("LOCAL_ONLY "):
            self.last_result = "仅本地解码，未发RF_SET；查看来源与ARM状态"
        elif line.startswith(("ACK_TIMEOUT", "NETWORK_LOST", "ABORT ")):
            self.last_result = "未确认远端执行状态；查看日志"
        elif line.startswith(("COMMAND_REJECT", "NETWORK_NOT_READY", "CAPTURE_REJECT", "DECODE_ERROR")):
            self.last_result = line
        elif line == "DECODE_NO_VALID_FRAME":
            self.last_result = "本次捕获未解出有效帧"
        elif line.startswith("WAVEFORM_DECODE "):
            rc = re.search(r"(?:^| )rc=(-?[0-9]+)(?= |$)", line)
            if rc:
                self.last_result = ("本次波形未解出有效帧" if rc[1] == "0" else
                                    "波形解调有结果，继续查看帧校验与转发日志" if rc[1] == "1" else
                                    "波形解调失败，查看日志")
        elif line.startswith("CAPTURE_REQUEST "):
            rc = re.search(r"(?:^| )rc=(-?[0-9]+)(?= |$)", line)
            if rc:
                self.last_result = "采集请求已接受，等待板端完成" if rc[1] == "0" else "板端拒绝采集请求，查看日志"
        elif line.startswith("CLI_RESULT rc="):
            rc = re.fullmatch(r"CLI_RESULT rc=(-?[0-9]+)", line)
            if rc and rc[1] != "0":
                self.last_result = f"板端命令未成功，rc={rc[1]}；查看对应日志"


class LineBuffer:
    def __init__(self, limit=4096):
        self.limit = limit
        self.pending = bytearray()
        self.dropping = False

    def feed(self, chunk):
        output = []
        for byte in chunk:
            if byte in (10, 13):
                if self.pending:
                    output.append(self.pending.decode("utf-8", errors="replace"))
                self.pending.clear()
                self.dropping = False
            elif not self.dropping:
                self.pending.append(byte)
                if len(self.pending) > self.limit:
                    self.pending.clear()
                    self.dropping = True
                    output.append("[HOST] 串口单行过长，已丢弃该行至下一个换行")
        return output


def open_serial(factory, port, baudrate=115200):
    if not re.fullmatch(r"COM[1-9][0-9]{0,3}", port, re.ASCII):
        raise ValueError("请选择有效的Windows COM端口")
    if baudrate not in (9600, 57600, 115200, 230400):
        raise ValueError("不支持的波特率")
    serial = factory(port=None, baudrate=baudrate, bytesize=8, parity="N", stopbits=1,
                     timeout=0, write_timeout=0.5, xonxoff=False, rtscts=False, dsrdtr=False)
    try:
        serial.dtr = False
        serial.rts = False
        serial.port = port
        serial.open()
        return serial
    except Exception:
        serial.close()
        raise


class Session:
    def __init__(self):
        self.serial = None
        self.lines = LineBuffer()

    def connect(self, factory, port, baudrate):
        if self.serial is not None:
            raise RuntimeError("请先断开已有连接")
        self.serial = open_serial(factory, port, baudrate)
        self.lines = LineBuffer()
        # No reset, query, ARM, nettest, or any other write on connection.

    def close(self):
        serial, self.serial = self.serial, None
        self.lines = LineBuffer()
        if serial is not None:
            serial.close()

    def send(self, action, values=()):
        packet = command_bytes(action, values)
        if self.serial is None:
            raise RuntimeError("串口未连接")
        try:
            if self.serial.write(packet) != len(packet):
                raise OSError("串口仅写入部分命令，已断开；请检查板端状态")
        except Exception:
            self.close()
            raise
        return packet.decode("ascii").rstrip("\r\n")

    def poll(self):
        if self.serial is None:
            return []
        try:
            return self.lines.feed(self.serial.read(4096))
        except Exception:
            self.close()
            raise
