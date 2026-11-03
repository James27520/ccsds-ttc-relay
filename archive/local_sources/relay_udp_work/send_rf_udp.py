"""Send the existing CCSDS RF_SET space packet to the relay board."""

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "IoT-NTN-FPGA-Relay" / "rk3588"))
from ccsds import APID_RF_SET, SpacePacket, enc_rf_set  # noqa: E402


def send(host, port, rx_hz, tx_hz, seq, gain, attenuation):
    packet = SpacePacket(APID_RF_SET,
                         enc_rf_set(rx_hz, tx_hz, gain, attenuation),
                         seq=seq).pack()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3.0)
        sock.sendto(packet, (host, port))
        reply, source = sock.recvfrom(256)
    values = dict(item.split("=", 1) for item in reply.decode("ascii").split())
    print(f"{source[0]}:{source[1]} {reply.decode('ascii').strip()}")
    if (int(values["rc"]) != 0 or int(values["seq"]) != seq or
            abs(int(values["rx_hz"]) - rx_hz) > 10000 or
            abs(int(values["tx_hz"]) - tx_hz) > 10000):
        raise RuntimeError("RF_SET was rejected or readback did not match")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="169.254.9.10")
    parser.add_argument("--port", type=int, default=5005)
    parser.add_argument("--rx-mhz", type=int, default=900)
    parser.add_argument("--tx-mhz", type=int, default=1000)
    parser.add_argument("--gain-db", type=int, default=0)
    parser.add_argument("--attenuation-db", type=int, default=30)
    parser.add_argument("--seq", type=int, default=7)
    args = parser.parse_args()
    try:
        send(args.host, args.port, args.rx_mhz * 1000000,
             args.tx_mhz * 1000000, args.seq,
             args.gain_db, args.attenuation_db)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        parser.exit(1, f"RF_SET failed: {exc}\n")
