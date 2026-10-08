"""Streamable-style JSON-RPC HTTP MCP for Convoy, on this machine's loopback.

Default address: http://127.0.0.1:8788/mcp (`convoy mcp`). There is no hosted
Convoy endpoint. One local server serves every thread in the machine index and
each call names its thread; `--root` pins one.

The server binds only a loopback address (127.0.0.1, localhost or ::1; any
other --host is refused) and answers only loopback requests: the peer must be
this machine's loopback, the Host must be 127.0.0.1, localhost or [::1] on the
port it listens on, and an Origin, when present, must be an http:// loopback
origin on that same port. Anything else is a 403 (DNS rebinding defense, as the
MCP Streamable HTTP transport requires). Writes need a conductor bearer from
`convoy conductor mint`.
"""
from __future__ import annotations

import argparse
import contextvars
import ipaddress
import json
import re
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .bringup import bring_up, dry_opt_in_refusal, ensure_interactive_path, hide_windows, live_applier, live_runner, terminals
from .rail import build_rail
from .loopback import ExclusiveBind, drain_refused, loopback_request_ok, request_ok, require_loopback_bind  # noqa: F401 - loopback_request_ok is re-exported
from .provenance import build_provenance
from .card import CARD_OUTPUT_SCHEMA, build_card
from .harness_contract import (
    canonical_harness_id,
    contract_path,
    effort_contract,
    harness_entries,
    harness_exec,
    load_harness_contract,
    model_catalog,
    usage_probe_key,
    usage_remaining_null_until_live_probe,
    where_options,
)
from .install import install as install_harness
from .onboard import onboard as run_onboard
from .repo import checkout_path_for, clone as clone_repo, is_repo_url, list_repos, mint_worktrees
from .context import pack
from .convoy import list_seats, read_id, read_thread
from .activity import neuron_activity, resolve_neuron_id_on_thread
from .convoy import seat as seat_chair
from .glance import build_glance
from .graph import build_graph, neighborhood
from .inbox import drain as drain_inbox, pending as pending_inbox
from .lifecycle import join as join_chair, seated_ack
from .consent import grant_consent
from .nudge import nudge_seat
from .crew import await_seated, crew as crew_chairs
from .targeted_launch import active_pane_runner, launch_choices, launch_seat
from .focus import focus_seat
from .graph_html import resume_neuron
from .index import index_path, list_threads, prune_threads
from .panes import bodies
from .gitstate import git_state
from .layer import SCHEMA_VERSION, conductor_stamp, feed_since, neuron_note, parse_since
from .synapse import fake_runner, is_wrapper_name, native_runner, send_one
from .convoy import CONDUCTOR as CONDUCTOR_ID
from . import bearer as _bearer
from . import version as _version
from .usage import CachedProbe, normalize_usage_remaining, probe as _live_probe

# roster and glance once took about twenty seconds even on loopback, because
# each request probed the vendors synchronously on the request thread
# (claude's /usage alone takes seconds, and ran more than once per card).
# Clients gave up mid-response, which the server logged as WinError
# 10053 in _send. The widget solved the same problem with CachedProbe: the
# request path never blocks on a vendor; the first ask says probing:true and a
# background refresh fills the cache. One instance per process, shared by
# every tool that reads usage.
probe: Any = CachedProbe(_live_probe, ttl_s=60.0)

PROTOCOL_LATEST = "2025-03-26"
PROTOCOL_SUPPORTED = frozenset({PROTOCOL_LATEST, "2024-11-05"})
SERVER_NAME = "convoy"
_BASE_VERSION = _version.package_version()


def _server_version(repo_dir: Path | None = None) -> str:
    """Base version plus `git describe --always --dirty` when the package sits
    in its own source checkout, so deploy drift — including a patched-in-place deploy —
    is detectable in one initialize call. An installed package gets the bare base
    version: a site-packages dir inside some other repository (a venv in a checkout)
    must not borrow that repository's describe. Unknown stays the bare base version —
    never an invented sha. SubprocessError is caught too: TimeoutExpired is NOT
    an OSError, and a hung git must not stop the server from importing."""
    if repo_dir is None and not _version.in_checkout():
        return _BASE_VERSION
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
HOME_LINE = "Convoy MCP v{version} on this machine. POST JSON-RPC to /mcp. Threads: {threads}."

HARNESSES = tuple((row["id"], str(row.get("name") or row["id"])) for row in harness_entries(mcp_supported_only=True))

# N-5 gate: SoT write tools are never exposed to a caller without identity.
# RPC-layer only: the CLI stays usable. Over the wire a write needs a checked
# conductor bearer (`convoy conductor mint`); there is no process-wide switch.
# send is also hidden: even its non-live form appends a synapse/feed row, so it
# is not read-only. seat/join/launch are in this set with the wizard verbs.
# They are HIDDEN from tools/list while no bearer is minted, not listed-and-refusing, on purpose:
# the @convoy wizard's Gate 0 reads tools/list to decide whether it can seat
# and launch, and a server that will not do those for this caller must not say it can.
# Gate 0 goes RED there and stops with an install card - fail-closed, which is
# the behaviour the wizard promises. inbox stays listed: its read is public;
# only drain is gated, inside the handler, like resume go=true.
# onboard joined the gate: it binds the thread (writes .convoy/)
# and, given a URL, SPAWNS git clone. clone and mint spawn git outright.
# repos joined after review the same day: `gh repo list` runs as whoever is
# logged in on the MCP HOST, so for a caller without a bearer it could only
# hand the operator's inventory (private names included) to that caller and
# spend the operator's API quota. It is the conductor's account; the gate says so.
# crew / seated / consent joined too: crew mints worktrees,
# joins N chairs and may spawn the window; seated stamps a chair's proof of
# life; consent mints a one-time grant. await_seated only reads, but it holds
# the request thread up to its timeout, which a caller without a bearer must not get.
_THREAD_PROPS = {
    "thread": {"type": "string", "description": "which thread this call touches: the thread key from the `threads` tool. Required when the origin is not pinned to one root; overrides the pin when it is."},
    "convoy_id": {"type": "string", "description": "which thread this call touches, by cvy_ id (alternative to `thread`)"},
}
# onboard takes `thread` as the NAME of the thread it creates; crew routes by it (and checks it).
_THREAD_IS_A_NAME_NOT_A_ROUTE = frozenset({"onboard"})
_WRITE_TOOLS = frozenset({"send", "stamp", "note", "seat", "join", "launch", "onboard", "clone", "mint", "repos",
                          "crew", "seated", "consent", "await_seated", "focus", "nudge"})
# MCP safety annotations describe what a tool can do on THIS process. Some
# tools have a read-only form for a caller without a bearer and a state-changing
# form only behind the write gate. Keep this vocabulary
# separate from _WRITE_TOOLS: repos and await_seated are gated for privacy and
# resource control, but they do not mutate state.
_STATE_CHANGING_TOOLS = frozenset({
    "send", "stamp", "note", "seat", "join", "launch", "onboard", "clone",
    "mint", "crew", "seated", "consent", "focus", "nudge",
})
_CONDITIONAL_STATE_CHANGING_TOOLS = frozenset({
    "bring_up", "open", "hide", "minimize", "background", "install",
    "resume", "inbox",
})
_IRREVERSIBLE_TOOLS = frozenset({"send", "stamp", "note"})
AWAIT_SEATED_MAX_S = 600.0


# The principal of the request being served: {id, conductor, label} from a
# checked bearer (bearer.py), else None. Set by the HTTP handler (or handle_rpc's
# `principal` argument) for the duration of one dispatch. A contextvar so the
# twenty-odd gate checks below stay one call and read the right request even on
# the threading server.
_PRINCIPAL: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("convoy_principal", default=None)


def _launch_launcher() -> dict[str, Any] | None:
    """The launcher an MCP launch records: the conductor this request's bearer proves.
    None without one: the launch then refuses."""
    from .launcher import conductor_launcher
    sender = _conductor_sender()
    return conductor_launcher(sender["chair"]) if sender else None


