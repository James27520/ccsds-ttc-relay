#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serial_port.py -- 跨平台串口，纯标准库，零依赖

  Linux  : termios + os.open + select
  Windows: ctypes 调 kernel32（无需 pyserial）

统一接口：
    sp = SerialPort("/dev/ttyUSB1", 115200)      # Linux
    sp = SerialPort("COM5", 115200)              # Windows
    sp.write("status\\r\\n")
    data = sp.read()          # 非阻塞，返回 bytes（可能为空）
    sp.close()

    for name in list_ports(): ...
"""

import os
import sys
import time

IS_WIN = (os.name == "nt")


# =====================================================================
#  Linux / POSIX
# =====================================================================
if not IS_WIN:
    import select
    import termios

    _BAUD = {
        9600: termios.B9600, 19200: termios.B19200, 38400: termios.B38400,
        57600: termios.B57600, 115200: termios.B115200, 230400: termios.B230400,
        460800: termios.B460800, 500000: termios.B500000, 576000: termios.B576000,
        921600: termios.B921600, 1000000: termios.B1000000,
        1500000: termios.B1500000, 2000000: termios.B2000000,
        3000000: getattr(termios, "B3000000", termios.B2000000),
    }

    class SerialPort(object):
        def __init__(self, port, baud=115200, timeout=0.05):
            self.port = port
            try:
                self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            except OSError as e:
                raise OSError("cannot open %s: %s" % (port, e))
            try:
                self._setup(baud, timeout)
            except Exception:
                self.close()
                raise
            self._rx = b""

        def _setup(self, baud, timeout):
            if baud not in _BAUD:
                raise OSError("unsupported baud %d (add it to _BAUD)" % baud)
            a = termios.tcgetattr(self.fd)
                # iflag oflag cflag lflag ispeed ospeed
            a[0] = termios.IGNPAR
            a[1] = termios.OPOST
            a[2] = (termios.CS8 | termios.CREAD | termios.CLOCAL)
            a[3] = 0
            a[4] = a[5] = _BAUD[baud]
            a[6][termios.VMIN] = 0
            a[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, a)
            termios.tcflush(self.fd, termios.TCIOFLUSH)

        def write(self, data):
            if isinstance(data, str):
                data = data.encode("ascii", "replace")
            os.write(self.fd, data)
            return len(data)

        def read(self, n=4096):
            """非阻塞读；内部按 timeout 短等待一次，避免上层忙等。"""
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if not r:
                return b""
            try:
                return os.read(self.fd, n)
            except OSError:
                return b""

        def readline(self, timeout=1.0):
            """读一行（以 \\n 结尾），超时返回已收到的内容。"""
            t0 = time.time()
            while b"\n" not in self._rx:
                if time.time() - t0 > timeout:
                    break
                d = self.read()
                if d:
                    self._rx += d
            if b"\n" in self._rx:
                ln, self._rx = self._rx.split(b"\n", 1)
                return ln
            return b""

        def flush(self):
            termios.tcflush(self.fd, termios.TCIOFLUSH)

        def close(self):
            if getattr(self, "fd", None) is not None:
                try:
                    os.close(self.fd)
                except OSError:
                    pass
                self.fd = None

    def list_ports():
        """列出 /dev/ttyUSB* /dev/ttyACM* /dev/ttyS*（按名字排序）。"""
        out = []
        for pat in ("ttyUSB", "ttyACM", "ttyS"):
            try:
                for n in os.listdir("/dev"):
                    if n.startswith(pat) and n[len(pat):].isdigit():
                        out.append("/dev/" + n)
            except OSError:
                pass
        return sorted(set(out), key=lambda s: (len(s), s))


# =====================================================================
#  Windows
# =====================================================================
else:
    import ctypes
    import ctypes.wintypes as wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    PURGE_RXCLEAR = 0x0008
    PURGE_TXCLEAR = 0x0004

    class _DCB(ctypes.Structure):
        _fields_ = [
            ("DCBlength", wt.DWORD), ("BaudRate", wt.DWORD),
            ("fBinary", wt.DWORD, 1), ("fParity", wt.DWORD, 1),
            ("fOutxCtsFlow", wt.DWORD, 1), ("fOutxDsrFlow", wt.DWORD, 1),
            ("fDtrControl", wt.DWORD, 2), ("fDsrSensitivity", wt.DWORD, 1),
            ("fTXContinueOnXoff", wt.DWORD, 1), ("fOutX", wt.DWORD, 1),
            ("fInX", wt.DWORD, 1), ("fErrorChar", wt.DWORD, 1),
            ("fNull", wt.DWORD, 1), ("fRtsControl", wt.DWORD, 2),
            ("fAbortOnError", wt.DWORD, 1), ("fDummy2", wt.DWORD, 17),
            ("wReserved", wt.WORD), ("XonLim", wt.WORD), ("XoffLim", wt.WORD),
            ("ByteSize", wt.BYTE), ("Parity", wt.BYTE), ("StopBits", wt.BYTE),
            ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
            ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char),
            ("EvtChar", ctypes.c_char), ("wReserved1", wt.WORD),
        ]

    class _TIMEOUTS(ctypes.Structure):
        _fields_ = [("ReadIntervalTimeout", wt.DWORD),
                    ("ReadTotalTimeoutMultiplier", wt.DWORD),
                    ("ReadTotalTimeoutConstant", wt.DWORD),
                    ("WriteTotalTimeoutMultiplier", wt.DWORD),
                    ("WriteTotalTimeoutConstant", wt.DWORD)]

    _k32.CreateFileW.restype = wt.HANDLE
    _k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD,
                                 ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    _k32.SetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(_DCB)]
    _k32.GetCommState.argtypes = [wt.HANDLE, ctypes.POINTER(_DCB)]
    _k32.SetCommTimeouts.argtypes = [wt.HANDLE, ctypes.POINTER(_TIMEOUTS)]
    _k32.PurgeComm.argtypes = [wt.HANDLE, wt.DWORD]
    _k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                              ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    _k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD,
                               ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    _k32.CloseHandle.argtypes = [wt.HANDLE]

    class SerialPort(object):
        def __init__(self, port, baud=115200, timeout=0.05):
            self.port = port
            self.h = _k32.CreateFileW("\\\\.\\" + port,
                                      GENERIC_READ | GENERIC_WRITE,
                                      0, None, OPEN_EXISTING, 0, None)
            if self.h == INVALID_HANDLE_VALUE or not self.h:
                raise OSError("cannot open %s (err %d)"
                              % (port, ctypes.get_last_error()))
            dcb = _DCB()
            dcb.DCBlength = ctypes.sizeof(_DCB)
            if not _k32.GetCommState(self.h, ctypes.byref(dcb)):
                self.close()
                raise OSError("GetCommState failed")
            dcb.BaudRate = baud
            dcb.ByteSize, dcb.Parity, dcb.StopBits = 8, 0, 0
            dcb.fBinary, dcb.fParity = 1, 0
            dcb.fOutxCtsFlow = dcb.fOutxDsrFlow = 0
            dcb.fDtrControl = 1
            dcb.fDsrSensitivity = 0
            dcb.fOutX = dcb.fInX = 0
            dcb.fRtsControl = 1
            dcb.fAbortOnError = 0
            if not _k32.SetCommState(self.h, ctypes.byref(dcb)):
                self.close()
                raise OSError("SetCommState failed (baud %d)" % baud)
            to = _TIMEOUTS(0, 0, int(timeout * 1000), 0, int(timeout * 1000))
            _k32.SetCommTimeouts(self.h, ctypes.byref(to))
            _k32.PurgeComm(self.h, PURGE_RXCLEAR | PURGE_TXCLEAR)
            self._rx = b""

        def write(self, data):
            if isinstance(data, str):
                data = data.encode("ascii", "replace")
            n = wt.DWORD(0)
            buf = ctypes.create_string_buffer(data, len(data))
            _k32.WriteFile(self.h, buf, len(data), ctypes.byref(n), None)
            return n.value

        def read(self, n=4096):
            buf = ctypes.create_string_buffer(n)
            got = wt.DWORD(0)
            _k32.ReadFile(self.h, buf, n, ctypes.byref(got), None)
            return buf.raw[:got.value]

        def readline(self, timeout=1.0):
            t0 = time.time()
            while b"\n" not in self._rx:
                if time.time() - t0 > timeout:
                    break
                d = self.read()
                if d:
                    self._rx += d
            if b"\n" in self._rx:
                ln, self._rx = self._rx.split(b"\n", 1)
                return ln
            return b""

        def flush(self):
            _k32.PurgeComm(self.h, PURGE_RXCLEAR | PURGE_TXCLEAR)

        def close(self):
            if getattr(self, "h", None):
                _k32.CloseHandle(self.h)
                self.h = None

    def list_ports():
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"HARDWARE\DEVICEMAP\SERIALCOMM")
            out, i = [], 0
            while True:
                try:
                    _n, val, _t = winreg.EnumValue(key, i)
                    out.append(val)
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
            return sorted(set(out), key=lambda s: (len(s), s))
        except Exception:
            return ["COM%d" % n for n in range(1, 33)]


# =====================================================================
def probe_payload(port, baud=115200, timeout=1.5, quiet=True):
    """打开 port 发 status，收到 STAT 就认为找到了载荷。返回 True/False。"""
    try:
        sp = SerialPort(port, baud)
    except OSError:
        return False
    try:
        time.sleep(0.2)
        sp.read()
        sp.write("auto 0\r\n")
        time.sleep(0.2)
        sp.read()
        for _ in range(3):
            sp.write("status\r\n")
            t0 = time.time()
            acc = b""
            while time.time() - t0 < timeout:
                acc += sp.read()
                if b"STAT" in acc:
                    return True
                time.sleep(0.05)
        return False
    finally:
        sp.close()


def autodetect(baud=115200, verbose=False):
    for p in list_ports():
        if verbose:
            print("  探测 %s ..." % p)
        if probe_payload(p, baud):
            return p
    return None


if __name__ == "__main__":
    print("平台:", "Windows" if IS_WIN else "POSIX")
    print("可用串口:", ", ".join(list_ports()) or "(无)")
    if len(sys.argv) > 1:
        port = sys.argv[1]
        print("探测 %s ..." % port, "OK" if probe_payload(port, verbose=True) else "无响应")
