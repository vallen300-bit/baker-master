"""Frame-codec tests for the cockpit bridge mux (baker-master / agent side).

COCKPIT_IN_LAB_BRIDGE_1 — the codec `scripts/cockpit_mux.py` and the vectors
`scripts/cockpit_mux_vectors.json` are BYTE-FOR-BYTE copies of the brisen-lab
originals. This test encodes the shared vectors and asserts the exact bytes, so
if either repo's codec drifts, that repo's suite fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
_spec = importlib.util.spec_from_file_location("cockpit_mux", os.path.join(_SCRIPTS, "cockpit_mux.py"))
m = importlib.util.module_from_spec(_spec)
# Register before exec so the frozen dataclass can resolve its own __module__
# (importlib module_from_spec + `from __future__ import annotations`).
sys.modules["cockpit_mux"] = m
_spec.loader.exec_module(m)

_VECTORS_PATH = os.path.join(_SCRIPTS, "cockpit_mux_vectors.json")


def _load_vectors():
    with open(_VECTORS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_vectors_encode_to_exact_bytes():
    doc = _load_vectors()
    assert doc["header_len"] == m.HEADER_LEN
    assert doc["max_frame_payload"] == m.MAX_FRAME_PAYLOAD
    for v in doc["vectors"]:
        payload = bytes.fromhex(v["payload_hex"])
        encoded = m.encode_frame(v["stream_id"], v["type"], payload)
        assert encoded.hex() == v["encoded_hex"], f"drift on vector {v['name']}"


def test_vectors_decode_round_trip():
    for v in _load_vectors()["vectors"]:
        raw = bytes.fromhex(v["encoded_hex"])
        frame, consumed = m.decode_frame(raw)
        assert consumed == len(raw)
        assert frame.stream_id == v["stream_id"]
        assert frame.type == v["type"]
        assert frame.payload == bytes.fromhex(v["payload_hex"])


@pytest.mark.parametrize("ftype", [m.OPEN, m.DATA, m.END, m.RESET, m.WS_OPEN, m.WS_DATA, m.WS_CLOSE, m.PING, m.PONG])
def test_encode_decode_round_trip(ftype):
    payload = b"" if ftype in (m.END, m.PING, m.PONG) else b"payload-\x00\xff-bytes"
    enc = m.encode_frame(42, ftype, payload)
    frame, consumed = m.decode_frame(enc)
    assert consumed == len(enc)
    assert frame == m.Frame(stream_id=42, type=ftype, payload=payload)


def test_interleaved_streams_decode_in_order():
    buf = b"".join([
        m.encode_frame(1, m.OPEN, b'{"method":"GET"}'),
        m.encode_frame(2, m.DATA, b"b1"),
        m.encode_frame(1, m.END),
    ])
    frames, leftover = m.iter_frames(buf)
    assert leftover == b""
    assert [(f.stream_id, f.type) for f in frames] == [(1, m.OPEN), (2, m.DATA), (1, m.END)]


def test_encode_rejects_oversize_payload():
    with pytest.raises(m.MuxError):
        m.encode_frame(1, m.DATA, b"x" * (m.MAX_FRAME_PAYLOAD + 1))


def test_decode_rejects_oversize_declared_length():
    bad = m.HEADER_STRUCT.pack(1, m.DATA, m.MAX_FRAME_PAYLOAD + 1)
    with pytest.raises(m.MuxError):
        m.try_decode_frame(bad + b"\x00")


def test_decode_rejects_unknown_type():
    with pytest.raises(m.MuxError):
        m.try_decode_frame(m.HEADER_STRUCT.pack(1, 200, 0))
