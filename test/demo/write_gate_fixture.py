"""Open the MCP write gate in a test about a write verb's behaviour, not about identity.

Since Convoy 1.3.2 the only thing that opens the write tools over the wire is a
checked conductor bearer on the request; there is no process-wide switch. Tests
that exercise what a write verb DOES (send, seat, crew, the redaction behind
the gate) open the gate here instead: `_write_tools_enabled` answers true for
this test only, and no identity is invented, so a launch still refuses for want
of a proven launcher exactly as it does for a caller with no bearer. Identity
itself is covered with real minted bearers in conductor_bearer_test and
loopback_mcp_test.

The patch is on the module attribute, so it reaches the HTTP server's request
threads as well as in-process calls.
"""
from __future__ import annotations

import contextlib
from typing import Any
from unittest import mock


def write_gate() -> Any:
    """A patcher (start/stop or a context manager) that opens the write gate for a
    local caller. An anonymous caller through a proxy stays on the product surface."""
    from convoy import mcp_http
    return mock.patch.object(mcp_http, "_write_tools_enabled", side_effect=lambda: not mcp_http._anonymous_public())


def open_write_gate(test: Any) -> None:
    """Open the gate for the rest of `test`, closed again at cleanup."""
    p = write_gate()
    p.start()
    test.addCleanup(p.stop)


def closed_write_gate() -> Any:
    """The gate as a caller with no bearer meets it, inside a test that opened it."""
    from convoy import mcp_http
    return mock.patch.object(mcp_http, "_write_tools_enabled", return_value=False)


def write_gate_if(gated: bool) -> Any:
    return write_gate() if gated else contextlib.nullcontext()
