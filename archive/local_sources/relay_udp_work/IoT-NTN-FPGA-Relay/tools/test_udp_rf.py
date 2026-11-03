"""Verify UDP RF_SET against independent AD9361 SPI readback; restore baseline."""
import argparse
import datetime
import json
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rk3588"))
from ccsds import APID_RF_SET, SpacePacket, enc_rf_set
from serial_port import SerialPort


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="169.254.9.10")
    ap.add_argument("--local-ip", default="")
    ap.add_argument("--interface-index", type=int)
    ap.add_argument("--serial", default="COM13")
    ap.add_argument("--offset-hz", type=int, default=1000000)
    ap.add_argument("--log", type=Path, default=Path("verification_logs/udp_rf_verified.json"))
    args = ap.parse_args()
    log = {"time": datetime.datetime.now().astimezone().isoformat(), "host": args.host,
           "serial": args.serial, "cases": [], "passed": False, "restored": False}
    sp = SerialPort(args.serial, 115200)
    baseline = None

    def uart(command):
        sp.write(command + "\r\n")
        data = bytearray()
        end = time.monotonic() + .35
        while time.monotonic() < end:
            data.extend(sp.read())
        text = data.decode("ascii", "replace")
        log.setdefault("uart", []).append({"command": command, "reply": text})
        return text

    def fields(text, prefix):
        lines = [s.strip() for s in text.splitlines() if s.strip().startswith(prefix)]
        if not lines:
            raise RuntimeError("Missing serial response: " + prefix)
        return dict(p.split("=", 1) for p in lines[-1].split()[1:])

    def read_radio():
        got = fields(uart("rfread"), "RFREAD ")
        if int(got["rx_rc"]) or int(got["tx_rc"]):
            raise RuntimeError("AD9361 readback failed: " + str(got))
        return int(got["rx_hz"]), int(got["tx_hz"])

    def packet(rx, tx, seq):
        return SpacePacket(APID_RF_SET, enc_rf_set(rx, tx, gain, att), seq=seq).pack()

    def case(name, payload, expected_rc, rx, tx, seq):
        row = {"name": name, "packet_hex": payload.hex(), "expected_rc": expected_rc}
        log["cases"].append(row)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            if args.local_ip:
                s.bind((args.local_ip, 0))
            if args.interface_index is not None:
                if sys.platform != "win32":
                    raise RuntimeError("--interface-index currently uses Windows IP_UNICAST_IF")
                s.setsockopt(socket.IPPROTO_IP, 31, socket.htonl(args.interface_index))
            s.settimeout(5)
            s.connect((args.host, 5005))
            start = time.monotonic()
            s.send(payload)
            reply = s.recv(512).decode("ascii")
            row.update(reply=reply.strip(), elapsed_ms=round((time.monotonic()-start)*1000, 2))
        got = dict(p.split("=", 1) for p in reply.split())
        actual = read_radio()
        row["spi_readback_hz"] = actual
        if int(got["rc"]) != expected_rc or int(got["seq"]) != seq:
            raise RuntimeError(name + ": unexpected UDP result: " + reply)
        for k, expected, hardware in zip(("rx_hz", "tx_hz"), (rx, tx), actual):
            if abs(int(got[k]) - expected) > 10000 or abs(hardware - expected) > 10000:
                raise RuntimeError(name + ": " + k + " did not match hardware readback")
        row["passed"] = True
        print(name, reply.strip(), "SPI=" + str(actual), flush=True)

    try:
        uart("auto 0")
        state = fields(uart("status"), "STAT ")
        gain, att = int(state["rxgain"]), int(state["txatt"])
        baseline = read_radio()
        rx, tx = baseline
        log["baseline"] = {"rx_hz": rx, "tx_hz": tx, "rx_gain_db": gain, "tx_attenuation_db": att}
        print("BASELINE", log["baseline"], flush=True)
        case("same_frequency", packet(rx, tx, 310), 0, rx, tx, 310)
        case("rx_only", packet(rx + args.offset_hz, tx, 311), 0,
             rx + args.offset_hz, tx, 311)
        case("tx_only", packet(rx + args.offset_hz, tx + args.offset_hz, 312), 0,
             rx + args.offset_hz, tx + args.offset_hz, 312)
        bad = bytearray(packet(rx, tx, 313))
        bad[-1] ^= 1
        case("reject_bad_crc", bytes(bad), -3,
             rx + args.offset_hz, tx + args.offset_hz, 0)
        case("reject_bad_length", packet(rx, tx, 314)[:-1], -1,
             rx + args.offset_hz, tx + args.offset_hz, 0)
        case("reject_out_of_range", packet(1, tx, 315), -4,
             rx + args.offset_hz, tx + args.offset_hz, 0)
        log["passed"] = True
    except Exception as exc:
        log["error"] = str(exc)
        print("FAILED", str(exc), flush=True)
    finally:
        if baseline is not None:
            try:
                case("restore_baseline", packet(*baseline, 316), 0, *baseline, 316)
                log["restored"] = True
            except Exception as exc:
                log["restore_error"] = str(exc)
                # This recovery does not count as a successful UDP test.
                if all(v % 1000000 == 0 for v in baseline):
                    try:
                        uart("lo %d %d" % tuple(v // 1000000 for v in baseline))
                        actual = read_radio()
                        log["restored"] = all(abs(a-b) <= 10000 for a,b in zip(actual, baseline))
                        log["recovery"] = "UART LO command"
                    except Exception as recovery_error:
                        log["recovery_error"] = str(recovery_error)
                log["passed"] = False
        uart("auto 1")
        sp.close()
        args.log.parent.mkdir(parents=True, exist_ok=True)
        args.log.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print("RESULT", "PASS" if log["passed"] and log["restored"] else "FAIL", flush=True)
    return 0 if log["passed"] and log["restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
