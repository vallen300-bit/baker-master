"""WAKE_INJECT_SUBMIT_FIX_2 D4 — PTY-level regression for the composer submit rule.

Encodes the finding established (with live pane captures) in
briefs/_reports/COMPOSER_RESIDUAL_DIAG_20260718.md and proves the wake
injection write pattern submits under it:

  * a newline delivered INSIDE an xterm bracketed paste (ESC[200~ … ESC[201~)
    is literal and PARKS — it never submits;
  * a carriage return delivered as its OWN PTY write SUBMITS.

The bytes traverse a real kernel PTY (``pty.openpty`` in raw mode, so no line
discipline rewrites CR/NL) and are interpreted by ``ComposerModel``, a minimal
model of the two rules above. This is a MODEL of the composer, not the live
Claude TUI — the live behaviour is confirmed by the post-deploy AC on a real
seat. What this test guarantees hermetically: the write pattern produced by
``cockpit_controller.wake_inject_writes`` submits, and a regression that coalesces
text+newline (or wraps it in a bracketed paste) goes red.
"""
from __future__ import annotations

import os
import pty
import tty

import pytest

from scripts import cockpit_controller as controller

ESC = b"\x1b"
PASTE_START = ESC + b"[200~"
PASTE_END = ESC + b"[201~"


class ComposerModel:
    """Minimal model of the Claude Code composer's submit semantics.

    Feeds raw PTY bytes. Tracks a bracketed-paste envelope; a CR (0x0D) is a
    submit ONLY when it arrives outside a paste envelope. Everything else — text,
    and any newline/CR inside a paste — is appended to the pending buffer.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.submitted: list[str] = []
        self._in_paste = False
        self._pending = b""

    def feed(self, data: bytes) -> None:
        self._pending += data
        while self._pending:
            if not self._in_paste and self._pending.startswith(PASTE_START):
                self._in_paste = True
                self._pending = self._pending[len(PASTE_START):]
                continue
            if self._in_paste and self._pending.startswith(PASTE_END):
                self._in_paste = False
                self._pending = self._pending[len(PASTE_END):]
                continue
            # Could a paste marker still be forming at the tail? If a strict
            # prefix of a marker is all that remains, wait for more bytes.
            if self._is_partial_marker(self._pending):
                return
            byte, self._pending = self._pending[:1], self._pending[1:]
            if byte == b"\r" and not self._in_paste:
                self.submitted.append(self.buffer)
                self.buffer = ""
            else:
                self.buffer += byte.decode("utf-8", errors="replace")

    @staticmethod
    def _is_partial_marker(pending: bytes) -> bool:
        for marker in (PASTE_START, PASTE_END):
            for n in range(1, len(marker)):
                if pending == marker[:n]:
                    return True
        return False


def _drive_through_pty(writes: list[bytes]) -> ComposerModel:
    """Write each element as its own PTY master write; read everything on the
    slave (raw mode) and feed it to a fresh ComposerModel."""
    master, slave = pty.openpty()
    tty.setraw(slave)
    model = ComposerModel()
    try:
        for chunk in writes:
            os.write(master, chunk)
        # Drain the slave without blocking past what we wrote.
        os.set_blocking(slave, False)
        while True:
            try:
                data = os.read(slave, 4096)
            except BlockingIOError:
                break
            if not data:
                break
            model.feed(data)
    finally:
        os.close(master)
        os.close(slave)
    return model


def test_bracketed_paste_newline_parks():
    """The bug: text + trailing newline wrapped in a bracketed paste, no separate
    CR — the newline is literal, nothing submits, the line parks."""
    payload = PASTE_START + b"check bus #7 topic\n" + PASTE_END
    model = _drive_through_pty([payload])
    assert model.submitted == []            # parked — nothing submitted
    assert "check bus #7 topic" in model.buffer


def test_separate_bare_cr_submits():
    """The recovery / correct pattern: text, then a bare CR as its OWN write."""
    model = _drive_through_pty([b"check bus #7 topic", b"\r"])
    assert model.submitted == ["check bus #7 topic"]
    assert model.buffer == ""


def test_wake_inject_writes_pattern_submits():
    """AC4 green: the exact writes cockpit_controller.wake_inject_writes produces
    submit under the composer model."""
    writes = controller.wake_inject_writes("[wake] check bus #7 topic")
    byte_writes = []
    for kind, data in writes:
        assert kind in ("literal", "cr")
        byte_writes.append(data.encode("utf-8"))
    model = _drive_through_pty(byte_writes)
    assert model.submitted == ["[wake] check bus #7 topic"]


def test_coalesced_newline_in_paste_is_the_regression_guard():
    """AC4 red: if a future change were to deliver the wake line as a single
    bracketed paste ending in a newline (the coalesced anti-pattern), it would
    park. This asserts the anti-pattern parks, so the guard is meaningful."""
    line = "[wake] check bus #7 topic"
    bad = PASTE_START + line.encode() + b"\n" + PASTE_END   # coalesced, no separate CR
    model = _drive_through_pty([bad])
    assert model.submitted == []
    assert line in model.buffer


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
