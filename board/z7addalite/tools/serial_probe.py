"""Bounded serial log capture; only sends commands explicitly supplied by caller."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host_software" / "_packages"))
import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--send-after", type=float, default=2)
    parser.add_argument("--command-gap", type=float, default=2)
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.seconds <= 300 or args.send_after < 0 or args.command_gap < 0:
        parser.error("invalid time limits")
    if args.command and args.send_after + (len(args.command)-1)*args.command_gap >= args.seconds:
        parser.error("last command would be outside capture window")
    for command in args.command:
        if not command or len(command) > 127 or any(c in command for c in "\r\n\0"):
            parser.error("commands must each be a single nonempty line of at most 127 bytes")
        command.encode("ascii")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    port = serial.Serial(port=None, baudrate=args.baud, timeout=.1,
                         xonxoff=False, rtscts=False, dsrdtr=False, write_timeout=1)
    port.dtr = False
    port.rts = False
    port.port = args.port
    events = []
    received = bytearray()
    start = time.monotonic()
    sent = 0
    print(f"OPEN {args.port} {args.baud} DTR=0 RTS=0", flush=True)
    try:
        port.open()
        with args.log.open("wb") as log:
            while time.monotonic() - start < args.seconds:
                elapsed = time.monotonic() - start
                if sent < len(args.command) and elapsed >= args.send_after + sent*args.command_gap:
                    command = args.command[sent]
                    port.write(command.encode("ascii") + b"\r\n")
                    events.append(dict(seconds=elapsed, command=command))
                    print(f"TX {command}", flush=True)
                    sent += 1
                data = port.read(max(1, min(port.in_waiting, 4096)))
                if data:
                    log.write(data)
                    log.flush()
                    received.extend(data)
                    print(data.decode("utf-8", "replace"), end="", flush=True)
    finally:
        port.close()
    text = received.decode("utf-8", "replace")
    checks = {token: token in text for token in args.expect}
    metadata = dict(port=args.port, baud=args.baud, commands=events, received_bytes=len(received),
                    elapsed_seconds=time.monotonic()-start, expectations=checks)
    args.log.with_suffix(args.log.suffix + ".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print("\nSERIAL_CAPTURE " + json.dumps(metadata), flush=True)
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