def _no_launcher(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    from .launcher import UNPROVEN_ERROR
    return {"ok": False, **(extra or {}), "error": UNPROVEN_ERROR,
            "why": "this request carries no bearer identity, so no conductor can be recorded as the launcher",
            "next": "call with the conductor's bearer (`convoy conductor mint`)"}


def _record_mcp_launcher(root: Path, sids: list[str]) -> tuple[dict[str, Any], dict[str, str]]:
    """Record the bearer's conductor on each chair a launch may spawn (a pending boot prompt,
    no live pane host, no launch claim held by a live process) and return what was there
    before, for _settle_mcp_launcher, plus the chairs another launch holds (skipped). The
    check and the record run under the chair's launch-claim lock, the lock every launcher
    record takes, so an MCP launch and a CLI launch of one chair never interleave."""
    from .filelock import exclusive
    from .lifecycle import record_launcher
    from .targeted_launch import _claim_expired, _claim_path, hosted_live, read_launch_claim
    launcher = _launch_launcher()
    wanted = set(sids) if sids else None
    previous: dict[str, Any] = {}
    held: dict[str, str] = {}
    for s in list_seats(root):
        sid = s.get("session_id")
        if not ((wanted is None or sid in wanted) and str(s.get("boot_prompt") or "").strip()):
            continue
        with exclusive(_claim_path(root, sid)):
            claim = read_launch_claim(root, sid)
            if hosted_live(root, sid) or (claim is not None and not _claim_expired(claim)):
                held[sid] = "another launch holds this chair's claim"
                continue
            current = next((r for r in list_seats(root) if r.get("session_id") == sid), s)
            previous[sid] = ("launched_by" in current, current.get("launched_by"), current.get("launched_by_why"))
            record_launcher(root, sid, {"kind": "conductor", "name": launcher["name"]})
    return previous, held


def _settle_mcp_launcher(root: Path, previous: dict[str, Any], spawned: list[str]) -> None:
    from .lifecycle import record_launcher
    for sid, (had, by, why) in previous.items():
        if sid not in spawned:
            record_launcher(root, sid, by, (why if had else "no launch has spawned this chair yet") if by is None else None)


def _conductor_sender() -> dict[str, Any] | None:
    """The sender of an MCP send: the conductor of this request's checked bearer, never a
    name from the arguments. No bearer, no proven sender."""
    principal = _PRINCIPAL.get()
    if isinstance(principal, dict) and isinstance(principal.get("conductor"), str) and principal["conductor"].strip():
        return {"chair": principal["conductor"].strip(), "verified_by": "bearer"}
    return None


# Did this request arrive from outside the machine? Set per request by handle_rpc.
_PUBLIC: contextvars.ContextVar[bool] = contextvars.ContextVar("convoy_public", default=False)

# Every edge adds one of these (a CDN: Cf-Connecting-Ip; any reverse proxy:
# X-Forwarded-For). A local client sends none and speaks from loopback.
_PROXY_HEADERS = ("Cf-Connecting-Ip", "X-Forwarded-For", "Forwarded", "X-Real-Ip")

# What an anonymous caller through a proxy may touch: the product, never a
# record. `install` is forced dry; `threads` answers a count. Convoy ships no
# proxy and no tunnel; this stays as defense in depth for anyone who builds one.
_PRODUCT_SURFACE = frozenset({"card", "choices", "install", "threads"})

# A filesystem path anywhere in a card, whole or embedded in prose (a boot
# prompt, a summary): drive-letter, UNC, POSIX home-like roots, tilde.
_PATH_RX = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|/(?:Users|home|root|tmp|var|opt|mnt|srv|etc|private)/|~[\\/])"
    r"[^\s\"'<>|*?`]*"
)


def _is_public_request(peer: str, headers: Any) -> bool:
    """True when the request came through an edge or from a non-loopback peer.

    Without it, an anonymous POST that reached the server from off the machine would return every thread's root
    under the operator's home and the names those roots carry. Nothing a local client sends can be told from a remote one
    except these two facts, and a local client already owns the disk."""
    for name in _PROXY_HEADERS:
        try:
            if headers.get(name):
                return True
        except AttributeError:
            break
    try:
        return not ipaddress.ip_address(str(peer or "").strip()).is_loopback
    except ValueError:
        return True


def _anonymous_public() -> bool:
    return bool(_PUBLIC.get()) and _PRINCIPAL.get() is None


def _write_tools_enabled() -> bool:
    """A write needs a checked bearer on this request, full stop."""
    return _PRINCIPAL.get() is not None


def _write_gate() -> str:
    """How this process admits writes: bearer | closed."""
    if _bearer.live_count() > 0:
        return "bearer"
    return "closed"


def _listed_tools() -> list[dict[str, Any]]:
    """What tools/list answers on THIS process: everything behind the gate,
    the read-only verbs otherwise. card scores its preflight on the same list.

    OpenAI's plugin scanner consumes these annotations from the live endpoint,
    so they must reflect the process gate rather than an imagined deployment.
    """
    # A process with a live bearer minted accepts writes from that bearer's
    # holder, so it lists the write tools; each call is still checked.
    writes = _write_tools_enabled() or _bearer.live_count() > 0
    tools = TOOLS if writes else [t for t in TOOLS if t["name"] not in _WRITE_TOOLS]
    if _anonymous_public():
        writes = False
        tools = [t for t in TOOLS if t["name"] in _PRODUCT_SURFACE]
    listed: list[dict[str, Any]] = []
    for tool in tools:
        name = tool["name"]
        mutates = name in _STATE_CHANGING_TOOLS or (writes and name in _CONDITIONAL_STATE_CHANGING_TOOLS)
        listed.append({
            **tool,
            "annotations": {
                "readOnlyHint": not mutates,
                "destructiveHint": mutates and name in _IRREVERSIBLE_TOOLS,
                "openWorldHint": False,
            },
        })
    return listed


