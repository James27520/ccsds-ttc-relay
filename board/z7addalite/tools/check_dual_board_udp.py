"""Exercise ADDA-origin UDP and independently read LDSDR PLLs through UART.

Requires the reviewed firmware on both boards and a direct Ethernet cable.
No PC UDP packets are sent. Leaves ADDA disarmed/network off and LDSDR muted.
"""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host_software" / "_packages"))
import serial
from serial.tools import list_ports


def fields(text, prefix):
    rows = [x.strip() for x in text.splitlines() if x.strip().startswith(prefix)]
    if not rows:
        raise RuntimeError("Missing response " + prefix + ": " + text[-500:])
    return dict(re.findall(r"(\w+)=(-?\d+)", rows[-1]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adda", required=True)
    ap.add_argument("--relay", required=True)
    ap.add_argument("--adda-usb-serial", default="210357A7D00EB")
    ap.add_argument("--relay-usb-serial", default="0ABC01B")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    if args.adda == args.relay:
        ap.error("Board UARTs must differ")
    inventory = {p.device: p.serial_number for p in list_ports.comports()}
    if inventory.get(args.adda) != args.adda_usb_serial or inventory.get(args.relay) != args.relay_usb_serial:
        ap.error("UART USB serial identity mismatch; inspect hardware before sending commands")
    if args.out.exists():
        ap.error("Output directory must be new")
    args.out.mkdir(parents=True)
    report = dict(time=datetime.datetime.now().astimezone().isoformat(),
                  origin="ADDA UART_NETTEST -> ADDA GEM0 -> LDSDR UDP5005",
                  analog_input_tested=False, cases=[], passed=False)
    ports, logs, buffers = {}, {}, {"adda": "", "relay": ""}
    events = []
    start = time.monotonic()
    cleanup_errors = []
    cleaning = False

    def pump(duration):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            for board, port in ports.items():
                try:
                    data = port.read(min(max(port.in_waiting, 1), 8192))
                except (serial.SerialException, OSError) as exc:
                    if not cleaning:
                        raise
                    message = board + " read: " + str(exc)
                    if message not in cleanup_errors:
                        cleanup_errors.append(message)
                    continue
                if data:
                    buffers[board] += data.decode("ascii", "replace")
                    try:
                        logs[board].write(data)
                        logs[board].flush()
                    except OSError as exc:
                        if not cleaning:
                            raise
                        message = board + " log: " + str(exc)
                        if message not in cleanup_errors:
                            cleanup_errors.append(message)
            time.sleep(.005)

    def command(board, text, wait=.45):
        pump(.05)
        mark = {b: len(v) for b, v in buffers.items()}
        ports[board].write(text.encode("ascii") + b"\r\n")
        events.append(dict(seconds=round(time.monotonic()-start, 3), board=board, command=text))
        pump(wait)
        return {b: buffers[b][mark[b]:] for b in buffers}

    def radio():
        v = fields(command("relay", "rfread")["relay"], "RFREAD ")
        if int(v["rx_rc"]) or int(v["tx_rc"]):
            raise RuntimeError("SPI PLL read failed")
        return [int(v["rx_hz"]), int(v["tx_hz"])]

    def status():
        return fields(command("adda", "status")["adda"], "STATUS ")

    def run_case(name, rx, tx, seq):
        before = int(status()["applied"])
        reply = command("adda", f"nettest {rx} {tx} {seq} 0 89", 2)
        expected = f"ACK source=UART_NETTEST rx={rx} tx={tx} air_seq={seq} rc=0"
        got = radio()
        after = status()
        state = fields(command("relay", "status")["relay"], "STAT ")
        ok = (expected in reply["adda"] and "UDP RF_SET rc=0" in reply["relay"]
              and int(after["applied"]) == before+1 and after["pending"] == "0"
              and all(abs(a-b*1000000) <= 10000 for a,b in zip(got, (rx,tx)))
              and state["mode"] == "2" and state["txatt"] == "89")
        report["cases"].append(dict(name=name, requested_mhz=[rx,tx], air_seq=seq,
                                    spi_hz=got, reply=reply, status=after,
                                    relay_state=state, passed=ok))
        print(name, "PASS" if ok else "FAIL", "SPI", got, flush=True)
        if not ok:
            raise RuntimeError("Case failed: " + name)

    baseline = None
    try:
        for board, name in (("adda",args.adda),("relay",args.relay)):
            p = serial.Serial(port=None, baudrate=115200, timeout=.01, write_timeout=1)
            p.dtr = p.rts = False
            p.port = name
            p.open()
            ports[board] = p
            logs[board] = (args.out / (board+".txt")).open("wb")
        command("relay", "auto 0")
        command("relay", "mode 2")
        command("relay", "txatt 89")
        rstate = fields(command("relay", "status")["relay"], "STAT ")
        if rstate["mode"] != "2" or rstate["txatt"] != "89":
            raise RuntimeError("Relay mute/attenuation precondition failed")
        got = radio()
        report["baseline_spi_hz"] = got
        base_mhz = [900, 1000]
        if any(abs(x-y*1000000)>10000 for x,y in zip(got,base_mhz)):
            raise RuntimeError("Expected reviewed baseline RX900/TX1000 MHz; no frequency tests run")
        baseline = got
        command("adda", "auto off")
        command("adda", "arm off")
        command("adda", "network on", 8)
        initial = status()
        report["initial_status"] = initial
        if initial["network"] != "1" or initial["armed"] != "0":
            raise RuntimeError("ADDA network/disarm precondition failed")
        rx, tx = base_mhz
        run_case("same_frequency", rx, tx, 40)
        run_case("rx_only", rx+1, tx, 41)
        run_case("tx_only", rx+1, tx+1, 42)
        command("adda", "network off")
        before = status()
        reply = command("adda", f"nettest {rx} {tx} 43 0 89", 1)
        after = status()
        got = radio()
        ok = ("NETWORK_NOT_READY" in reply["adda"] and "UDP RF_SET" not in reply["relay"]
              and after["applied"] == before["applied"] and after["pending"] == "0"
              and all(abs(a-b*1000000)<=10000 for a,b in zip(got,(rx+1,tx+1))))
        report["cases"].append(dict(name="network_off_reject", reply=reply, spi_hz=got, passed=ok))
        if not ok:
            raise RuntimeError("Network-off rejection failed")
        command("adda", "network on", 8)
        run_case("reenable_restore_baseline", rx, tx, 44)
        report["restored"] = True
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        print("ERROR", exc, flush=True)
    finally:
        cleaning = True

        def cleanup_step(label, action):
            try:
                return action()
            except Exception as exc:
                cleanup_errors.append(label + ": " + str(exc))
                return None

        if "adda" in ports:
            for text in ("network off", "arm off"):
                cleanup_step("adda " + text, lambda text=text: command("adda", text))
            state = cleanup_step("adda status", status)
            report["final_adda"] = state
            if not state or any(state.get(k) != "0" for k in ("network", "armed", "pending")):
                cleanup_errors.append("ADDA final network/disarm/pending state not confirmed")
        if "relay" in ports:
            for text in ("mode 2", "txatt 89", "auto 0"):
                cleanup_step("relay " + text, lambda text=text: command("relay", text))
            if baseline is not None and not report.get("restored"):
                cleanup_step("relay restore", lambda: command("relay", "lo 900 1000", 1))
                report["recovery"] = "UART, not counted as UDP success"
            got = cleanup_step("relay PLL readback", radio)
            report["final_spi_hz"] = got
            if baseline is not None:
                report["restored"] = got is not None and all(abs(a-b)<=10000 for a,b in zip(got,baseline))
                if not report["restored"]:
                    cleanup_errors.append("Relay baseline restoration not confirmed")
            state = cleanup_step("relay status", lambda: fields(command("relay", "status")["relay"], "STAT "))
            report["final_relay"] = state
            if not state or state.get("mode") != "2" or state.get("txatt") != "89":
                cleanup_errors.append("Relay mute/attenuation state not confirmed")
        for board, p in ports.items():
            cleanup_step(board + " close", p.close)
        for board, log in logs.items():
            cleanup_step(board + " log close", log.close)
        if cleanup_errors:
            report["cleanup_errors"] = cleanup_errors
            report["passed"] = False
        report["events"] = events
        (args.out/"result.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print("RESULT", "PASS" if report["passed"] else "FAIL", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
