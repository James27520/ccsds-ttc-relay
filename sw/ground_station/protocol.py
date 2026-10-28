"""Small application envelope over the existing experimental RF text link.

Wire payload: ``G1:<8 lowercase hex session>:<4 lowercase hex sequence>:<body>``.
The body occupies 1..32 strict UTF-8 bytes. The outer RF frame, shaping,
carrier/timing search and CRC all remain owned by ``tools/rf_text_link.py``.
This module performs no hardware, serial-port or network operations.
"""
from collections import OrderedDict
import _imp
import importlib.util
from pathlib import Path
import re
import secrets
import sys


def _load_text_link():
    """Load the legacy standalone tool without leaving its sys.path edit behind.

    The tool imports ccsds_tm_tx by its standalone name and inserts its directory
    into sys.path. Hold Python's import lock while importing and restoring that
    list, including on failure. No caller-specific working directory or tools
    directory on sys.path is required.
    """
    name = "_ground_station_rf_text_link"
    _imp.acquire_lock()
    try:
        if name in sys.modules:
            return sys.modules[name]
        original_path = sys.path[:]
        try:
            path = Path(__file__).resolve().parents[1] / "tools" / "rf_text_link.py"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules.pop(name, None)
                raise
            return module
        finally:
            sys.path[:] = original_path
    finally:
        _imp.release_lock()


_link = _load_text_link()
MAX_TEXT_BYTES = 32
MAX_SEQUENCE = 0xFFFF
CAPTURE_SAMPLES = 32768
_SESSION = re.compile(r"[0-9a-f]{8}", re.ASCII)
_ENVELOPE = re.compile(r"G1:([0-9a-f]{8}):([0-9a-f]{4}):([\s\S]+)", re.ASCII)


def new_session_id():
    """Return a fresh random 32-bit session identifier for a sender instance."""
    return secrets.token_hex(4)


def _body_bytes(text):
    if not isinstance(text, str):
        raise ValueError("Message text must be a string")
    try:
        raw = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("Message text must be strict UTF-8") from exc
    if not 1 <= len(raw) <= MAX_TEXT_BYTES:
        raise ValueError("Message text must contain 1..32 UTF-8 bytes")
    return raw


def encode_message(text, session_id, sequence):
    """Return the canonical wire envelope; sequence overflow never wraps.

    After sequence 65535 the caller must start a fresh session before sending.
    Strings are preserved exactly; no whitespace stripping or normalization.
    """
    if not isinstance(session_id, str) or _SESSION.fullmatch(session_id) is None:
        raise ValueError("Session ID must be exactly 8 lowercase hexadecimal digits")
    if type(sequence) is not int or not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("Sequence must be an integer in 0..65535; start a new session on overflow")
    _body_bytes(text)
    return f"G1:{session_id}:{sequence:04x}:{text}"


def parse_message(payload_string):
    """Parse only a canonical G1 envelope, raising ValueError for other text."""
    if not isinstance(payload_string, str):
        raise ValueError("Payload must be a decoded UTF-8 string")
    match = _ENVELOPE.fullmatch(payload_string)
    if match is None:
        raise ValueError("Payload is not a canonical G1 application message")
    session_id, seq_hex, text = match.groups()
    raw = _body_bytes(text)
    return dict(message_id=f"{session_id}:{seq_hex}", session_id=session_id,
                sequence=int(seq_hex, 16), text=text, payload_bytes=len(raw))


def generate_message_iq(text, session_id, sequence, *, amplitude=.1,
                        sample_rate_hz=_link.FS, symbol_rate=_link.RS,
                        offset_hz=500_000, corrupt_crc=False):
    """Use the existing RF generator; the manifest is sender diagnostics only."""
    payload = encode_message(text, session_id, sequence)
    iq, manifest = _link.generate_iq(
        payload, amplitude=amplitude, sample_rate_hz=sample_rate_hz,
        symbol_rate=symbol_rate, offset_hz=offset_hz, corrupt_crc=corrupt_crc)
    manifest["application"] = parse_message(payload)
    manifest["application_protocol"] = "G1"
    return iq, manifest


def decode_capture(raw, expected_offset_hz=-250_000, *, sample_rate_hz=_link.FS,
                   symbol_rate=_link.RS, search_hz=20_000):
    """Blind-decode raw sign-extended 12-bit IQ and parse CRC-valid messages.

    There is intentionally no expected text, TX manifest or known-payload input.
    ``frames`` retains every result from the original decoder. ``messages``
    contains one entry per valid application frame, including cyclic repeats;
    the receiver owns cross-window duplicate tracking.
    """
    report = _link.decode(raw, sample_rate_hz=sample_rate_hz,
                          symbol_rate=symbol_rate,
                          expected_offset_hz=expected_offset_hz,
                          search_hz=search_hz)
    messages = []
    for index, frame in enumerate(report["frames"]):
        if not frame.get("crc_valid"):
            continue
        try:
            message = parse_message(frame["text"])
        except ValueError:
            continue
        message.update(frame_index=index,
                       first_symbol_sample=frame["first_symbol_sample"],
                       carrier_offset_hz=frame["carrier_offset_hz"],
                       crc16=frame["crc16"], crc_valid=True)
        messages.append(message)
    report["messages"] = messages
    report["valid_message_count"] = len(messages)
    return report


class MessageTracker:
    """Bounded LRU duplicate/conflict history across independent IQ windows.

    ``observe`` returns new, duplicate, or conflict. A conflicting body for an
    existing ID never replaces the first accepted body. Every observation
    refreshes that ID's recency. Once evicted, an ID may be reported new again.
    Callers should retain this object through receiver disconnect/reconnect.
    """

    def __init__(self, capacity=1024):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Tracker capacity must be a positive integer")
        self.capacity = capacity
        self._seen = OrderedDict()

    def observe(self, message):
        canonical = parse_message(encode_message(
            message["text"], message["session_id"], message["sequence"]))
        if any(message[key] != canonical[key] for key in canonical):
            raise ValueError("Message fields do not match the canonical envelope")
        key = canonical["message_id"]
        body = canonical["text"].encode("utf-8")
        if key in self._seen:
            status = "duplicate" if self._seen[key] == body else "conflict"
            self._seen.move_to_end(key)
            return status
        self._seen[key] = body
        if len(self._seen) > self.capacity:
            self._seen.popitem(last=False)
        return "new"

    def __len__(self):
        return len(self._seen)
