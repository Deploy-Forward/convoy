"""Streamable-style JSON-RPC HTTP MCP for convoy. Attach from Grok Bot is still RED.

Public URL when attached: https://convoy.bot/mcp
This process does not make that URL live. Do not mark GREEN.
One MCP process is bound to one convoy root (and its bound thread).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files as resource_files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .bringup import bring_up, ensure_interactive_path, hide_windows, live_applier, live_runner, terminals
from .harness_contract import (
    canonical_harness_id,
    contract_path,
    harness_entries,
    harness_exec,
    load_harness_contract,
    usage_probe_key,
    usage_remaining_null_until_live_probe,
)
from .install import install as install_harness
from .onboard import onboard as run_onboard
from .context import pack
from .convoy import list_seats, read_thread
from .glance import build_glance
from .gitstate import git_state
from .layer import SCHEMA_VERSION, conductor_stamp, feed_since, neuron_note
from .synapse import fake_runner, native_runner, send_one
from .usage import normalize_usage_remaining, probe

PROTOCOL_LATEST = "2025-03-26"
PROTOCOL_SUPPORTED = frozenset({PROTOCOL_LATEST, "2024-11-05"})
SERVER_NAME = "convoy"
_BASE_VERSION = "0.1.0"


def _server_version(repo_dir: Path | None = None) -> str:
    """Base version plus `git describe --always --dirty` when the package sits
    in a git checkout, so deploy drift — including a patched-in-place deploy —
    is detectable in one initialize call. Unknown stays the bare base version —
    never an invented sha. SubprocessError is caught too: TimeoutExpired is NOT
    an OSError, and a hung git must not stop the server from importing."""
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_dir or Path(__file__).resolve().parent), "describe", "--always", "--dirty"],
            capture_output=True, text=True, timeout=10,
        )
        build = (r.stdout or "").strip()
        if r.returncode == 0 and build:
            return _BASE_VERSION + "+" + build
    except (OSError, subprocess.SubprocessError):
        pass
    return _BASE_VERSION


SERVER_VERSION = _server_version()
HOME_LINE = "convoy.bot · a grok-bot native mcp · one process ↔ one bound thread"

HARNESSES = tuple((row["id"], str(row.get("name") or row["id"])) for row in harness_entries(mcp_supported_only=True))

_TOOL_NAMES = ("roster", "glance", "onboard", "terminals", "context", "send", "feed", "stamp", "note", "bring_up", "open", "hide", "minimize", "background", "install")

# N-5 gate: SoT write tools are never exposed on an ungated public process.
# RPC-layer only — CLI and in-process call_tool stay usable; a gated/loopback
# deploy opts in via CONVOY_MCP_WRITE_TOOLS=1.
_WRITE_TOOLS = frozenset({"stamp", "note"})


def _write_tools_enabled() -> bool:
    return os.environ.get("CONVOY_MCP_WRITE_TOOLS", "").strip() == "1"

_SITE_ASSETS: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml; charset=utf-8"),
    "/favicon.ico": ("favicon.ico", "image/x-icon"),
    "/favicon-96.png": ("favicon-96.png", "image/png"),
    "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
    "/og.png": ("og.png", "image/png"),
    "/fonts/work-sans-latin.woff2": ("fonts/work-sans-latin.woff2", "font/woff2"),
    "/fonts/jetbrains-mono-latin.woff2": ("fonts/jetbrains-mono-latin.woff2", "font/woff2"),
    "/fonts/OFL-work-sans.txt": ("fonts/OFL-work-sans.txt", "text/plain; charset=utf-8"),
    "/fonts/OFL-jetbrains-mono.txt": ("fonts/OFL-jetbrains-mono.txt", "text/plain; charset=utf-8"),
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


TOOLS: list[dict[str, Any]] = [
    {
        "name": "roster",
        "description": "Live harness roster. present/wired is shutil.which on the MCP process PATH, not an already-open desktop terminal. Interactive bash skips .profile so ~/.local/bin (claude, codex) can be installed and still command-not-found; roster/bring_up ungate ~/.bashrc. usage_remaining is JSON null when the harness does not expose a remaining count.",
        "inputSchema": _schema({}),
    },
    {
        "name": "glance",
        "description": "Read-only usage card with a conductor identifier (`grok-bot`), overall BYO harness remaining, and optional by-thread seats. Honest values only: usage_remaining is number|object|null.",
        "inputSchema": _schema({
            "thread": {"type": "string"},
            "convoy_id": {"type": "string"},
        }),
    },
    {
        "name": "onboard",
        "description": "First-run after MCP attach: user names harnesses they already have. Checks PATH honestly per named harness only; no silent additions. Refuses wrappers (gemini-cli, grok-cli, ultracode-shim, ola-brain). Optional thread + checkout_root bind without stomping an existing different thread. Missing harnesses point to install opt-in when a vendor installer is cataloged; no installer fetch here.",
        "inputSchema": _schema(
            {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Named harness ids you already have (grok, claude, codex, cursor-agent, agy/antigravity, hermes, pi)",
                },
                "thread": {"type": "string"},
                "checkout_root": {"type": "string"},
            },
            required=["to"],
        ),
    },
    {
        "name": "terminals",
        "description": "Window metadata for the process-bound thread. Pointers only. No PTY dump.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
        }),
    },
    {
        "name": "context",
        "description": "Packed pointers only (thread.md, role.md, brief, handoff, instance_id, worktree, branch, pr) plus convoy_id/thread_key from .convoy one-line files. Not file contents.",
        "inputSchema": _schema({
            "instance_id": {"type": "string"},
        }),
    },
    {
        "name": "send",
        "description": "Headless synapse; does not pop a TUI. Sends one compact card to a harness. Default runner is fake. live=true execs native harness CLI on PATH (no ola-brain wrap). Live resumed send is currently refused to avoid spawning a second interactive --resume process. Never live_runner / CREATE_NEW_CONSOLE. Refuses limited without waiting; the refuse card asks the user to bring_up / open a pane or write a .ola/*handoff*.",
        "inputSchema": _schema(
            {
                "to": {"type": "string"},
                "body": {"type": "string"},
                "model": {"type": "string"},
                "label": {"type": "string"},
                "worktree": {"type": "string"},
                "session_id": {"type": "string"},
                "resume": {"type": "string"},
                "live": {"type": "boolean", "default": False},
            },
            required=["to", "body"],
        ),
    },
    {
        "name": "feed",
        "description": "Layer events since ts (feed contract v2: schema_version + additive kinds — conductor stamps, synapse, refuse+ask). Default last 24h. Not vendor resume; readers skip unknown kinds.",
        "inputSchema": _schema({
            "since": {"type": "string", "description": "ISO UTC lower bound. Default last 24h."},
        }),
    },
    {
        "name": "stamp",
        "description": "Conductor stamp: ONE compact line into the thread feed (kind=conductor) so neurons can feed --since this chat's decisions. Not a transcript mirror — summary is clamped to one line; transcript is a pointer, never bytes; unknown agent/model/effort stay JSON null.",
        "inputSchema": _schema(
            {
                "summary": {"type": "string", "description": "Compact one-line decision/stamp"},
                "agent": {"type": "string"},
                "model": {"type": "string"},
                "effort": {"type": "string"},
                "instance_id": {"type": "string"},
                "transcript": {"type": "string", "description": "Pointer to the conductor transcript, never its bytes"},
            },
            required=["summary"],
        ),
    },
    {
        "name": "note",
        "description": "Neuron note: ONE compact line into the thread feed (kind=note) with an attributed from — the writing seat's claimed instance_id (the bus does not authenticate authorship), never grok-bot or an alias of it (conductor lines are stamp). Optional to addresses one seat or grok-bot. Same one-line clamp as stamp; this is the hosted-neuron write path.",
        "inputSchema": _schema(
            {
                "summary": {"type": "string", "description": "Compact one-line note"},
                "instance_id": {"type": "string", "description": "The writing seat's instance_id (honest from; never grok-bot)"},
                "to": {"type": "string", "description": "Optional addressee: a seat instance_id or grok-bot"},
            },
            required=["summary", "instance_id"],
        ),
    },
    {
        "name": "bring_up",
        "description": "Resume seated neurons visibly. dry_run defaults true so a public URL cannot pop windows. Pass dry_run false to spawn.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
            "dry_run": {"type": "boolean", "default": True},
        }),
    },
    {
        "name": "open",
        "description": "Alias of bring_up. The only show command besides bring_up.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
            "dry_run": {"type": "boolean", "default": True},
        }),
    },
    {
        "name": "hide",
        "description": "Minimize or hide neuron TUI windows. Sessions keep running. Does not kill grok.exe/claude.exe/Grok Bot.exe. dry_run defaults true so a public URL cannot change windows. Pass dry_run false to apply. mode=minimize (default, SW_MINIMIZE) or hide (SW_HIDE). restore is bring_up.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
            "mode": {"type": "string", "default": "minimize", "description": "minimize (default) or hide. restore is bring_up."},
            "dry_run": {"type": "boolean", "default": True},
        }),
    },
    {
        "name": "minimize",
        "description": "Alias of hide (mode minimize). Sessions keep running. Does not kill.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
            "mode": {"type": "string", "default": "minimize"},
            "dry_run": {"type": "boolean", "default": True},
        }),
    },
    {
        "name": "background",
        "description": "Alias of hide (mode minimize). Sessions keep running. Does not kill.",
        "inputSchema": _schema({
            "convoy_id": {"type": "string"},
            "thread": {"type": "string"},
            "mode": {"type": "string", "default": "minimize"},
            "dry_run": {"type": "boolean", "default": True},
        }),
    },
    {
        "name": "install",
        "description": "Opt-in vendor harness download. dry_run defaults true. Live needs opt_in true. Only x.ai, claude.ai, chatgpt.com, cursor.com, antigravity.google. Never a wrap. Some MCP-supported harnesses are BYO-only and may not have a cataloged installer. affiliate is always JSON null.",
        "inputSchema": _schema(
            {
                "to": {"type": "string", "description": "grok, claude, codex, cursor-agent, or agy/antigravity. BYO-only harnesses without a vendor installer are refused here (onboard still accepts them when present)."},
                "dry_run": {"type": "boolean", "default": True},
                "opt_in": {"type": "boolean", "default": False},
            },
            required=["to"],
        ),
    },
]


def _null_if_blank(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    return val


def _seat_for(seats: list[dict[str, Any]], hid: str) -> dict[str, Any] | None:
    found = None
    for s in seats:
        if canonical_harness_id(s.get("to")) == hid:
            found = s
    return found


def _roster_contract_view() -> dict[str, Any]:
    contract = load_harness_contract()
    return {
        "path": contract_path(),
        "schema_version": contract.get("schema_version"),
        "effort_types": contract.get("effort_types"),
    }


def build_roster(root: Path) -> dict[str, Any]:
    """Live agents. Missing binaries are present false. Never invent usage 0.

    present is MCP process PATH. Interactive terminals can still miss claude.
    ensure_interactive_path writes ~/.bashrc so the next shell sees harness bins.
    """
    path_card = ensure_interactive_path()
    seats = list_seats(root)
    thread = read_thread(root)
    agents: list[dict[str, Any]] = []
    for hid, name in HARNESSES:
        exe = harness_exec(hid)
        path = shutil.which(exe)
        present = path is not None
        wired = bool(present)
        usage_remaining = None
        availability = None
        auth = None
        models = None
        if present:
            probed = probe(usage_probe_key(hid))
            usage_remaining = normalize_usage_remaining(probed.get("usage_remaining"))
            if usage_remaining == 0 and probed.get("raw") is None and usage_remaining_null_until_live_probe(hid):
                # never invent 0 when the harness does not expose a remaining count
                usage_remaining = None
            if probed.get("limited"):
                availability = "limited"
            else:
                availability = "available"
        seat = _seat_for(seats, hid)
        worktree = None
        branch = None
        pr = None
        if seat is not None:
            wt = seat.get("worktree")
            worktree = _null_if_blank(wt)
            if worktree:
                state = git_state(worktree)
                branch = state.get("git_branch")
                pr = state.get("pr_number")
        agents.append({
            "id": hid,
            "name": name,
            "present": present,
            "wired": wired,
            "auth": auth,
            "models": models,
            "availability": availability,
            "usage_remaining": usage_remaining,
            "tracking": "off",
            "board": "off",
            "thread": thread,
            "worktree": worktree,
            "branch": branch,
            "pr": pr,
        })
    return {"ok": True, "agents": agents, "path": path_card, "contract": _roster_contract_view()}


def _default_since() -> str:
    t = datetime.now(timezone.utc) - timedelta(hours=24)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _opt_str(args: dict[str, Any], key: str) -> str | None:
    val = args.get(key)
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return str(val)


def _opt_bool(args: dict[str, Any], key: str, default: bool) -> bool:
    if key not in args or args.get(key) is None:
        return default
    val = args.get(key)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes")
    return bool(val)


def call_tool(root: Path, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    if name == "roster":
        return build_roster(root)
    if name == "glance":
        return build_glance(root, thread=_opt_str(args, "thread"), convoy_id=_opt_str(args, "convoy_id"))
    if name == "onboard":
        raw_to = args.get("to")
        to: list[str] = []
        if isinstance(raw_to, list):
            to = [str(x) for x in raw_to]
        elif raw_to is not None:
            to = [str(raw_to)]
        return run_onboard(
            root,
            to,
            thread=_opt_str(args, "thread"),
            checkout_root=_opt_str(args, "checkout_root"),
        )
    if name == "terminals":
        return terminals(root, convoy_id=_opt_str(args, "convoy_id"), thread=_opt_str(args, "thread"))
    if name == "context":
        return pack(root, instance_id=_opt_str(args, "instance_id"))
    if name == "send":
        to = _opt_str(args, "to")
        body = args.get("body")
        if not to or body is None:
            return {"ok": False, "error": "send requires to and body"}
        if not isinstance(body, str):
            body = str(body)
        instance_id = _opt_str(args, "session_id")
        resume = _opt_str(args, "resume")
        live = _opt_bool(args, "live", False)
        runner = native_runner if live else fake_runner
        card = send_one(
            root,
            to,
            body,
            instance_id=instance_id,
            resume=resume,
            label=_opt_str(args, "label"),
            runner=runner,
            worktree=_opt_str(args, "worktree"),
            allow_interactive_resume=not live,
        )
        model = _opt_str(args, "model")
        if model is not None and card.get("model") is None:
            card["model"] = model
        return card
    if name == "feed":
        since = _opt_str(args, "since") or _default_since()
        rows = feed_since(root, since)
        return {"ok": True, "schema_version": SCHEMA_VERSION, "since": since, "events": rows}
    if name == "stamp":
        try:
            row = conductor_stamp(
                root,
                str(args.get("summary") or ""),
                agent=_opt_str(args, "agent"),
                model=_opt_str(args, "model"),
                effort=_opt_str(args, "effort"),
                instance_id=_opt_str(args, "instance_id"),
                transcript=_opt_str(args, "transcript"),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "schema_version": SCHEMA_VERSION, **row}
    if name == "note":
        try:
            row = neuron_note(
                root,
                str(args.get("summary") or ""),
                instance_id=_opt_str(args, "instance_id"),
                to=_opt_str(args, "to"),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "schema_version": SCHEMA_VERSION, **row}
    if name in ("bring_up", "open"):
        dry = _opt_bool(args, "dry_run", True)
        runner = None if dry else live_runner
        card = bring_up(
            root,
            convoy_id=_opt_str(args, "convoy_id"),
            thread=_opt_str(args, "thread"),
            runner=runner,
        )
        card["dry_run"] = dry
        return card
    if name in ("hide", "minimize", "background"):
        dry = _opt_bool(args, "dry_run", True)
        mode = _opt_str(args, "mode") or "minimize"
        applier = None if dry else live_applier
        card = hide_windows(
            root,
            convoy_id=_opt_str(args, "convoy_id"),
            thread=_opt_str(args, "thread"),
            mode=mode,
            applier=applier,
        )
        card["dry_run"] = dry
        return card
    if name == "install":
        to = _opt_str(args, "to")
        if not to:
            return {"ok": False, "error": "install requires to", "ran": False}
        dry = _opt_bool(args, "dry_run", True)
        opt_in = _opt_bool(args, "opt_in", False)
        return install_harness(to, dry_run=dry, opt_in=opt_in)
    return {"ok": False, "error": "tool not found: " + name}


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _json_default(_o: Any) -> Any:
    return None


def handle_rpc(root: Path, msg: dict[str, Any]) -> dict[str, Any] | None:
    """Return a JSON-RPC response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method = msg.get("method")
    rpc_id = msg.get("id", None)
    is_notification = "id" not in msg
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    try:
        if method == "initialize":
            requested = None
            if isinstance(params, dict):
                requested = params.get("protocolVersion")
            version = requested if requested in PROTOCOL_SUPPORTED else PROTOCOL_LATEST
            result = {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        if method == "notifications/initialized":
            return None
        if method == "ping":
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}
        if method == "tools/list":
            if is_notification:
                return None
            listed = TOOLS if _write_tools_enabled() else [t for t in TOOLS if t["name"] not in _WRITE_TOOLS]
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": listed}}
        if method == "tools/call":
            if is_notification:
                return None
            name = ""
            arguments: dict[str, Any] = {}
            if isinstance(params, dict):
                name = str(params.get("name") or "")
                raw_args = params.get("arguments")
                if isinstance(raw_args, dict):
                    arguments = raw_args
            if name not in {t["name"] for t in TOOLS} and name != "open":
                payload = {"ok": False, "error": "tool not found: " + name}
                is_err = True
            elif name in _WRITE_TOOLS and not _write_tools_enabled():
                payload = {"ok": False, "error": "write tool disabled on this process: " + name + " (set CONVOY_MCP_WRITE_TOOLS=1 on a gated/loopback deploy)"}
                is_err = True
            else:
                payload = call_tool(root, name, arguments)
                is_err = bool(payload.get("ok") is False and payload.get("error"))
            result = {
                "content": [{"type": "text", "text": _dumps(payload)}],
                "structuredContent": payload,
                "isError": is_err,
            }
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}
    except Exception as e:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": type(e).__name__}}


