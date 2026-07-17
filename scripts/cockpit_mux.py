"""Cockpit bridge mux — binary framing codec (shared, byte-for-byte identical).

COCKPIT_IN_LAB_BRIDGE_1 (b1, lead dispatch #12566). This module is the wire
format that multiplexes many HTTP requests (and, in Phase 2, ttyd websockets)
over ONE websocket between the Lab (brisen-lab, Render) and the laptop agent
(baker-master). It MUST be identical in both repos:

    brisen-lab/cockpit_mux.py            <- this file
    baker-master/scripts/cockpit_mux.py  <- byte-for-byte copy

Drift is caught by the shared test-vector file `cockpit_mux_vectors.json` (also
copied byte-for-byte into both repos): each side encodes the vectors and asserts
the exact hex bytes, so a one-sided change fails that side's test suite.

Frame layout (all integers big-endian, unsigned):

    +------------+--------+-----------+------------------+
    | stream_id  |  type  |  length   |   payload        |
    |   u32      |  u8    |   u32     |  <length> bytes  |
    +------------+--------+-----------+------------------+
       4 bytes    1 byte   4 bytes      length bytes

Header is 9 bytes. A stream_id identifies one logical request/response pair (or
one proxied websocket) and is allocated by the Lab side. Frame TYPES:

  OPEN (1)     — head frame. Payload = JSON. Lab->agent it is the REQUEST head
                 {method, path, query, headers}. agent->Lab (same stream_id) it
                 is the RESPONSE head {status, headers}. Direction disambiguates;
                 the enum stays exactly the 9 the brief specifies.
  DATA (2)     — a body chunk (request or response). Zero or more per stream.
  END  (3)     — end of a stream's body. Payload empty.
  RESET (4)    — abort a stream. Payload = optional JSON {reason}.
  WS_OPEN (5)  — Phase 2: open a proxied websocket. Payload = JSON
                 {path, headers, subprotocols}.
  WS_DATA (6)  — Phase 2: one ws message. Payload[0] = kind (0 text, 1 binary),
                 payload[1:] = the message bytes.
  WS_CLOSE (7) — Phase 2: close a proxied ws. Payload = optional JSON {code,reason}.
  PING (8)     — heartbeat. Payload empty.
  PONG (9)     — heartbeat reply. Payload empty.

Hard limit: a single frame payload is at most MAX_FRAME_PAYLOAD (256 KiB). The
encoder refuses to build a larger frame and the decoder refuses to accept a
declared length larger than that (OOM history on this service — bodies are
chunked into DATA frames, never buffered whole).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# --- constants --------------------------------------------------------------

HEADER_STRUCT = struct.Struct(">IBI")  # stream_id u32, type u8, length u32
HEADER_LEN = HEADER_STRUCT.size  # 9
MAX_FRAME_PAYLOAD = 256 * 1024  # 262144 bytes — hard cap, both directions

# Frame types (u8). Exactly the nine the brief specifies — do not add to this
# set without updating the brief + both repos + the vectors file.
OPEN = 1
DATA = 2
END = 3
RESET = 4
WS_OPEN = 5
WS_DATA = 6
WS_CLOSE = 7
PING = 8
PONG = 9

_VALID_TYPES = frozenset({OPEN, DATA, END, RESET, WS_OPEN, WS_DATA, WS_CLOSE, PING, PONG})

# WS_DATA kind byte (Phase 2).
WS_KIND_TEXT = 0
WS_KIND_BINARY = 1

_MAX_U32 = 0xFFFFFFFF


class MuxError(Exception):
    """Framing violation — malformed header, oversize frame, bad type."""


@dataclass(frozen=True)
class Frame:
    """One decoded mux frame."""

    stream_id: int
    type: int
    payload: bytes = b""


def encode_frame(stream_id: int, frame_type: int, payload: bytes = b"") -> bytes:
    """Serialize one frame to bytes. Raises MuxError on any contract breach.

    Refuses oversize payloads at build time so a caller cannot construct a frame
    the peer would reject on decode.
    """
    if not isinstance(stream_id, int) or stream_id < 0 or stream_id > _MAX_U32:
        raise MuxError(f"stream_id out of u32 range: {stream_id!r}")
    if frame_type not in _VALID_TYPES:
        raise MuxError(f"unknown frame type: {frame_type!r}")
    if not isinstance(payload, (bytes, bytearray)):
        raise MuxError(f"payload must be bytes, got {type(payload).__name__}")
    if len(payload) > MAX_FRAME_PAYLOAD:
        raise MuxError(
            f"frame payload {len(payload)} exceeds max {MAX_FRAME_PAYLOAD}"
        )
    return HEADER_STRUCT.pack(stream_id, frame_type, len(payload)) + bytes(payload)


def decode_frame(buf: bytes) -> tuple[Frame, int]:
    """Decode ONE frame from the front of `buf`.

    Returns (frame, bytes_consumed). Raises MuxError if the header is malformed
    or declares an oversize/incomplete payload. Callers that stream should first
    check `frame_available(buf)` or catch the "need more" signal via
    `try_decode_frame`.
    """
    frame, consumed = try_decode_frame(buf)
    if frame is None:
        raise MuxError("incomplete frame: need more bytes")
    return frame, consumed


def try_decode_frame(buf: bytes) -> tuple[Frame | None, int]:
    """Non-raising streaming decode of one frame from the front of `buf`.

    Returns (None, 0) when more bytes are needed to complete the current frame.
    Returns (Frame, bytes_consumed) once a whole frame is present. Raises
    MuxError only for UNRECOVERABLE violations (bad type, oversize declared
    length) — never for a merely-incomplete buffer.
    """
    if len(buf) < HEADER_LEN:
        return None, 0
    stream_id, frame_type, length = HEADER_STRUCT.unpack_from(buf, 0)
    if length > MAX_FRAME_PAYLOAD:
        raise MuxError(
            f"declared frame length {length} exceeds max {MAX_FRAME_PAYLOAD}"
        )
    if frame_type not in _VALID_TYPES:
        raise MuxError(f"unknown frame type on wire: {frame_type}")
    total = HEADER_LEN + length
    if len(buf) < total:
        return None, 0
    payload = bytes(buf[HEADER_LEN:total])
    return Frame(stream_id=stream_id, type=frame_type, payload=payload), total


def decode_stream(buf: bytes):
    """Yield every complete frame in `buf`, then return the unconsumed tail.

    Generator-style: iterate frames; the final `.tail` attribute pattern is
    avoided for simplicity — callers use `iter_frames` for that. Raises MuxError
    on an unrecoverable violation.
    """
    offset = 0
    n = len(buf)
    while offset < n:
        frame, consumed = try_decode_frame(buf[offset:])
        if frame is None:
            break
        offset += consumed
        yield frame


def iter_frames(buf: bytes) -> tuple[list[Frame], bytes]:
    """Decode all complete frames in `buf`; return (frames, leftover_bytes).

    The leftover is a (possibly empty) partial frame to be prepended to the next
    read. Raises MuxError on an unrecoverable violation.
    """
    frames: list[Frame] = []
    offset = 0
    n = len(buf)
    while offset < n:
        frame, consumed = try_decode_frame(buf[offset:])
        if frame is None:
            break
        frames.append(frame)
        offset += consumed
    return frames, bytes(buf[offset:])


# --- body chunking helpers --------------------------------------------------

def chunk_body(stream_id: int, body: bytes, *, chunk: int = MAX_FRAME_PAYLOAD):
    """Yield DATA frames splitting `body` into <=chunk pieces, then an END frame.

    Never buffers a whole large body into one frame — this is the anti-OOM path.
    An empty body yields just the END frame.
    """
    if chunk <= 0 or chunk > MAX_FRAME_PAYLOAD:
        chunk = MAX_FRAME_PAYLOAD
    for i in range(0, len(body), chunk):
        yield encode_frame(stream_id, DATA, body[i:i + chunk])
    yield encode_frame(stream_id, END, b"")
