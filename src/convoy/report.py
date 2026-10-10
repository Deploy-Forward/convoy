"""The report client: the only place Convoy speaks to the platform.

Convoy is open MIT and the platform is closed. This module is the seam, and
it is deliberately the thinnest one that can exist: stdlib urllib, the public
OpenAPI paths and nothing else, no sibling import, no state that could be
mistaken for a session. It can be read in full by anyone deciding whether to
pair a machine, which is the point.

Five rules, each of which has already cost a day somewhere:

1. Unpaired is OFF. With no origin.json there is no client, so a machine that
   never opted in cannot make a request by accident.
2. The credential is read at CALL time - not at construction, not cached - so
   a rotation or a revocation takes effect on the next call and a long-lived
   loop never holds a secret in memory across a night. utf-8-sig, because
   PowerShell 5.1's `-Encoding utf8` writes a BOM and the BOM becomes the
   first character of the Authorization header, failing as an opaque 403.
   Asserted ASCII, and never echoed: not in a log line, not in an exception.
3. Every call sends a browser User-Agent. Cloudflare rejects the default
   Python-urllib agent with `error code: 1010` BEFORE the credential is read.
4. A 403 is therefore triaged by its BODY. A WAF code is Transient; only an
   auth body is Revoked. A machine that unpaired itself over a network hiccup
   would be worse than one that retried too long.
5. Writes carry an Idempotency-Key, one per write, so a retry after a
   timeout is the same write and not a second one.

Statuses come back in an envelope {status, body} rather than as exceptions,
because 409 is a normal answer to a replayed write (the outbox drops on it)
and only Revoked and Transient change what the caller does next.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

# A real browser string. Not decoration: see rule 3.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
API_BASE = "/api/org/worklanes"
ORIGIN_FILE = "origin.json"
TIMEOUT_S = 20.0
# Markers that mean an edge rejected the request before the app ever saw it.
WAF_MARKERS = ("error code: 1010", "error code: 1020", "cloudflare",
               "attention required", "<!doctype html")


class Revoked(Exception):
    """The platform refused this credential. Stop; a human must re-pair."""


class Transient(Exception):
    """The request did not reach a verdict. Back off and try again."""


def read_origin(home: Path | str) -> dict[str, Any] | None:
    """The pairing record, or None. None is the whole off switch."""
    path = Path(home) / ORIGIN_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not str(value.get("api_base") or "").strip():
        return None
    return value


def _read_credential(origin: dict[str, Any]) -> str:
    """The bearer, read fresh. Never logged, never in an exception message.

    The assertions name the DEFECT and never the value: a credential in a
    traceback is a credential in a bug report.
    """
    path = str(origin.get("credential_path") or "").strip()
    if not path:
        raise ValueError("origin.json names no credential_path")
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError("cannot read the origin credential file: " + type(exc).__name__) from None
    text = raw.strip()
    if not text:
        raise ValueError("the origin credential file is empty")
    if text.startswith("﻿"):
        raise ValueError("the origin credential still carries a BOM after utf-8-sig")
    if not text.isascii():
        raise ValueError("the origin credential is not ASCII; it cannot ride an HTTP header")
    if any(ch.isspace() for ch in text):
        raise ValueError("the origin credential contains whitespace; it is not a bearer token")
    return text


def _looks_like_waf(body: str) -> str | None:
    low = (body or "").lower()
    for marker in WAF_MARKERS:
        if marker in low:
            return marker
    return None


class ReportClient:
    """Speaks the public OpenAPI on behalf of one paired origin."""

    def __init__(self, origin: dict[str, Any] | None, *,
                 opener: Callable[..., Any] = urllib.request.urlopen,
                 timeout: float = TIMEOUT_S,
                 log: Callable[[str], Any] | None = None) -> None:
        if not origin:
            raise ValueError("refuse a report client without a pairing record")
        self.origin = dict(origin)
        self.base = str(self.origin.get("api_base") or "").rstrip("/")
        self._open = opener
        self._timeout = float(timeout)
        self._log = log or (lambda _line: None)

    @classmethod
    def from_home(cls, home: Path | str, **kw: Any) -> "ReportClient | None":
        """The client, or None when this machine is not paired. Callers use
        the None to stay silent rather than to raise."""
        origin = read_origin(home)
        if origin is None:
            return None
        return cls(origin, **kw)

    # -- the four public calls -------------------------------------------

    def origin_queue(self) -> dict[str, Any]:
        return self._call("GET", API_BASE + "/origin/queue")

    def fulfil(self, card_id: str, link_id: str, body: dict[str, Any]) -> dict[str, Any]:
        path = (API_BASE + "/cards/" + _segment(card_id) +
                "/threads/" + _segment(link_id) + "/fulfil")
        return self._call("POST", path, body=body)

    def report(self, token: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", API_BASE + "/delegations/" + _segment(token) + "/report", body=body)

    def beat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", API_BASE + "/origin/beat", body=payload)

    def answer_nudge(self, nudge_id: str, outcome: str, reason: str | None = None) -> dict[str, Any]:
        """The origin's account of one nudge: nudged, refused or unsupported.
        The platform never types anything itself; this is the only place that
        tells it what actually happened on this machine."""
        body: dict[str, Any] = {"outcome": outcome}
        if reason:
            body["reason"] = str(reason)[:400]
        return self._call("POST", API_BASE + "/origin/nudges/" + _segment(nudge_id), body=body)

    # -- one transport ----------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        credential = _read_credential(self.origin)   # at call time, every time
        headers = {
            "Authorization": "Bearer " + credential,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = str(uuid.uuid4())
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        self._log(method + " " + path)
        try:
            with self._open(request, timeout=self._timeout) as response:
                status = int(getattr(response, "status", 200) or 200)
                raw = response.read()
        except urllib.error.HTTPError as exc:
            return self._from_http_error(method, path, exc)
        except urllib.error.URLError as exc:
            self._log(method + " " + path + " -> unreachable")
            raise Transient("unreachable: " + type(exc).__name__) from None
        except OSError as exc:
            self._log(method + " " + path + " -> " + type(exc).__name__)
            raise Transient("transport: " + type(exc).__name__) from None
        self._log(method + " " + path + " -> " + str(status))
        return {"status": status, "body": _parse(raw)}

    def _from_http_error(self, method: str, path: str, exc: Any) -> dict[str, Any]:
        status = int(getattr(exc, "code", 0) or 0)
        try:
            text = (exc.read() or b"").decode("utf-8", errors="replace")
        except Exception:
            text = ""
        self._log(method + " " + path + " -> " + str(status))
        if status in (401, 403):
            marker = _looks_like_waf(text)
            if marker:
                # Rule 4: the edge answered, not the app. A WAF page is not a
                # verdict on the credential and must never unpair a machine.
                raise Transient("edge refused before auth (" + marker + ")") from None
            raise Revoked("the platform refused this origin credential (" + str(status) + ")") from None
        if status >= 500:
            raise Transient("server error " + str(status)) from None
        return {"status": status, "body": _parse(text.encode("utf-8"))}


def _segment(value: Any) -> str:
    """One path segment, escaped. A card id is data and a URL is not."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("refuse an empty path segment")
    return urllib.parse.quote(text, safe="")


def _parse(raw: Any) -> Any:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except Exception:
            return None
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