def _cors(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, Accept, Authorization, MCP-Protocol-Version, Mcp-Session-Id",
    )
    handler.send_header("Access-Control-Max-Age", "86400")


def _site_asset_response(path: str) -> tuple[int, bytes, str] | None:
    spec = _SITE_ASSETS.get(path)
    if spec is None:
        return None
    asset_path, content_type = spec
    try:
        body = resource_files("convoy.site").joinpath(asset_path).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        if path == "/":
            return (200, HOME_LINE.encode("utf-8"), "text/html; charset=utf-8")
        return (404, b"not found", "text/plain; charset=utf-8")
    return (200, body, content_type)


class McpHandler(BaseHTTPRequestHandler):
    server_version = "convoy-mcp/" + SERVER_VERSION

    def log_message(self, fmt: str, *args: Any) -> None:
        # request line only; never log bodies or headers (secrets).
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _root(self) -> Path:
        return Path(getattr(self.server, "convoy_root"))

    def _send(self, code: int, body: bytes, content_type: str, extra: list[tuple[str, str]] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        _cors(self)
        if extra:
            for k, v in extra:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        _cors(self)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/mcp":
            self._send(405, b"POST JSON-RPC to /mcp", "text/plain; charset=utf-8", extra=[("Allow", "POST, OPTIONS")])
            return
        if path == "":
            path = "/"
        site = _site_asset_response(path)
        if site is not None:
            code, body, ctype = site
            self._send(code, body, ctype)
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/mcp":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = 0
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length < 0:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            msg = json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = _dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}).encode("utf-8")
            self._send(400, body, "application/json; charset=utf-8")
            return
        if isinstance(msg, list):
            replies = []
            for item in msg:
                if isinstance(item, dict):
                    r = handle_rpc(self._root(), item)
                    if r is not None:
                        replies.append(r)
            if not replies:
                self.send_response(202)
                _cors(self)
                self.end_headers()
                return
            payload = replies
        elif isinstance(msg, dict):
            reply = handle_rpc(self._root(), msg)
            if reply is None:
                self.send_response(202)
                _cors(self)
                self.end_headers()
                return
            payload = reply
        else:
            payload = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        body = _dumps(payload).encode("utf-8")
        extra = [("MCP-Protocol-Version", PROTOCOL_LATEST)]
        self._send(200, body, "application/json; charset=utf-8", extra=extra)


class McpHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], root: Path):
        self.convoy_root = Path(root).resolve()
        super().__init__(addr, McpHandler)


def make_server(root: Path | str, host: str = "127.0.0.1", port: int = 8788) -> McpHTTPServer:
    return McpHTTPServer((host, port), Path(root))


def serve(root: Path | str, host: str = "127.0.0.1", port: int = 8788) -> int:
    srv = make_server(root, host, port)
    bound_host, bound_port = srv.server_address[:2]
    print("convoy mcp listening on http://%s:%s/mcp (attach RED until Grok Bot catalogs it)" % (bound_host, bound_port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m convoy.mcp_http")
    p.add_argument("--root", default=".", help="layer root")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8788)
    args = p.parse_args(argv)
    return serve(Path(args.root).resolve(), host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
