"""Host IQ acceptance tests; receiver never receives expected text/manifest."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sw"))
from tools import rf_text_link as link


def run(executable, raw, directory, name, success=True):
    prefix = directory / name
    started = time.perf_counter()
    result = subprocess.run([str(executable), str(prefix), "--stdio"], input=raw,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    elapsed = time.perf_counter() - started
    assert (result.returncode == 0) == success, result.stderr.decode()
    status = json.loads(prefix.with_suffix(".status.json").read_text())
    messages = json.loads(prefix.with_suffix(".messages.json").read_text())
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(messages) <= 128
    assert events[-1]["type"] == "status"
    assert status["samples"] == len(raw) // 4 or not success
    return status, messages, elapsed


def iq(text, *, offset=-250_000, corrupt=False):
    data, _ = link.generate_iq(text, amplitude=.8, offset_hz=offset,
                               corrupt_crc=corrupt)
    return np.rint(data.astype(float)/16).astype("<i2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--capture-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    executable = args.executable.resolve()
    report = {}
    with tempfile.TemporaryDirectory(prefix="stream_rx_test_") as d:
        directory = Path(d)
        # A maximum-size G1 frame, separated by gaps and crossing the 32768 decimated
        # sample boundary, requires overlap to be recovered in full.
        payload = "G1:a1b2c3d4:0010:" + "boundary 中文"
        data = iq(payload)
        longest = "G1:a1b2c3d4:0011:" + "x" * 32
        assert len(longest.encode()) == 49
        combined = np.concatenate([np.zeros((160_000, 2), dtype="<i2"),
                                   iq(longest), np.tile(data, (8, 1))])
        z = (combined[:, 0] + 1j*combined[:, 1])*np.exp(2j*np.pi*250*np.arange(len(combined))/2_500_000)
        raw = np.rint(np.column_stack([z.real, z.imag])).astype("<i2").tobytes()
        status, messages, elapsed = run(executable, raw, directory, "synthetic")
        recovered = {bytes.fromhex(m["payload_hex"]).decode() for m in messages}
        assert {payload, longest} <= recovered, (status, messages)
        assert status["frames"] > len(messages)
        assert all(m["crc_valid"] for m in messages)
        report["synthetic"] = dict(status=status, elapsed_s=elapsed,
                                    input_duration_s=len(raw)/4/2_500_000)
        # No original, manifest, or reference payload is supplied to receiver.
        corrupt = np.tile(iq("G1:a1b2c3d4:0002:reject", corrupt=True), (30, 1)).tobytes()
        status, messages, _ = run(executable, corrupt, directory, "bad_crc")
        assert not messages and status["frames"] == 0 and status["rejects"] > 0
        report["bad_crc"] = status
        status, messages, _ = run(executable, np.tile(iq(longest + "x"), (12, 1)).tobytes(), directory, "over_g1_limit")
        assert not messages
        # Bounded history and valid JSON publication with many distinct frames.
        blocks = [np.tile(iq(f"G1:01234567:{n:04x}:message-{n}"), (3, 1))
                  for n in range(135)]
        status, messages, elapsed = run(executable, np.concatenate(blocks).tobytes(), directory, "bounded")
        assert len(messages) == 128, (status, len(messages))
        assert len({m["payload_hex"] for m in messages}) == 128
        report["bounded"] = dict(status=status, elapsed_s=elapsed)
        status, messages, _ = run(executable, b"\0\0\0", directory, "truncated", success=False)
        assert not messages
        run(executable, np.array([[32767, 0]], dtype="<i2").tobytes(), directory, "wrong_format", success=False)
        rng = np.random.default_rng(13)
        status, messages, _ = run(executable, rng.integers(-10, 11, (170000, 2), dtype=np.int16).astype("<i2").tobytes(), directory, "noise")
        assert not messages and status["frames"] == 0
        report["noise"] = status
        levels = np.zeros((1_300_000, 2), dtype="<i2")
        levels[-110_000:, 0] = 1500
        levels[-1, 1] = -2048
        status, messages, _ = run(executable, levels.tobytes(), directory, "level_step")
        assert status["rms"] < 1000 < status["recent_rms"]
        assert status["clips"] == status["recent_clips"] == 1
        assert abs(status["rms"] - np.sqrt(np.mean(np.sum(levels.astype(float)**2, axis=1)))) < 1e-5
        report["level_step"] = status
        if args.capture_dir:
            for capture in sorted(args.capture_dir.glob("terminal*/rx_both_on.bin")):
                raw = capture.read_bytes()
                # Compare recovered payload to the existing Python algorithm
                # on raw IQ, without reading prior result/manifest files.
                reference = link.decode(raw[:32768*4])
                expected = {f["payload_hex"] for f in reference["frames"]}
                status, messages, elapsed = run(executable, raw, directory, capture.parent.name)
                actual = {m["payload_hex"] for m in messages}
                assert expected and expected <= actual, (capture, expected, actual, status)
                report[capture.parent.name] = dict(status=status, elapsed_s=elapsed,
                    input_duration_s=len(raw)/4/2_500_000,
                    reference_payloads=sorted(expected), recovered_payloads=sorted(actual))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
