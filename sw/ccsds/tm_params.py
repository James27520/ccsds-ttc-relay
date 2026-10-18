#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tm_params.py -- 遥测/遥控帧的【参数表定义】（演示工具与文档共用）

为什么要有这个
--------------
CCSDS 帧的数据域里装的不是自由文本，而是一张【事先定义好的参数表】：
  · 每个参数在数据域里的字节偏移、类型、量纲、比例因子都是定死的
  · 发端只填数值，收端按同一张表解析
自由文本那种属于数据注入，不是常规遥测/遥控。

本文件提供两套参数集（数据域都是 16 个 16 位参数 = 32 字节）：

  relay（默认） 转发板控制参数
      遥控板收到 CCSDS 帧 -> 解析出这些参数 -> 通过以太网下发给转发板
      转发板据此决定转发到哪个频段、多大带宽、多少增益…

  tm            卫星遥测参数
      传统的星上工程参数（电压/温度/姿态…）下行回地面

两套共用同一个帧格式（40 字节），只是数据域的含义不同。
"""
import struct

DATA_BYTES = 32
FMT_STRUCT = {"u8": "B", "i8": "b", "u16": "H", "i16": "h", "u32": "I", "i32": "i"}
FMT_SIZE = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4}


# ============================================================================
#  参数集 A：转发板控制参数（默认）—— 遥控板解析后下发给转发板
# ============================================================================
RELAY_PARAMS = [
    dict(name="转发使能",   off=0,  fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=1,     init=1,
         desc="0=停止转发 1=开始转发"),
    dict(name="工作模式",   off=2,  fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=3,     init=0,
         desc="0=透明转发 1=再生转发 2=解调-再调制 3=备份"),
    dict(name="目标频段",   off=4,  fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=6,     init=2,
         desc="0=L 1=S 2=C 3=X 4=Ku 5=K 6=Ka"),
    dict(name="目标频率低", off=6,  fmt="u16", scale=1.0,   unit="MHz", lo=0,   hi=65535, init=5785,
         desc="目标频率的整数部分 MHz（低 16 位），例如 5785 MHz"),
    dict(name="目标频率高", off=8,  fmt="u16", scale=1.0,   unit="MHz", lo=0,   hi=65535, init=0,
         desc="目标频率的整数部分 MHz（高 16 位），频率 = 高*65536 + 低"),
    dict(name="转发带宽",   off=10, fmt="u16", scale=1.0,   unit="kHz", lo=1,   hi=40000, init=1000,
         desc="转发通道带宽，1 kHz/LSB"),
    dict(name="发射增益",   off=12, fmt="i16", scale=0.1,   unit="dB",  lo=-400, hi=400,  init=100,
         desc="转发链路发射增益，0.1 dB/LSB"),
    dict(name="接收增益",   off=14, fmt="i16", scale=0.1,   unit="dB",  lo=-400, hi=600,  init=300,
         desc="转发链路接收增益，0.1 dB/LSB"),
    dict(name="通道选择",   off=16, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=3,     init=0,
         desc="0=CH1 1=CH2 2=CH1+CH2 3=备份"),
    dict(name="本振来源",   off=18, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=1,     init=0,
         desc="0=内部本振 1=外部参考"),
    dict(name="极化方式",   off=20, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=1,     init=0,
         desc="0=水平 1=垂直"),
    dict(name="衰减量",     off=22, fmt="u16", scale=0.1,   unit="dB",  lo=0,   hi=600,   init=200,
         desc="转发链路衰减，0.1 dB/LSB"),
    dict(name="增益控制",   off=24, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=1,     init=0,
         desc="0=手动增益 1=自动增益(AGC)"),
    dict(name="加密模式",   off=26, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=1,     init=0,
         desc="0=明传 1=加密"),
    dict(name="指令序号",   off=28, fmt="u16", scale=1.0,   unit="次",  lo=0,   hi=65535, init=1,
         desc="遥控指令序号，每发一条递增；转发板据此判重/判序"),
    dict(name="保留",       off=30, fmt="u16", scale=1.0,   unit="—",   lo=0,   hi=65535, init=0,
         desc="保留字段，填 0"),
]


# ============================================================================
#  参数集 B：卫星遥测参数 —— 传统星上工程参数下行
# ============================================================================
TM_PARAMS = [
    dict(name="母线电压",     off=0,  fmt="u16", scale=0.01,   unit="V",   lo=0,      hi=60000, init=2850,  desc="一次电源母线电压，0.01 V/LSB"),
    dict(name="母线电流",     off=2,  fmt="u16", scale=0.001,  unit="A",   lo=0,      hi=20000, init=1250,  desc="母线总电流，0.001 A/LSB"),
    dict(name="功放温度",     off=4,  fmt="i16", scale=0.1,    unit="℃",   lo=-1000,  hi=1500,  init=420,   desc="发射功放温度，0.1 ℃/LSB"),
    dict(name="接收电平",     off=6,  fmt="i16", scale=0.1,    unit="dBm", lo=-1200,  hi=0,     init=-750,  desc="上行接收电平，0.1 dBm/LSB"),
    dict(name="发射功率",     off=8,  fmt="u16", scale=0.01,   unit="W",   lo=0,      hi=10000, init=200,   desc="下行发射功率，0.01 W/LSB"),
    dict(name="姿态角X",      off=10, fmt="i16", scale=0.01,   unit="°",   lo=-18000, hi=18000, init=1234,  desc="滚动角，0.01 °/LSB"),
    dict(name="姿态角Y",      off=12, fmt="i16", scale=0.01,   unit="°",   lo=-18000, hi=18000, init=-567,  desc="俯仰角，0.01 °/LSB"),
    dict(name="姿态角Z",      off=14, fmt="i16", scale=0.01,   unit="°",   lo=-18000, hi=18000, init=890,   desc="偏航角，0.01 °/LSB"),
    dict(name="轨道高度",     off=16, fmt="u16", scale=1.0,    unit="km",  lo=0,      hi=2000,   init=500,   desc="轨道高度，1 km/LSB"),
    dict(name="电池电压",     off=18, fmt="u16", scale=0.001,  unit="V",   lo=0,      hi=30000, init=7400,  desc="蓄电池组电压，0.001 V/LSB"),
    dict(name="帆板电流",     off=20, fmt="u16", scale=0.001,  unit="A",   lo=0,      hi=20000, init=3200,  desc="太阳能帆板输出电流，0.001 A/LSB"),
    dict(name="工作模式",     off=22, fmt="u16", scale=1.0,    unit="—",   lo=0,      hi=15,     init=2,     desc="0=待机 1=初始化 2=正常 3=安全 4=测试"),
    dict(name="遥控指令计数", off=24, fmt="u16", scale=1.0,    unit="次",  lo=0,      hi=65535,  init=17,    desc="累计收到的有效遥控指令数"),
    dict(name="丢帧计数",     off=26, fmt="u16", scale=1.0,    unit="帧",  lo=0,      hi=65535,  init=0,     desc="地面统计的丢帧数"),
    dict(name="CRC错误计数",  off=28, fmt="u16", scale=1.0,    unit="次",  lo=0,      hi=65535,  init=0,     desc="累计 CRC 校验失败次数"),
    dict(name="时间戳低位",   off=30, fmt="u16", scale=1.0,    unit="—",   lo=0,      hi=65535,  init=0,     desc="帧时间戳低 16 位"),
]


PROFILES = {
    "relay": {"name": "转发板控制参数（遥控板解析后下发给转发板）", "params": RELAY_PARAMS},
    "tm":    {"name": "卫星遥测参数（星上工程参数下行）", "params": TM_PARAMS},
}

# 当前生效的参数集。默认用转发控制参数 —— 因为演示要展示的是
# "CCSDS 帧 -> 遥控板解析 -> 下发给转发板" 这条链路。
_ACTIVE = "relay"


def set_profile(key):
    global _ACTIVE
    if key in PROFILES:
        _ACTIVE = key
    return _ACTIVE


def get_profile():
    return _ACTIVE


def profile_name(key=None):
    return PROFILES[key or _ACTIVE]["name"]


# 兼容旧代码：PARAMS 始终指向当前生效的参数集
def _p():
    return PROFILES[_ACTIVE]["params"]


class _ParamsProxy(object):
    """让 PARAMS 这个名字始终反映当前参数集（旧代码直接遍历 PARAMS）"""
    def __iter__(self):
        return iter(_p())

    def __len__(self):
        return len(_p())

    def __getitem__(self, i):
        return _p()[i]


PARAMS = _ParamsProxy()


def clamp(p, raw):
    """把界面输入的原始值夹到允许范围内"""
    try:
        v = int(round(float(raw)))
    except Exception:
        v = p["init"]
    return max(p["lo"], min(p["hi"], v))


def build_data_block(values=None, profile=None):
    """
    values: dict {参数名: 原始值} 或 None（用默认值）
    profile: 指定参数集('relay'/'tm')，默认用当前生效的
    返回 32 字节数据域
    """
    ps = PROFILES[profile]["params"] if profile else _p()
    buf = bytearray(DATA_BYTES)
    for p in ps:
        raw = p["init"] if values is None else clamp(p, values.get(p["name"], p["init"]))
        struct.pack_into("<" + FMT_STRUCT[p["fmt"]], buf, p["off"], raw)
    return bytes(buf)


def parse_data_block(data, profile=None):
    """data: 32 字节数据域 -> [(参数定义, 原始值, 工程值), ...]"""
    ps = PROFILES[profile]["params"] if profile else _p()
    out = []
    for p in ps:
        try:
            raw = struct.unpack_from("<" + FMT_STRUCT[p["fmt"]], data, p["off"])[0]
        except Exception:
            raw = 0
        out.append((p, raw, raw * p["scale"]))
    return out


def format_eng(p, raw):
    """把原始值格式化成工程值字符串（按 scale 决定小数位）"""
    v = raw * p["scale"]
    s = p["scale"]
    if s >= 1:
        return "%.0f %s" % (v, p["unit"])
    txt = "%g" % s
    nd = len(txt.split(".")[1]) if "." in txt else 0
    return "%.*f %s" % (nd, v, p["unit"])


def relay_freq_mhz(vals):
    """转发目标的实际频率 = 高16位*65536 + 低16位"""
    lo = vals.get("目标频率低", 0)
    hi = vals.get("目标频率高", 0)
    return hi * 65536 + lo


if __name__ == "__main__":
    for key in ("relay", "tm"):
        set_profile(key)
        print("=" * 78)
        print("  参数集 %s : %s" % (key, profile_name()))
        print("=" * 78)
        print("  %-14s %-4s %-5s %-8s %-8s %s" % ("参数名", "偏移", "类型", "比例", "单位", "默认工程值"))
        tot = 0
        for p in _p():
            tot += FMT_SIZE[p["fmt"]]
            print("  %-14s %-4d %-5s %-8g %-8s %s"
                  % (p["name"], p["off"], p["fmt"], p["scale"], p["unit"],
                     format_eng(p, p["init"])))
        print("  合计 %d 字节 %s" % (tot, "OK" if tot == DATA_BYTES else "★不一致"))
        d = build_data_block()
        print("  数据域 (%d B): %s" % (len(d), d.hex()))
        print()
    set_profile("relay")
    print("  转发控制参数往返解析检查:")
    d = build_data_block()
    for p, raw, eng in parse_data_block(d):
        print("    %-14s raw=%-7d  %s" % (p["name"], raw, format_eng(p, raw)))
    print("    目标频率 = %d MHz" % relay_freq_mhz({p["name"]: p["init"] for p in RELAY_PARAMS}))
