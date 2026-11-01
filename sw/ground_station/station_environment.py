"""Read-only desktop preflight. Never opens a serial port or configures a radio."""
import argparse
import importlib
import json
import os
import platform
import struct
import sys


def inspect_environment():
    report = dict(passed=True, python=sys.version.split()[0], executable=sys.executable,
                  platform=platform.platform(), bits=struct.calcsize('P')*8,
                  versions={}, errors=[], usb_ports=[], serial_ports_opened=False)
    if sys.version_info < (3, 11) or report['bits'] != 64:
        report['errors'].append('需要64位 Python 3.11或更新版本；推荐使用已验证的3.13。')
    for name in ('numpy', 'serial', 'tkinter'):
        try:
            module = importlib.import_module(name)
            report['versions'][name] = str(getattr(module, '__version__', getattr(module, 'TkVersion', 'installed')))
        except Exception as exc:
            report['errors'].append(f'{name} 无法加载：{exc}')
    if not report['errors']:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            try:
                root.update_idletasks()
            finally:
                root.destroy()
        except Exception as exc:
            report['errors'].append(f'图形环境无法启动：{exc}')
        try:
            from .terminal_radio import TerminalRadio
            report['receiver_binary_bytes'] = len(TerminalRadio.receiver_binary())
            report['receiver_binary_override'] = bool(os.environ.get('NTN_STREAM_RX'))
            if report['receiver_binary_override']:
                report['errors'].append('检测到NTN_STREAM_RX覆盖；双电脑演示请使用仓库随附的接收程序。')
        except Exception as exc:
            report['errors'].append(f'接收程序校验失败：{exc}')
        try:
            from serial.tools import list_ports
            report['usb_ports'] = [dict(port=p.device, description=p.description,
                vid=p.vid, pid=p.pid, serial=p.serial_number) for p in list_ports.comports() if p.vid is not None]
        except Exception as exc:
            report['errors'].append(f'USB串口枚举失败：{exc}')
    report['passed'] = not report['errors']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    report = inspect_environment()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not args.quiet or not report['passed']:
        print(f'Python {report["python"]} / {report["bits"]}位')
        print('程序环境检查通过。此检查没有连接板卡。' if report['passed'] else '程序环境检查失败：')
        for error in report['errors']:
            print('  '+error)
        for port in report['usb_ports']:
            print(f'  {port["port"]} · {port["description"]} · USB序号 {port["serial"] or "未提供"}')
        if report['passed'] and not report['usb_ports']:
            print('尚无USB串口。可先完成安装，再接板卡DEBUG口并检查FTDI VCP驱动。')
        if not report['passed']:
            print('请运行 setup_station.bat；详见 docs/two-computer-guide.md。')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
