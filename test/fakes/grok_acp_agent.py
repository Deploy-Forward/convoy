#!/usr/bin/env python3
"""NDJSON ACP agent stub for convoy grok-acp unit tests. No network. No grok."""
from __future__ import annotations

import json
import sys

SESSION_ID = "01234567-89ab-cdef-0123-456789abcdef"


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    session = SESSION_ID
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        method = msg.get("method")
        rid = msg.get("id")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": 1,
                    "agentCapabilities": {
                        "loadSession": True,
                        "promptCapabilities": {"image": False, "audio": False, "embeddedContext": False},
                        "sessionCapabilities": {"resume": {}},
                    },
                    "agentInfo": {"name": "fake-grok-acp", "version": "test"},
                    "authMethods": [],
                },
            })
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": session}})
        elif method in ("session/load", "session/resume"):
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "session/prompt":
            sid = params.get("sessionId") or session
            send({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": sid,
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "ACP_PONG"},
                    },
                },
            })
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
        elif method == "notifications/initialized":
            continue
        elif rid is not None:
            send({
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": "unknown method " + str(method)},
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