# No enum here on purpose: the vocabulary is per harness (grok xhigh, codex
# extra-high, pi --thinking levels). The handler refuses a value the named
# harness does not take and the error lists that harness's real keys.
_EFFORT_ARG = {
    "type": "string",
    "description": "declared effort, validated for the named harness; valid keys are choices.harnesses[].effort.keys, refused otherwise naming them. Reaches argv only where effort.applied is true.",
}
# Model is checked the same way, against choices.harnesses[].models. That
# catalog is null wherever no local --help enumerates a closed list, and
# null accepts anything — a field, not a menu.
_MODEL_ARG = {
    "type": "string",
    "description": "declared model, passed through as typed when choices.harnesses[].models is null; when that catalog is a list, a model outside it is refused naming the list.",
}
# where IS a closed axis, so an enum is honest here. cloud is refused per
# harness unless choices.harnesses[].where.cloud.offered is true (only an
# evidenced interactive attach, such as claude --cloud).
_WHERE_ARG = {
    "type": "string",
    "enum": ["local", "cloud"],
    "description": "local (default) or cloud. cloud is accepted only where choices.harnesses[].where.cloud.offered is true, refused otherwise naming that harness's cloud mode and evidence. A cloud chair has no worktree, and no launcher exists for it yet.",
}


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list",
        "description": "Read-only local machine thread picker, numbered threads and full neuron rows. Temp and absent roots remain named as skipped. Authenticated surface only, never anonymous product reads.",
        "inputSchema": _schema({"all": {"type": "boolean"}, "since": {"type": "string"}}),
    },
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
        "description": "First-run after MCP attach: user names harnesses they already have (write gate: it binds the thread and may clone). Checks PATH honestly per named harness only; no silent additions. Refuses wrappers (gemini-cli, grok-cli, ultracode-shim, ola-brain). Optional thread + checkout_root bind without stomping an existing different thread; a git URL as checkout_root is cloned once into the Convoy-owned checkout root and reused after. Missing harnesses point to install opt-in when a vendor installer is cataloged; no installer fetch here.",
        "inputSchema": _schema(
            {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Named harness ids you already have (grok, claude, codex, cursor-agent, agy/antigravity, hermes, pi)",
                },
                "thread": {"type": "string"},
                "checkout_root": {"type": "string", "description": "an existing path, or a git URL (https://... or git@...) cloned under <CONVOY_HOME>/checkouts/<owner>/<repo>"},
                "github": {"type": "boolean", "description": "the wizard's GitHub? answer, recorded on the bind as yes|no; a URL records yes by itself; omitted stays null"},
                "probe": {"type": "boolean", "default": False, "description": "read each named harness's usage by running its CLI; omitted: usage is null and no harness binary is started"},
            },
            required=["to"],
        ),
    },
    # The repository step. repos reads names and URLs
    # from `gh repo list` as the MCP host's login, never a token, and a
    # missing gh is an install hint rather than a guessed list. It sits
    # behind the write gate with clone and mint (which spawn git): the
    # inventory is the conductor's, so it is hidden publicly.
    {
        "name": "repos",
        "description": "Read-only: the GitHub repositories of the gh login on the MCP host (the conductor's account, not the caller's) via `gh repo list` on the process PATH (name, url, private, updated_at). Write gate: it discloses that inventory. gh absent is ok=false with an install hint and repos null; never a remembered list, never a token.",
        "inputSchema": _schema({"limit": {"type": "integer", "default": 30}}),
    },
    {
        "name": "clone",
        "description": "git clone one URL into the Convoy-owned checkout root, <CONVOY_HOME>/checkouts/<owner>/<repo> (write gate: this SPAWNS git). Refuses a non-empty dest. .convoy/ and thread.md go into the clone's .git/info/exclude so the bind is never a tracked file of the user's repo.",
        "inputSchema": _schema({"url": {"type": "string"}}, required=["url"]),
    },
    {
        "name": "mint",
        "description": "git worktree add one worktree per seat, DERIVED from the checkout: sibling <checkout>-wt-<name> on branch convoy/<name> (write gate: this SPAWNS git). names defaults to neuron-1..n; an existing sibling is reused; stops at the first git failure naming it.",
        "inputSchema": _schema(
            {"checkout": {"type": "string", "description": "path of a git checkout, e.g. onboard's root"},
             "n": {"type": "integer"},
             "names": {"type": "array", "items": {"type": "string"}}},
            required=["checkout", "n"],
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
        "description": "Packed pointers only (thread.md, role.md, brief, handoff, instance_id, worktree, branch, pr) plus convoy_id/thread_key from .convoy one-line files. Not file contents. `canonical` names where to WRITE: briefs to .convoy/brief.md, handoffs to .convoy/handoff/. `legacy_ola` lists any .ola/ files still being read (legacy, read only) with `advice`.",
        "inputSchema": _schema({
            "instance_id": {"type": "string"},
        }),
    },
    {
        "name": "send",
        "description": "Headless synapse; does not pop a TUI. Naming a live seat queues the body (delivery=queued, delivered=false) instead of spawning a second --resume. Codex may native-queue. Fake ACKs are recorded, not delivered. live=true still never steals a TUI. Refuses limited without waiting.",
        "inputSchema": _schema(
            {
                "to": {"type": "string", "description": "Seat harness/name or a neuron id on this thread (n + six hex digits)."},
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
        "name": "replies",
        "description": "The conductor's mail: feed rows addressed to it (`to`), newer than `since`, plus a `cursor` to pass back next turn; or the rows citing one send `token` with `delivered` true|false. Read-only. `wait` holds the request up to 600 s and returns on the first landing row; like await_seated it is behind the write gate because it holds a request. Contract: <root>/.convoy/conductor.md.",
        "inputSchema": _schema({
            "since": {"type": "string", "description": "ISO UTC lower bound or a window (10m | 2h); default epoch"},
            "token": {"type": "string", "description": "a send token; returns the rows citing it and delivered"},
            "wait": {"type": "number", "description": "seconds to hold for the first row, max 600 (gated)"},
            "conductor": {"type": "string", "description": "conductor id; default grok-bot"},
        }),
    },
    {
        "name": "feed",
        "description": "Layer events since ts (feed contract v2: schema_version + additive kinds — conductor stamps, synapse, refuse+ask). Default last 24h. Not vendor resume; readers skip unknown kinds.",
        "inputSchema": _schema({
            "since": {"type": "string", "description": "ISO UTC lower bound, or a window: 10m | 2h | 1d | 45s. Default last 24h."},
        }),
    },
    {
        "name": "rail",
        "description": "Read-only: the thread rail, the strip under the panes. Feed events in the window, seats connected | pending | stale from the seated acks, usage remaining per harness (null is unknown, never 0), last conductor stamp, lead. Reads only the bound thread, so every neuron and this chat see one rail. Never a token.",
        "inputSchema": _schema({
            "since": {"type": "string", "description": "feed window: 10m | 2h | 1d | 45s, or an ISO UTC lower bound. Default 10m."},
        }),
    },
    {
        "name": "provenance",
        "description": "Read-only: per-chair Git provenance folded from seats.jsonl and kind=commit feed rows. Unknown fields stay null; chairs without commit rows report commits 0.",
        "inputSchema": _schema({
            "since": {"type": "string", "description": "optional feed window: 10m | 2h | 1d | 45s, or an ISO UTC timestamp"},
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
        "description": "Neuron note: ONE compact line into the thread feed (kind=note) with a claimed from — the writing seat's instance_id (the bus does not authenticate authorship), never grok-bot or an alias of it (conductor lines are stamp). The row says author_claimed=true and leaves device and verified_by null. Optional to addresses one seat or grok-bot. Same one-line clamp as stamp; this is the neuron-side write path. A claimed note is never a delivery receipt; the chair's own CLI reply (convoy reply TOKEN) is.",
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
        "description": "Resume seated neurons visibly. dry_run defaults true. Pass dry_run false to spawn; that needs a conductor bearer.",
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
        "description": "Minimize or hide neuron TUI windows. Sessions keep running. Does not kill grok.exe/claude.exe/Grok Bot.exe. dry_run defaults true. Pass dry_run false to apply; that needs a conductor bearer. mode=minimize (default, SW_MINIMIZE) or hide (SW_HIDE). restore is bring_up.",
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
        "name": "graph",
        "description": "Read-only ontology of the bound thread: chairs, occupants (harness/model), lineage pending/acked, talk edges, lead. Every edge attested, never authenticated; never a token. Pass neuron=<chair> for that chair's rejoin card with its place (last contribution, rank, degree, lead).",
        "inputSchema": _schema({"neuron": {"type": "string", "description": "chair session_id for the neighborhood/place card"}}),
    },
    {
        "name": "panes",
        "description": "Every body of every neuron on the bound thread, from the OS process table (not only what Convoy launched): per chair live/bodies (pid, via token|cwd)/duplicate, plus unassigned harness processes. Never a token. Windows exposes no cwd, so the cwd rung is null there.",
        "inputSchema": _schema({}),
    },
    {
        "name": "threads",
        "description": "Every Convoy thread this machine's index knows (convoy_id, thread, root, updated_at). present=false when the root is gone or its id changed; never a token. `bound` names the thread this origin is pinned to, null when it serves them all and each call names its thread. prune=true drops temp-dir and absent roots and reports every dropped row (write-gated, like resume go=true).",
        "inputSchema": _schema({"prune": {"type": "boolean", "default": False, "description": "drop temp-dir and absent roots from the machine index; reports every dropped row"}}),
    },
    {
        "name": "resume",
        "description": "Resume one neuron at its most recent place: native argv + cwd + place card. Dry by default (no spawn). go=true spawns once and is refused for a caller without a conductor bearer; it also refuses when a live body holds the chair or the chair has no token for its current harness (then launch --seat).",
        "inputSchema": _schema({"neuron": {"type": "string"}, "go": {"type": "boolean", "default": False}}, required=["neuron"]),
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
    # The six verbs below were CLI-only until the PR 50 review found that the
    # @convoy wizard's Gate 0 requires them from the
    # LIVE tools/list and goes RED otherwise, so redeploying the old server
    # could never make the wizard green. Read-only verbs answer anywhere.
    # Anything that mutates the thread or SPAWNS sits behind the same write
    # gate as `resume go=true`: a caller without a bearer never mints a chair or
    # starts a process.
    {
        "name": "choices",
        "description": "Read-only: installed harnesses, known git worktrees, current seats, and whether this host can split an active pane. The wizard renders ONLY what this returns; never a remembered menu. Never a token.",
        "inputSchema": _schema({}),
    },
    # ONE card: the @convoy wizard's single read. Rows are
    # choices rows plus the usage probe glance runs and a crew attach template;
    # preflight is this server's own tools/list scored by wizard_preflight, so
    # the card carries its Gate 0 verdict. outputSchema is declared so a host
    # can render structuredContent as a card without parsing the text copy.
    {
        "name": "contract",
        "description": "Read-only: the conductor contract itself (conductor.md): its text and sha, the same sha glance, roster and context name. Read it before your first write. Each thread mirrors it at <root>/.convoy/conductor.md.",
        "inputSchema": _schema({}),
    },
    {
        "name": "start_card",
        "description": "Read-only: the start card for the bound thread, so a new session starts synced: where (repo, branch, ahead/behind, dirty, thread, lead), who (the neurons), commitments (open sends, the latest handoff per neuron, recent commits, asks from limited sends), board, next. One line per item with a path or id; never file contents. Send tokens are withheld on the ungated wire (behind the write gate they are shown). all=true lifts the 60-line budget.",
        "inputSchema": _schema({"all": {"type": "boolean", "default": False}}),
    },
    {
        "name": "card",
        "description": "Read-only: the one card a host renders for @convoy - header, tagline, summary (installed harnesses, seats, thread, GitHub? answer), this server's own wizard preflight verdict, repo (checkout, worktrees), and one row per harness in contract order: where offered, installed, USAGE REMAINING (number|object|null from the live probe, never an invented 0), models catalog or null, effort keys, connect_mode, and attach (a crew call for that harness). Never a token, never a resume id, never a boot prompt.",
        "inputSchema": _schema({}),
        "outputSchema": CARD_OUTPUT_SCHEMA,
    },
    {
        "name": "neurons",
        "description": "Read-only: who is active on the bound thread and the command that messages each. Bus recency first (a chair that authored a row is alive whatever the process table says), process evidence second. A chair Convoy cannot place is never reported dead. Never a token.",
        "inputSchema": _schema({"since": {"type": "string", "description": "ISO timestamp; default is a 90-minute window"}}),
    },
    {
        "name": "inbox",
        "description": "Pending live-seat messages for one chair. Read (default) is public and lists pending rows. drain=true appends a consumed-marker per row and is behind the write gate. A drain is NOT a receipt: only the chair's own ack row proves delivery. Requires seat; never guesses a chair from cwd.",
        "inputSchema": _schema(
            {"seat": {"type": "string", "description": "chair session_id"},
             "drain": {"type": "boolean", "default": False}},
            required=["seat"],
        ),
    },
    {
        "name": "seat",
        "description": "Register or update a chair on the bound thread (write gate). A worktree belongs to ONE chair: seating a second chair on a held worktree is refused naming both chairs (C8). The same chair may re-seat. Echoes what it was given; never invents a resume token.",
        "inputSchema": _schema(
            {"to": {"type": "string", "description": "harness: grok, claude, codex, cursor-agent, agy, hermes, pi"},
             "session_id": {"type": "string", "description": "chair id; identity of the seat"},
             "worktree": {"type": "string"}, "model": _MODEL_ARG,
             "title": {"type": "string"}, "effort": _EFFORT_ARG, "where": _WHERE_ARG},
            required=["to", "session_id"],
        ),
    },
    {
        "name": "join",
        "description": "Add a NEW chair: seat + boot prompt + join row with a minted inbox token (write gate). Refuses a chair id that already exists and a worktree another chair holds (C8). Does not launch; call launch for that.",
        "inputSchema": _schema(
            {"to": {"type": "string"}, "session_id": {"type": "string"}, "worktree": {"type": "string"},
             "model": _MODEL_ARG, "title": {"type": "string"}, "effort": _EFFORT_ARG,
             "where": _WHERE_ARG, "author": {"type": "string"}},
            required=["to"],
        ),
    },
    {
        "name": "launch",
        "description": "Launch one already-joined fresh chair: inside tmux a split of the caller's pane; on Windows the thread's own Windows Terminal window (wt -w convoy-<8 hex>; never window 0 unless here=true); on POSIX outside tmux with tmux installed, the thread's detached tmux session the person opens with the card's attach command; the card's placement says which. This SPAWNS a process, so it is behind the write gate and refused for a caller without a conductor bearer, without spawning anything. consent carries the user's explicit yes when the host asks for it. Never a token.",
        "inputSchema": _schema(
            {"seat": {"type": "string", "description": "chair session_id from join"},
             "consent": {"type": "string"},
             "here": {"type": "boolean", "default": False,
                      "description": "split the window you are working in (Windows: wt -w 0 split-pane; inside tmux: a split of your pane). Default is the thread's own window."}},
            required=["seat"],
        ),
    },
    {
        "name": "focus",
        "description": "Ask the pane host to highlight one chair (write gate: this is a host action). tmux: select-pane -t when a target is supplied. Windows Terminal: focused=false with reason until a pane-target adapter is evidenced. Never a token.",
        "inputSchema": _schema(
            {"seat": {"type": "string", "description": "chair session_id"},
             "target": {"type": "string", "description": "tmux pane id for select-pane -t"}},
            required=["seat"],
        ),
    },
    # N neurons -> N chairs -> ONE window -> observed connects.
    # crew replaces the join/launch/seat/bring_up walk that left chairs 2..N
    # without a boot prompt: every chair it mints carries one. seated is the
    # proof-of-life stamp a neuron makes from its pane by CLI; on the wire it
    # is how a neuron that attached by MCP (a cloud chair) proves the same.
    {
        "name": "crew",
        "description": "Validate N seats (where/model/effort, refused in the harness's own words before any write), mint one worktree per local seat from the checkout, join every chair with a boot prompt + token, and bring the crew up ONCE: one new terminal window with N panes (write gate: this writes chairs, runs git and, with launch=true, SPAWNS). launched is not connected: the card's `seated` snapshot says pending until await_seated observes each chair's ack. connect_mode per seat says how that harness receives (hook | native-queue-or-cli-drain | cli-drain); a cli-drain harness is never auto-connecting.",
        "inputSchema": _schema(
            {"seats": {"type": "array", "description": "one entry per neuron",
                       "items": _schema({"harness": {"type": "string"}, "model": _MODEL_ARG, "effort": _EFFORT_ARG,
                                         "where": _WHERE_ARG, "title": {"type": "string", "description": "seat name; default <harness>-<n>"}},
                                        required=["harness"])},
             "checkout": {"type": "string", "description": "git checkout to mint worktrees from; default the bound root"},
             "thread": {"type": "string", "description": "must match the bound thread when given"},
             "launch": {"type": "boolean", "default": False, "description": "false writes chairs + worktrees and shows the argv; true spawns the window once"}},
            required=["seats"],
        ),
    },
    {
        "name": "seated",
        "description": "Proof-of-life: the chair's new occupant echoes the token from its boot prompt (write gate: stamps kind=seated and clears the one-shot boot prompt). From a pane this is `convoy seated`; over the wire it is how a neuron attached by MCP proves it sat down. Never returns the token.",
        "inputSchema": _schema({"seat": {"type": "string"}, "token": {"type": "string"}}, required=["seat", "token"]),
    },
    {
        "name": "consent",
        "description": "Grant a prior consent request after the user explicitly approved it (write gate: mints a one-time, action-scoped grant). Pass the returned consent only to the exact pending command (launch).",
        "inputSchema": _schema({"grant": {"type": "string", "description": "request_id from the awaiting-user-consent card"}}, required=["grant"]),
    },
    {
        "name": "nudge",
        "description": "Wake one idle chair on the user's own machine (write gate: host SendInput/send-keys/queue). Requires a proven pane (panes body + unique WT title or tmux target) and a consent card that names that pane and the exact keys. delivery=nudged, never delivered. Refuses when the pane cannot be identified. Needs a conductor bearer.",
        "inputSchema": _schema(
            {"seat": {"type": "string"}, "keys": {"type": "string", "description": "exact keystroke the consent card names"},
             "target": {"type": "string", "description": "tmux pane id"},
             "dry_run": {"type": "boolean", "default": False},
             "consent": {"type": "string"}},
            required=["seat"],
        ),
    },
    {
        "name": "await_seated",
        "description": "Observe, do not trust: polls kind=seated rows for the named chairs until each has acked with the token its join/swap minted, or timeout (seconds, max 600; 0 is one snapshot). Per chair connected | pending | stale (an ack citing a token this mint never issued) and the seconds waited. Write gate: it holds the request up to timeout. Never a token.",
        "inputSchema": _schema({"seats": {"type": "array", "items": {"type": "string"}},
                                "timeout": {"type": "number", "default": 120}}, required=["seats"]),
    },
]
for _t in TOOLS:
    _props = _t.setdefault("inputSchema", {}).setdefault("properties", {})
    if _t.get("name") in {"bring_up", "open", "launch", "crew", "resume", "send"}:
        _props["allow_unverified_launch"] = {"type": "boolean", "default": False,
                                          "description": "Explicitly accept unverified harness launch eligibility for this launch; does not bypass authorization or consent"}
    if _t.get("name") in {"bring_up", "open", "launch", "crew"}:
        _props["write_repo_files"] = {"type": "boolean", "default": False,
                                      "description": "Also write the repo files a person could own (AGENTS.md) outside a worktree Convoy minted; write gate only"}
    for _k, _v in _THREAD_PROPS.items():
        _props.setdefault(_k, _v)
del _t, _props, _k, _v


def _known_threads() -> list[dict[str, Any]]:
    """Present, unhidden threads for implicit choices; hidden roots still route."""
    from .index import discoverable_threads
    out = []
    for t in discoverable_threads():
        out.append({"thread": t.get("thread"), "convoy_id": t.get("convoy_id"), "root": t.get("root"), "updated_at": t.get("updated_at")})
    return out


def _resolve_root(bound: Path | None, args: dict[str, Any], tool: str | None = None) -> Path | dict[str, Any]:
    """The root one call touches. A named thread (key or cvy_ id) wins; else the
    pinned root; else onboard's checkout_root on an unbound origin; else a refusal that
    names an argument this tool accepts and lists the choices. The
    origin serves every thread on the machine and nothing is pointed at startup."""
    want_t = _opt_str(args, "thread")
    want_id = _opt_str(args, "convoy_id")
    if want_t or want_id:
        from .index import routable_threads
        for t in routable_threads():
            if (want_t and str(t.get("thread")) == want_t) or (want_id and str(t.get("convoy_id")) == want_id):
                return Path(str(t["root"])).resolve()
        if bound is not None and want_id and read_id(bound) == want_id:
            return bound
        if bound is not None and want_t and read_thread(bound) == want_t:
            return bound
        return {"ok": False, "error": "no thread named " + str(want_t or want_id) + " on this origin (unknown, Temp, or its root is gone); see the `threads` tool",
                "threads": _known_threads()}
    if bound is not None:
        return bound
    if tool == "onboard":
        want = _opt_str(args, "checkout_root")
        if want:
            # onboard binds the thread at its checkout: that path is the route.
            return (checkout_path_for(want) if is_repo_url(want) else Path(want).expanduser()).resolve()
        return {"ok": False, "error": "this origin serves every thread on the machine; name the checkout to onboard with "
                "checkout_root=<path or git URL>, or an existing thread with convoy_id=<cvy_...> (the `threads` tool lists them)",
                "threads": _known_threads()}
    return {"ok": False, "error": "this origin serves every thread on the machine; name one with thread=<key> or convoy_id=<cvy_...> (the `threads` tool lists them)",
            "threads": _known_threads()}


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
    # effort lives on each agent row (effort_contract): the global
    # effort_types echo read as one menu for every harness and it never was.
    contract = load_harness_contract()
    return {
        "path": contract_path(),
        "schema_version": contract.get("schema_version"),
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
        # the catalog is a contract fact, not a liveness fact: read it either way
        catalog = model_catalog(hid)
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
            "models": catalog["models"],
            "models_evidence": catalog["evidence"],
            "effort": effort_contract(hid),
            "where": where_options(hid),
            "availability": availability,
            "usage_remaining": usage_remaining,
            "tracking": "off",
            "board": "off",
            "thread": thread,
            "worktree": worktree,
            "branch": branch,
            "pr": pr,
        })
    from .conductor import contract_pointer
    return {"ok": True, "agents": agents, "path": path_card, "contract": _roster_contract_view(),
            "conductor": {"to": CONDUCTOR_ID, "write_gate": _write_gate(), "bearers": _bearer.live_count(),
                          "contract": {k: x for k, x in contract_pointer(root).items() if k in ("path", "sha", "current")}}}


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


def call_tool(root: Path | None, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    if _anonymous_public():
        if name not in _PRODUCT_SURFACE:
            return _refuse_public(name)
        args = dict(arguments) if isinstance(arguments, dict) else {}
        if name == "install":
            args["dry_run"] = True
        return _public_shape(name, _call_tool(root, name, args))
    card = _call_tool(root, name, arguments)
    if not _write_tools_enabled():
        _redact_public(name, card)
    return card


def _refuse_public(name: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": name,
        "error": name + " reads or writes a thread record; on the public edge that takes identity. Mint a bearer with "
                 "`convoy conductor mint` on the origin's machine and send it as `Authorization: Bearer`. Anonymous "
                 "callers get " + ", ".join(sorted(_PRODUCT_SURFACE)) + ".",
    }


def _scrub_paths(value: Any) -> Any:
    if isinstance(value, str):
        return _PATH_RX.sub("[redacted]", value)
    if isinstance(value, list):
        return [_scrub_paths(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_paths(v) for k, v in value.items()}
    return value


def _public_shape(name: str, card: Any) -> Any:
    """The product surface as an anonymous public caller may see it: no
    enumeration of threads (a count), no filesystem path anywhere."""
    if not isinstance(card, dict):
        return card
    if name == "threads":
        rows = card.get("threads") if isinstance(card.get("threads"), list) else []
        card = {"ok": bool(card.get("ok", True)), "count": len(rows),
                "note": "anonymous callers cannot enumerate threads; name one you already know, or identify with a bearer"}
    elif isinstance(card.get("threads"), list):
        # a routing refusal lists the candidates for a local caller; here it counts them
        card = {**card, "threads": len(card["threads"])}
    return _scrub_paths(card)


def _call_tool(bound: Path | None, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    if name == "list":
        from .thread_list import thread_list
        try:
            return thread_list(all_threads=bool(args.get("all")), since=_opt_str(args, "since"))
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
    if name == "contract":
        from .conductor import CONTRACT_RELATIVE, contract_sha, contract_text
        return {"ok": True, "sha": contract_sha(), "text": contract_text(),
                "mirror": "<root>/" + CONTRACT_RELATIVE.as_posix()}
    if name == "threads":
        try:
            card = _call_tool_at(bound if bound is not None else Path.cwd(), name, args)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if isinstance(card, dict):
            card["bound"] = read_thread(bound) if bound is not None else None
            card["bound_root"] = str(bound) if bound is not None else None
        return card
    # onboard and crew take `thread` as the NAME of the thread they create or
    # validate, not as a route; for them only convoy_id routes.
    route_args = {k: v for k, v in args.items() if not (name in _THREAD_IS_A_NAME_NOT_A_ROUTE and k == "thread")}
    named = bool(_opt_str(route_args, "thread") or _opt_str(route_args, "convoy_id"))
    resolved = _resolve_root(bound, route_args, name)
    if isinstance(resolved, dict):
        return resolved
    root: Path = resolved
    try:
        card = _call_tool_at(root, name, args)
    except ValueError as exc:
        # A verb's refusal is a tool error with its text, never a bare protocol error.
        return {"ok": False, "error": str(exc)}
    # A card that was routed by name, or served by an unbound origin, says which
    # thread it touched so a conductor can never mistake one record for another.
    # A pinned call without a name keeps its CLI shape untouched.
    if isinstance(card, dict) and (named or bound is None):
        card.setdefault("thread", read_thread(root))
        card.setdefault("root", str(root))
    return card


def _call_tool_at(root: Path, name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "roster":
        return build_roster(root)
    if name == "glance":
        return build_glance(root, thread=_opt_str(args, "thread"), convoy_id=_opt_str(args, "convoy_id"), probe_fn=probe)
    if name == "onboard":
        # onboard writes the thread at the root its checkout_root resolves to.
        # This call was resolved to ONE root (pinned or named); a checkout
        # elsewhere would bind a thread this call is not about, and every later
        # card would describe the wrong place. Refuse,
        # and say to name that thread on the next call instead.
        want = _opt_str(args, "checkout_root")
        if want:
            try:
                dest = checkout_path_for(want) if is_repo_url(want) else Path(want).expanduser()
                elsewhere = dest.resolve() != Path(root).resolve()
            except OSError:
                elsewhere = True
                dest = Path(want)
            if elsewhere:
                return {"ok": False, "root": str(root), "checkout_root": str(dest), "bound": False,
                        "error": ("this endpoint is bound to " + str(root) + " and cannot bind a thread at "
                                  + str(dest) + "; clone with the `clone` tool if needed, then attach a Convoy "
                                  "endpoint whose root IS that checkout and call onboard there"),
                        "next": "attach-endpoint-at-checkout"}
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
            github=None if args.get("github") is None else _opt_bool(args, "github", False),
            probe=_opt_bool(args, "probe", False),
        )
    if name == "repos":
        if not _write_tools_enabled():
            # Refused BEFORE gh runs: no rows, null not [], nothing spawned.
            return {"ok": False, "gh_present": None, "repos": None, "count": None, "error": _gate_text("repos")}
        limit = args.get("limit")
        return list_repos(limit=int(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) else 30)
    if name == "clone":
        url = (_opt_str(args, "url") or "").strip()
        if not url:
            return {"ok": False, "cloned": False, "error": "clone requires url"}
        if not _write_tools_enabled():
            # Refused BEFORE git runs: nothing is spawned.
            return {"ok": False, "url": url, "cloned": False, "error": _gate_text("clone")}
        try:
            return clone_repo(url, checkout_path_for(url))
        except ValueError as e:
            return {"ok": False, "url": url, "cloned": False, "error": str(e)}
    if name == "mint":
        checkout = (_opt_str(args, "checkout") or "").strip()
        n = args.get("n")
        if not checkout or not isinstance(n, int) or isinstance(n, bool):
            return {"ok": False, "worktrees": [], "error": "mint requires checkout and an integer n"}
        if not _write_tools_enabled():
            return {"ok": False, "checkout": checkout, "worktrees": [], "error": _gate_text("mint")}
        names = args.get("names")
        return mint_worktrees(checkout, n, names=[str(x) for x in names] if isinstance(names, list) else None)
    if name == "terminals":
        return terminals(root, convoy_id=_opt_str(args, "convoy_id"), thread=_opt_str(args, "thread"))
    if name == "context":
        return pack(root, instance_id=_opt_str(args, "instance_id"))
    if name == "send":
        override = args.get("allow_unverified_launch", False)
        if not isinstance(override, bool):
            return {"ok": False, "error": "allow_unverified_launch must be a boolean"}
        to = _opt_str(args, "to")
        body = args.get("body")
        if not to or body is None:
            return {"ok": False, "error": "send requires to and body"}
        to = to.strip()
        if not to:
            return {"ok": False, "error": "send requires to and body"}
        if not isinstance(body, str):
            body = str(body)
        instance_id = _opt_str(args, "session_id")
        resume = _opt_str(args, "resume")
        worktree = _opt_str(args, "worktree")
        cid = read_id(root)
        if not cid:
            return {"ok": False, "error": "send requires a bound thread"}
        seats = list_seats(root, convoy_id=cid)
        exact_seat = any(row.get("session_id") == to for row in seats)
        if not exact_seat and re.fullmatch(r"n[0-9a-fA-F]{6}", to):
            resolved = resolve_neuron_id_on_thread(root, to)
            if not resolved["ok"]:
                return resolved
            sid = resolved["session_id"]
            # A blank override is an unset field, not a conflicting address.
            instance_id, resume, worktree = (
                None if value is None or not value.strip() else value
                for value in (instance_id, resume, worktree))
            if instance_id is not None and instance_id.strip() != sid:
                return {"ok": False, "error": "neuron id " + to + " conflicts with session_id"}
            if resume is not None and resume.strip() != resolved.get("resume"):
                return {"ok": False, "error": "neuron id " + to + " conflicts with resume"}
            seat_worktree = resolved.get("worktree")
            if worktree is not None and (not seat_worktree or
                    os.path.normcase(os.path.normpath(worktree)) !=
                    os.path.normcase(os.path.normpath(str(seat_worktree)))):
                return {"ok": False, "error": "neuron id " + to + " conflicts with worktree"}
            # Reuse send_one's chair resolver so its worktree, resume and git
            # pointers are identical to an address by session_id.
            to, instance_id, resume, worktree = sid, None, None, None
        elif not exact_seat and not is_wrapper_name(to):
            harness = canonical_harness_id(to)
            if harness not in {row["id"] for row in harness_entries()}:
                # Uncontracted names are typos, not new harnesses to spawn.
                return {"ok": False, "error": "no target " + to + " on this thread (not a seated session or known harness)"}
            to = harness
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
            worktree=worktree,
            allow_interactive_resume=not live,
            local_writer=False,
            allow_unverified_launch=override,
            sender=_conductor_sender(),
        )
        model = _opt_str(args, "model")
        if model is not None and card.get("model") is None:
            card["model"] = model
        return card
    if name == "graph":
        neuron = _opt_str(args, "neuron")
        try:
            return neighborhood(root, neuron) if neuron else build_graph(root)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "threads":
        if args.get("prune"):
            if not _write_tools_enabled():
                return {"ok": False, "dropped": [], "n_dropped": None, "kept": None,
                        "error": _gate_text("threads prune=true") + "; the dry list is allowed"}
            return prune_threads()
        return {"ok": True, "index": str(index_path()), "threads": list_threads()}
    if name == "panes":
        return bodies(root)
    if name == "resume":
        neuron = _opt_str(args, "neuron") or ""
        go = bool(args.get("go"))
        if go and not _write_tools_enabled():
            return {"ok": False, "neuron": neuron, "spawned": False,
                    "error": _gate_text("resume go=true") + "; the dry read is allowed"}
        try:
            return resume_neuron(root, neuron, go=go, allow_unverified_launch=args.get("allow_unverified_launch", False))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "replies":
        from .conductor import replies as _replies
        wait_raw = args.get("wait")
        wait = 0.0
        if wait_raw is not None:
            if isinstance(wait_raw, bool) or not isinstance(wait_raw, (int, float, str)):
                return {"ok": False, "rows": [], "error": "replies wait must be a number of seconds, got " + repr(wait_raw)}
            try:
                wait = float(str(wait_raw).strip())
            except ValueError:
                return {"ok": False, "rows": [], "error": "replies wait must be a number of seconds, got " + repr(wait_raw)}
            if wait > 0 and not _write_tools_enabled():
                return {"ok": False, "rows": [], "error": _gate_text("replies wait")}
        try:
            return _replies(root, _opt_str(args, "conductor") or CONDUCTOR_ID, since=_opt_str(args, "since"),
                            token=_opt_str(args, "token"), wait=wait)
        except ValueError as e:
            return {"ok": False, "rows": [], "error": str(e)}
    if name == "feed":
        since = _opt_str(args, "since") or _default_since()
        try:
            since_iso = parse_since(since)
            rows = feed_since(root, since_iso)
        except ValueError as e:
            return {"ok": False, "error": str(e), "since": since}
        return {"ok": True, "schema_version": SCHEMA_VERSION, "since": since, "since_iso": since_iso, "events": rows}
    if name == "rail":
        try:
            return build_rail(root, since=_opt_str(args, "since") or "10m", probe_fn=probe)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "provenance":
        try:
            return build_provenance(root, since=_opt_str(args, "since"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
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
                principal=_PRINCIPAL.get(),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "schema_version": SCHEMA_VERSION, **row}
    if name == "note":
        try:
            # Today's checked bearer identifies a conductor, never a neuron.
            # This hosted author's identity remains a claim until a separate
            # neuron principal exists; do not borrow the MCP server's device.
            row = neuron_note(
                root,
                str(args.get("summary") or ""),
                instance_id=_opt_str(args, "instance_id"),
                to=_opt_str(args, "to"),
            )
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        # Said on every note so no caller mistakes it for an answer the sender can count.
        return {"ok": True, "schema_version": SCHEMA_VERSION, **row, "receipt": False,
                "receipt_note": ("a claimed note does not count as a delivery receipt; the chair's own "
                                 "`convoy reply <token> \"...\"` (environment or token proof of its session) does")}
    if name in ("bring_up", "open", "launch", "crew"):
        # write_repo_files writes files a person could own into their repo: a strict boolean, and
        # only behind the write gate. Without it the card's would_write names what was left out.
        wrf = args.get("write_repo_files", False)
        if not isinstance(wrf, bool):
            return {"ok": False, "error": "write_repo_files must be a boolean"}
        if wrf and not _write_tools_enabled():
            return {"ok": False, "error": _gate_text(name + " write_repo_files=true")}
        repo_files = {"write_repo_files": True if wrf else None}
    if name in ("bring_up", "open"):
        dry = _opt_bool(args, "dry_run", True)
        if dry and repo_files["write_repo_files"]:
            # A dry call is a read: it never writes a person file or records an opt-in.
            return {"ok": False, "dry_run": True, "windows": [],
                    "error": dry_opt_in_refusal(name)}
        # dry_run=false SPAWNS: a live wt.exe on the server host. Same class
        # as the PR 50 launch hole; the read stays public, the spawn is gated
        # (found by a verifier, pre-existing on main).
        if not dry and not _write_tools_enabled():
            return {"ok": False, "dry_run": False, "spawned": False, "windows": [], "error": _gate_text(name + " dry_run=false")}
        runner = None if dry else live_runner
        previous: dict[str, Any] = {}
        if not dry:
            if _launch_launcher() is None:
                return _no_launcher({"dry_run": False, "spawned": False, "windows": []})
            previous, held = _record_mcp_launcher(root, [])
        else:
            held = {}
        spawned: list[str] = []
        try:
            card = bring_up(
                root,
                convoy_id=_opt_str(args, "convoy_id"),
                thread=_opt_str(args, "thread"),
                runner=runner,
                allow_unverified_launch=args.get("allow_unverified_launch", False),
                exclude=held or None,
                **repo_files,
            )
            spawned = [str(w.get("session_id")) for w in card.get("windows") or []
                       if isinstance(w, dict) and w.get("ok") and w.get("session_id")]
        finally:
            _settle_mcp_launcher(root, previous, spawned)
        card["dry_run"] = dry
        return card
    if name in ("hide", "minimize", "background"):
        dry = _opt_bool(args, "dry_run", True)
        mode = _opt_str(args, "mode") or "minimize"
        # dry_run=false calls ShowWindow on the host's desktop. Gated like a spawn.
        if not dry and not _write_tools_enabled():
            return {"ok": False, "dry_run": False, "applied": False, "windows": [], "error": _gate_text(name + " dry_run=false")}
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
        # A live install runs a vendor installer on the host. The catalog read
        # (dry) stays public. A live run needs BOTH the user's opt_in and the
        # write gate; opt_in is checked first so its refusal ("opt_in
        # required") reads the same on every process, gated or not.
        if not dry and not opt_in:
            return install_harness(to, dry_run=False, opt_in=False)
        if not dry and not _write_tools_enabled():
            return {"ok": False, "to": to, "dry_run": False, "ran": False, "error": _gate_text("install dry_run=false")}
        return install_harness(to, dry_run=dry, opt_in=opt_in)
    if name == "choices":
        return launch_choices(root)
    if name == "card":
        return build_card(root, listed=[t["name"] for t in _listed_tools()], probe_fn=probe)
    if name == "neurons":
        return neuron_activity(root, since=_opt_str(args, "since"))
    if name == "start_card":
        from .start_card import LINE_BUDGET, build_start_card
        # Behind the write gate the reader may hold a token; on the ungated wire, never.
        return build_start_card(root, budget=None if _opt_bool(args, "all", False) else LINE_BUDGET,
                                redact_tokens=not _write_tools_enabled())
    if name == "inbox":
        sid = (_opt_str(args, "seat") or "").strip()
        if not sid:
            return {"ok": False, "error": "inbox requires seat; the wire never guesses a chair from cwd"}
        if not _opt_bool(args, "drain", False):
            # The inbox token is the RECEIVER's proof of receipt: an ack that
            # cites it is evidence precisely because only Convoy and the target
            # know it. A public read that echoed it would let anyone forge an
            # ack. Redact it here; the chair reads its own token from disk.
            rows = [{k: v for k, v in r.items() if k != "token"} for r in pending_inbox(root, sid)]
            return {"ok": True, "seat": sid, "drained": False, "pending_count": len(rows), "pending": rows}
        if not _write_tools_enabled():
            return {"ok": False, "seat": sid, "drained": False,
                    "error": _gate_text("inbox drain=true")}
        rows = drain_inbox(root, sid)
        return {"ok": True, "seat": sid, "drained": True, "count": len(rows), "rows": rows}
    if name == "seat":
        to = _opt_str(args, "to")
        sid = _opt_str(args, "session_id")
        if not to or not sid:
            return {"ok": False, "error": "seat requires to and session_id"}
        if not _write_tools_enabled():
            return {"ok": False, "error": _gate_text("seat")}
        try:
            # seat() returns the bare row and signals failure by raising, so
            # it has no ok key. Every other tool has one; give it one.
            row = seat_chair(root, to, sid, worktree=_opt_str(args, "worktree"), model=_opt_str(args, "model"),
                             title=_opt_str(args, "title"), effort=_opt_str(args, "effort"),
                             where=_opt_str(args, "where"))
            return {"ok": True, **row}
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "join":
        to = _opt_str(args, "to")
        if not to:
            return {"ok": False, "error": "join requires to"}
        if not _write_tools_enabled():
            return {"ok": False, "error": _gate_text("join")}
        launcher = _launch_launcher()
        if launcher is None:
            return _no_launcher()
        try:
            return join_chair(root, to, session_id=_opt_str(args, "session_id"), worktree=_opt_str(args, "worktree"),
                              model=_opt_str(args, "model"), title=_opt_str(args, "title"),
                              effort=_opt_str(args, "effort"), author=_opt_str(args, "author"),
                              where=_opt_str(args, "where"), calling_session=False,
                              launched_by={"kind": "conductor", "name": launcher["name"]})
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "launch":
        sid = (_opt_str(args, "seat") or "").strip()
        if not sid:
            return {"ok": False, "spawned": False, "error": "launch requires seat"}
        if not _write_tools_enabled():
            # Refused BEFORE launch_seat is reached: nothing is spawned.
            return {"ok": False, "seat": sid, "spawned": False, "error": _gate_text("launch")}
        if _launch_launcher() is None:
            return _no_launcher({"seat": sid, "spawned": False})
        previous, held = _record_mcp_launcher(root, [sid])
        if sid in held:
            return {"ok": False, "seat": sid, "spawned": False,
                    "error": "refuse duplicate launch: " + held[sid]}
        spawned: list[str] = []
        try:
            card = launch_seat(root, sid, runner=active_pane_runner, consent=_opt_str(args, "consent"),
                               allow_unverified_launch=args.get("allow_unverified_launch", False),
                               here=bool(args.get("here", False)), **repo_files)
            spawned = [sid] if card.get("ok") else []
            return card
        except ValueError as e:
            return {"ok": False, "seat": sid, "spawned": False, "error": str(e)}
        finally:
            _settle_mcp_launcher(root, previous, spawned)
    if name == "focus":
        sid = (_opt_str(args, "seat") or "").strip()
        if not sid:
            return {"ok": False, "focused": False, "error": "focus requires seat"}
        if not _write_tools_enabled():
            return {"ok": False, "seat": sid, "focused": False, "error": _gate_text("focus")}
        return focus_seat(root, sid, target=_opt_str(args, "target"))
    if name == "crew":
        seats = args.get("seats")
        if not isinstance(seats, list) or not seats:
            return {"ok": False, "seats": [], "launched": False, "error": "crew requires seats: a non-empty list"}
        if not _write_tools_enabled():
            # Refused BEFORE validation, mint or join: no chair, no git, no window.
            return {"ok": False, "seats": [], "launched": False, "error": _gate_text("crew")}
        launch = _opt_bool(args, "launch", False)
        launcher = _launch_launcher()
        if launcher is None:
            return _no_launcher({"seats": [], "launched": False})
        return crew_chairs(root, seats, thread=_opt_str(args, "thread"), checkout=_opt_str(args, "checkout"),
                           runner=live_runner if launch else None, allow_unverified_launch=args.get("allow_unverified_launch", False),
                           launcher=launcher, **repo_files)
    if name == "seated":
        sid = (_opt_str(args, "seat") or "").strip()
        token = _opt_str(args, "token") or ""
        if not sid or not token.strip():
            return {"ok": False, "error": "seated requires seat and token"}
        if not _write_tools_enabled():
            return {"ok": False, "seat": sid, "error": _gate_text("seated")}
        try:
            row = seated_ack(root, sid, token, local_writer=False)["row"]
        except ValueError as e:
            return {"ok": False, "seat": sid, "error": str(e)}
        # the ack row carries the token it echoed; the caller supplied it, so
        # the card answers with the fact of the row, not the token again
        return {"ok": True, "seat": sid, "seated_at": row.get("ts"), "kind": row.get("kind")}
    if name == "consent":
        rid = (_opt_str(args, "grant") or "").strip()
        if not rid:
            return {"ok": False, "error": "consent requires grant: the request_id to approve"}
        if not _write_tools_enabled():
            return {"ok": False, "request_id": rid, "error": _gate_text("consent")}
        try:
            return grant_consent(root, rid)
        except ValueError as e:
            return {"ok": False, "request_id": rid, "error": str(e)}
    if name == "nudge":
        sid = (_opt_str(args, "seat") or "").strip()
        if not sid:
            return {"ok": False, "identified": False, "delivered": False, "delivery": None,
                    "error": "nudge requires seat"}
        if not _write_tools_enabled():
            return {"ok": False, "seat": sid, "identified": False, "delivered": False,
                    "delivery": None, "error": _gate_text("nudge")}
        return nudge_seat(
            root, sid,
            consent=_opt_str(args, "consent"),
            keys=_opt_str(args, "keys"),
            dry_run=_opt_bool(args, "dry_run", False),
            target=_opt_str(args, "target"),
        )
    if name == "await_seated":
        seats = args.get("seats")
        if not isinstance(seats, list) or not seats:
            return {"ok": False, "chairs": [], "error": "await_seated requires seats: a non-empty list of chair ids"}
        if not _write_tools_enabled():
            return {"ok": False, "chairs": [], "error": _gate_text("await_seated")}
        # Coerce like _opt_bool does, never default past a value the caller
        # sent: the string "0" (what an LLM client sends for the documented
        # snapshot) would fall through to 120 real seconds.
        # Out-of-schema values are refused, not replaced.
        raw = args.get("timeout")
        if raw is None:
            timeout = 120.0
        elif isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return {"ok": False, "chairs": [], "error": "await_seated timeout must be a number of seconds, got " + repr(raw)}
        else:
            try:
                timeout = float(str(raw).strip())
            except ValueError:
                return {"ok": False, "chairs": [], "error": "await_seated timeout must be a number of seconds, got " + repr(raw)}
            if timeout != timeout or timeout in (float("inf"), float("-inf")):
                return {"ok": False, "chairs": [], "error": "await_seated timeout must be finite, got " + repr(raw)}
        try:
            return await_seated(root, [str(s) for s in seats], timeout=min(max(timeout, 0.0), AWAIT_SEATED_MAX_S))
        except ValueError as e:
            return {"ok": False, "chairs": [], "error": str(e)}
    return {"ok": False, "error": "tool not found: " + name}


_WINDOW_TOOLS = frozenset({"bring_up", "open", "terminals", "hide", "minimize", "background"})


def _redact_public(name: str, card: Any) -> None:
    """Two locked contracts collide on every card that names a seat. SPEC.md:56
    makes seat.resume (the vendor session id) chip front matter for the
    conductor; graph.py:16 says tokens never leave seats.jsonl. The write gate
    is the arbiter: behind it (conductor-local loopback) the cards are whole;
    for a caller without a bearer a row carries only the shape graph already
    uses, {available, for}, so a chip can still say "resumable" and nobody
    without the bearer can lift a session id off it. The same leak applies to
    glance, terminals / bring_up / open / hide windows and the resume dry
    read, and a second one: the inbox token join/swap mint (the receiver's proof of
    receipt) rides the kind=join feed row and the boot prompt, which is the
    last argv element bring_up would exec. So argv takes the same shape (it
    is a fact here, not a payload), and feed rows drop the token key the way
    the public inbox read does. A row WITHOUT a token says available=false
    rather than omitting the key, so redaction and absence are told apart."""
    if not isinstance(card, dict):
        return
    if name == "glance":
        by_thread = card.get("by_thread")
        for row in (by_thread.get("seats") or []) if isinstance(by_thread, dict) else []:
            _redact_row(row, ("resume",))
    elif name in _WINDOW_TOOLS:
        for row in card.get("windows") or []:
            _redact_row(row, ("resume", "argv"))
    elif name == "resume" and "argv" in card:
        current = card.get("current")
        card["argv"] = _shape(card["argv"], current.get("harness") if isinstance(current, dict) else None)
    elif name == "feed":
        card["events"] = [{k: v for k, v in r.items() if k != "token"} if isinstance(r, dict) else r
                          for r in card.get("events") or []]


def _redact_row(row: Any, keys: tuple[str, ...]) -> None:
    if not isinstance(row, dict):
        return
    for key in keys:
        # resume is always answered (absence must read as available=false);
        # argv only where the card had one (hide windows never carry argv).
        if key == "resume" or key in row:
            row[key] = _shape(row.pop(key, None), row.get("to"))


def _shape(raw: Any, harness: Any) -> dict[str, Any]:
    present = (isinstance(raw, str) and bool(raw.strip())) or (isinstance(raw, list) and bool(raw))
    return {"available": present, "for": harness}


def _gate_text(verb: str) -> str:
    return (verb + " is behind the write gate: send `Authorization: Bearer <bearer>` from "
            "`convoy conductor mint` on this machine; nothing was written or spawned")


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=_json_default)


def _json_default(_o: Any) -> Any:
    return None


def handle_rpc(root: Path | None, msg: dict[str, Any], principal: dict[str, Any] | None = None, public: bool = False) -> dict[str, Any] | None:
    """Return a JSON-RPC response dict, or None for notifications.

    principal: the checked bearer record for this request ({id, conductor, label})
    or None for an anonymous caller. It is the only thing that opens the write
    tools, and `from` on conductor rows is read from it, never from an argument.
    public: the request came through a proxy or from a non-loopback peer
    (_is_public_request). Anonymous and public together means the product
    surface only."""
    token = _PRINCIPAL.set(principal)
    pub = _PUBLIC.set(bool(public))
    try:
        return _handle_rpc(root, msg)
    finally:
        _PUBLIC.reset(pub)
        _PRINCIPAL.reset(token)


def _handle_rpc(root: Path | None, msg: dict[str, Any]) -> dict[str, Any] | None:
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
            # The conductor reads this at attach: the ten rules and the pointer to
            # the full contract. A client may ignore `instructions`; glance, roster
            # and context carry the same pointer.
            try:
                from .conductor import initialize_instructions
                result["instructions"] = initialize_instructions()
            except OSError:
                pass
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
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": _listed_tools()}}
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
            elif name == "launch" and not _write_tools_enabled():
                sid = str(arguments.get("seat") or "").strip()
                payload = {"ok": False, "spawned": False, "error": _gate_text("launch")}
                if sid:
                    payload["seat"] = sid
                is_err = True
            elif name in _WRITE_TOOLS and not _write_tools_enabled():
                payload = {"ok": False, "error": "write tool refused without identity: " + name + "; " + _gate_text(name)}
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


def _log_line(text: str) -> None:
    """One line to stderr when a console exists, else to CONVOY_HOME/origin.log.
    Under pythonw (the supervised origin since #101) sys.stderr and sys.stdout
    are None; writing to them raised inside the request handler and every
    request died with EOF (a public 502). Logging must never be the
    reason a request fails, so any failure here is swallowed."""
    line = text.rstrip("\n") + "\n"
    stream = sys.stderr
    if stream is not None:
        try:
            stream.write(line)
            stream.flush()
            return
        except (OSError, ValueError, AttributeError):
            pass
    try:
        home = Path(os.environ.get("CONVOY_HOME") or (Path.home() / ".convoy"))
        home.mkdir(parents=True, exist_ok=True)
        with (home / "origin.log").open("a", encoding="utf-8") as f:
            f.write(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ ") + line)
    except OSError:
        pass


# Loopback only. A page on any site can make a browser POST to this port, and
# a DNS name that resolves to 127.0.0.1 (DNS rebinding) makes that page
# same-origin with it, so Host and Origin must name this machine's loopback on
# the listening port. A non-browser client can forge Host, so the peer must be
# loopback too, and make_server refuses to bind anything else. The checks live
# in convoy.loopback, shared with the widget's server. No response carries CORS
# headers.


class McpHandler(BaseHTTPRequestHandler):
    server_version = "convoy-mcp/" + SERVER_VERSION

    def log_message(self, fmt: str, *args: Any) -> None:
        # request line only; never log bodies or headers (secrets).
        _log_line("%s %s" % (self.address_string(), fmt % args))

    def _root(self) -> Path | None:
        r = getattr(self.server, "convoy_root", None)
        return Path(r) if r is not None else None

    def _send(self, code: int, body: bytes, content_type: str, extra: list[tuple[str, str]] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if extra:
            for k, v in extra:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def __getattr__(self, name: str) -> Any:
        # BaseHTTPRequestHandler answers 501 for a method with no do_<METHOD>,
        # before any gate runs. Route every such method through the gate: 403
        # off loopback, 405 on it.
        if name.startswith("do_"):
            return self._unsupported_method
        raise AttributeError(name)

    def _unsupported_method(self) -> None:
        if self._refused():
            return
        self._send(405, b"", "text/plain; charset=utf-8", extra=[("Allow", "POST, OPTIONS")])

    def _body_length(self) -> int:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        return max(length, 0)

    def _refused(self) -> bool:
        """Send 403 and return True unless the peer, Host and Origin are all this
        machine's loopback. Checked before identity and before the body is parsed."""
        port = int(self.server.server_address[1])
        if request_ok(self._peer(), self.headers, port, self.path):
            return False
        self._send(403, ("forbidden: this Convoy MCP answers loopback requests only (a loopback peer, "
                         "Host 127.0.0.1, localhost or [::1] on port %d, and no foreign Origin)" % port).encode("utf-8"),
                   "text/plain; charset=utf-8")
        drain_refused(self)
        return True

    def _peer(self) -> str:
        return self.client_address[0] if self.client_address else ""

    def do_OPTIONS(self) -> None:  # noqa: N802
        if self._refused():
            return
        self.send_response(204)
        self.send_header("Allow", "POST, OPTIONS")
        self.send_header("Content-Length", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self._refused():
            return
        if _is_public_request(self._peer(), self.headers):
            # Through a proxy or from another machine: nothing to read here.
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        path = urlparse(self.path).path
        if path == "/mcp":
            self._send(405, b"POST JSON-RPC to /mcp", "text/plain; charset=utf-8", extra=[("Allow", "POST, OPTIONS")])
            return
        if path in ("", "/"):
            try:
                count: Any = len(list_threads())
            except (OSError, ValueError):
                count = "unknown"
            line = HOME_LINE.format(version=_BASE_VERSION, threads=count)
            self._send(200, (line + "\n").encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self._refused():
            return
        path = urlparse(self.path).path
        if path != "/mcp":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = self._body_length()
        raw = self.rfile.read(length) if length else b""
        # Identity first: a presented bearer that does not check is a 401 before
        # any body is parsed. No header is an anonymous read-only caller. The
        # bearer itself is never logged (log_message prints the request line only).
        principal: dict[str, Any] | None = None
        presented = _bearer.parse_authorization(self.headers.get("Authorization"))
        if presented is not None:
            principal = _bearer.check(presented)
            if principal is None:
                body = _dumps({"ok": False, "error": "bearer not recognized or revoked; mint one with `convoy conductor mint` on this machine"}).encode("utf-8")
                self._send(401, body, "application/json; charset=utf-8", extra=[("WWW-Authenticate", "Bearer realm=\"convoy\"")])
                return
        try:
            msg = json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = _dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}).encode("utf-8")
            self._send(400, body, "application/json; charset=utf-8")
            return
        public = _is_public_request(self._peer(), self.headers)
        if isinstance(msg, list):
            replies = []
            for item in msg:
                if isinstance(item, dict):
                    r = handle_rpc(self._root(), item, principal=principal, public=public)
                    if r is not None:
                        replies.append(r)
            if not replies:
                self._send(202, b"", "text/plain; charset=utf-8")
                return
            payload: Any = replies
        elif isinstance(msg, dict):
            reply = handle_rpc(self._root(), msg, principal=principal, public=public)
            if reply is None:
                self._send(202, b"", "text/plain; charset=utf-8")
                return
            payload = reply
        else:
            payload = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
        body = _dumps(payload).encode("utf-8")
        extra = [("MCP-Protocol-Version", PROTOCOL_LATEST)]
        self._send(200, body, "application/json; charset=utf-8", extra=extra)


class McpHTTPServer(ExclusiveBind, ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr: tuple[str, int], root: Path | None):
        # None: this origin serves every thread the machine index knows and each
        # call names its thread. A path: pinned to that root
        # by default, a named thread still wins.
        self.convoy_root = Path(root).resolve() if root is not None else None
        if ":" in str(addr[0]):
            self.address_family = socket.AF_INET6
        super().__init__(addr, McpHandler)


def make_server(root: Path | str | None, host: str = "127.0.0.1", port: int = 8788) -> McpHTTPServer:
    """Bind the MCP on a loopback address; any other host raises ValueError."""
    host = require_loopback_bind(host)
    return McpHTTPServer((host, port), Path(root) if root is not None else None)


def serve(root: Path | str | None, host: str = "127.0.0.1", port: int = 8788) -> int:
    srv = make_server(root, host, port)
    bound_host, bound_port = srv.server_address[:2]
    scope = ("pinned to " + str(srv.convoy_root)) if srv.convoy_root is not None else "serving every thread in the machine index"
    _log_line("convoy mcp listening on http://%s:%s/mcp, %s" % (bound_host, bound_port, scope))
    # The origin loop rides inside this one supervised process.
    # Unpaired returns None and nothing starts, so a machine that never opted
    # in never polls.
    try:
        from .origin_loop import start_daemon
        if start_daemon() is not None:
            _log_line("convoy origin loop started (paired)")
    except Exception as exc:        # noqa: BLE001 - the MCP serves with or without it
        _log_line("convoy origin loop did not start: " + type(exc).__name__)
    # The wake dispatcher rides here too, after the bind: one thread per root
    # that opted in (convoy wake enable); a root that never did is never read.
    wake = None
    try:
        from .wake_service import start_daemon as start_wake
        wake = start_wake(srv.convoy_root)
    except Exception as exc:        # noqa: BLE001 - the MCP serves with or without it
        _log_line("convoy wake service did not start: " + type(exc).__name__)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if wake is not None:
            try:
                wake.stop()
            except Exception as exc:  # noqa: BLE001 - closing the listener comes first
                _log_line("convoy wake service did not stop cleanly: " + type(exc).__name__)
        srv.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m convoy.mcp_http")
    p.add_argument("--root", default=None, help="pin the origin to one thread root (default: serve every thread in the machine index; each call names its thread)")
    p.add_argument("--host", default="127.0.0.1", help="loopback address to bind: 127.0.0.1 (default), localhost or ::1; anything else is refused")
    p.add_argument("--port", type=int, default=8788)
    args = p.parse_args(argv)
    try:
        require_loopback_bind(args.host)
    except ValueError as exc:
        print("convoy mcp: " + str(exc), file=sys.stderr)
        return 2
    # No --root serves every thread in the machine index; each call names its thread.
    return serve(Path(args.root).resolve() if args.root else None, host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
