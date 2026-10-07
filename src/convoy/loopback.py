"""Loopback-only request checks shared by Convoy's two local HTTP servers.

A page on any site can make a browser POST to a port on 127.0.0.1, and a DNS
name that resolves to 127.0.0.1 (DNS rebinding) makes that page same-origin
with it. The MCP Streamable HTTP transport says a server MUST validate Origin
for this reason. So a request is served only when:

- the peer address is this machine's loopback,
- it carries exactly one Host, naming a loopback name on the listening port,
- it carries at most one Origin, and any Origin is an http:// loopback origin
  on that same port (`null`, https and other ports are refused),
- its request target is a path (origin form). An absolute-form target names an
  authority that RFC 9112 prefers over Host, and `*` names no resource.

A non-browser client can forge Host, so the peer check is what keeps a server
loopback-only; the Host and Origin checks are what stop a browser page. Both
servers also refuse to bind anything but 127.0.0.1, localhost or ::1.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "[::1]"})
BIND_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _split_host(value: str) -> tuple[str, int | None] | None:
    """`name[:port]` -> (lowercased name, port or None); None when it is not that shape.
    The port must be written canonically: no sign, no leading zero."""
    v = value.strip().lower()
    if not v:
        return None
    if v.startswith("["):
        end = v.find("]")
        if end < 0:
            return None
        name, rest = v[:end + 1], v[end + 1:]
    else:
        name, sep, tail = v.partition(":")
        rest = ":" + tail if sep else ""
    if not rest:
        return name, None
    digits = rest[1:]
    if not rest.startswith(":") or not digits.isascii() or not digits.isdigit() or str(int(digits)) != digits:
        return None
    return name, int(digits)


def host_ok(value: str | None, port: int) -> bool:
    parsed = _split_host(value or "")
    if parsed is None or parsed[0] not in LOOPBACK_NAMES:
        return False
    return parsed[1] == port or (parsed[1] is None and port == 80)


def origin_ok(value: str | None, port: int) -> bool:
    """No Origin is a non-browser client and is allowed. A present one must be
    http://<loopback name>:<this port>."""
    if value is None:
        return True
    v = value.strip()
    if not v.lower().startswith("http://"):
        return False
    return host_ok(v[len("http://"):], port)


def loopback_request_ok(host: str | None, origin: str | None, port: int) -> bool:
    """True when a request with this Host and Origin may be served on `port`."""
    return host_ok(host, port) and origin_ok(origin, port)


def peer_is_loopback(peer: str | None) -> bool:
    """True when the connecting address is this machine's loopback (127/8, ::1,
    or an IPv4-mapped loopback). Unparseable is not loopback."""
    try:
        ip = ipaddress.ip_address(str(peer or "").split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(ip.is_loopback or (mapped is not None and mapped.is_loopback))


def request_ok(peer: str | None, headers: Any, port: int, target: str | None = None) -> bool:
    """The whole gate: a loopback peer, an origin-form `target` when one is given,
    exactly one Host, at most one Origin, both loopback on `port`."""
    if not peer_is_loopback(peer):
        return False
    if target is not None and not str(target).startswith("/"):
        return False
    hosts = headers.get_all("Host") or []
    origins = headers.get_all("Origin") or []
    return len(hosts) == 1 and len(origins) <= 1 and loopback_request_ok(hosts[0], origins[0] if origins else None, port)


DRAIN_CAP = 1 << 20
DRAIN_TIMEOUT_S = 2.0


def drain_refused(handler: Any) -> None:
    """Call after a refusal has been sent. Reads what the client sent (capped,
    and only briefly) so closing the socket does not reset the connection
    before the client reads the refusal; a client that stalls its body is not
    waited on. The connection is closed afterwards."""
    handler.close_connection = True
    try:
        length = max(int(handler.headers.get("Content-Length") or "0"), 0)
    except ValueError:
        length = 0
    length = min(length, DRAIN_CAP)
    if not length:
        return
    try:
        handler.wfile.flush()
        handler.connection.settimeout(DRAIN_TIMEOUT_S)
        handler.rfile.read(length)
    except OSError:
        pass


class ExclusiveBind:
    """Server mixin (put it before the HTTPServer class). On Windows,
    SO_REUSEADDR lets another local process bind the same address and take
    connections, so the port is bound with SO_EXCLUSIVEADDRUSE instead. Other
    platforms keep SO_REUSEADDR, which there only allows a restart past
    TIME_WAIT."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if os.name == "nt" and exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)  # type: ignore[attr-defined]
        super().server_bind()  # type: ignore[misc]


def require_loopback_bind(host: str) -> str:
    """Return `host` (brackets stripped) when it is 127.0.0.1, localhost or ::1; raise ValueError otherwise."""
    h = str(host).strip().strip("[]")
    if h.lower() in BIND_NAMES:
        return h.lower()
    raise ValueError("refusing to bind %r: Convoy serves loopback only (use 127.0.0.1, localhost or ::1)" % host)
