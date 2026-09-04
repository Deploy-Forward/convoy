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
from .repo import checkout_path_for, clone as clone_repo, list_repos, mint_worktrees
from .context import pack
from .convoy import list_seats, read_thread
from .activity import neuron_activity
from .convoy import seat as seat_chair
from .glance import build_glance
from .graph import build_graph, neighborhood
from .inbox import drain as drain_inbox, pending as pending_inbox
from .lifecycle import join as join_chair, seated_ack
from .consent import grant_consent
from .crew import await_seated, crew as crew_chairs
from .targeted_launch import active_pane_runner, launch_choices, launch_seat
from .graph_html import resume_neuron
from .index import index_path, list_threads
from .panes import bodies
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

# N-5 gate: SoT write tools are never exposed on an ungated public process.
# RPC-layer only — CLI and in-process call_tool stay usable; a gated/loopback
# deploy opts in via CONVOY_MCP_WRITE_TOOLS=1.
# seat/join/launch joined this set with the wizard verbs (2026-09-04). They
# are HIDDEN from a public tools/list, not listed-and-refusing, on purpose:
# the @convoy wizard's Gate 0 reads tools/list to decide whether it can seat
# and launch, and a public endpoint that cannot do those must not say it can.
# Gate 0 goes RED there and stops with an install card - fail-closed, which is
# the behaviour the wizard promises. inbox stays listed: its read is public;
# only drain is gated, inside the handler, like resume go=true.
# onboard joined (2026-09-04, item D): it binds the thread (writes .convoy/)
# and, given a URL, SPAWNS git clone. clone and mint spawn git outright.
# repos joined after review the same day: `gh repo list` runs as whoever is
# logged in on the MCP HOST, so on a public deploy it could only hand the
# operator's inventory (private names included) to strangers and spend
# their API quota. It is the conductor's account; the gate says so.
# crew / seated / consent joined 2026-09-04 (item E): crew mints worktrees,
# joins N chairs and may spawn the window; seated stamps a chair's proof of
# life; consent mints a one-time grant. await_seated only reads, but it holds
# the request thread up to its timeout, which a public endpoint must not offer.
_WRITE_TOOLS = frozenset({"stamp", "note", "seat", "join", "launch", "onboard", "clone", "mint", "repos",
                          "crew", "seated", "consent", "await_seated"})
AWAIT_SEATED_MAX_S = 600.0


def _write_tools_enabled() -> bool:
    return os.environ.get("CONVOY_MCP_WRITE_TOOLS", "").strip() == "1"


# No enum here on purpose: the vocabulary is per harness (grok xhigh, codex
# extra-high, pi --thinking levels). The handler refuses a value the named
# harness does not take and the error lists that harness's real keys.
_EFFORT_ARG = {
    "type": "string",
    "description": "declared effort, validated for the named harness; valid keys are choices.harnesses[].effort.keys, refused otherwise naming them. Reaches argv only where effort.applied is true.",
}
# Model is checked the same way, against choices.harnesses[].models. That
# catalog is null wherever no local --help enumerates a closed list (live
# 2026-09-04: every harness), and null accepts anything — a field, not a menu.
_MODEL_ARG = {
    "type": "string",
    "description": "declared model, passed through as typed when choices.harnesses[].models is null; when that catalog is a list, a model outside it is refused naming the list.",
}
# where IS a closed axis, so an enum is honest here. cloud is refused per
# harness unless choices.harnesses[].where.cloud.offered is true (only an
# evidenced interactive attach; live 2026-09-04: claude --cloud).
_WHERE_ARG = {
    "type": "string",
    "enum": ["local", "cloud"],
    "description": "local (default) or cloud. cloud is accepted only where choices.harnesses[].where.cloud.offered is true, refused otherwise naming that harness's cloud mode and evidence. A cloud chair has no worktree, and no launcher exists for it yet.",
}

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
            },
            required=["to"],
        ),
    },
    # The repository step (2026-09-04, item D). repos reads names and URLs
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
        "description": "Packed pointers only (thread.md, role.md, brief, handoff, instance_id, worktree, branch, pr) plus convoy_id/thread_key from .convoy one-line files. Not file contents.",
        "inputSchema": _schema({
            "instance_id": {"type": "string"},
        }),
    },
    {
        "name": "send",
        "description": "Headless synapse; does not pop a TUI. Naming a live seat queues the body (delivery=queued, delivered=false) instead of spawning a second --resume. Codex may native-queue. Fake ACKs are recorded, not delivered. live=true still never steals a TUI. Refuses limited without waiting.",
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
        "description": "Every Convoy thread this machine's index knows (convoy_id, thread, root, updated_at). present=false when the root is gone or its id changed; never a token.",
        "inputSchema": _schema({}),
    },
    {
        "name": "resume",
        "description": "Resume one neuron at its most recent place: native argv + cwd + place card. Dry by default (no spawn). go=true spawns once and is refused on an ungated public process; it also refuses when a live body holds the chair or the chair has no token for its current harness (then launch --seat).",
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
    # The six verbs below were CLI-only until grok-bot's PR 50 review
    # (2026-09-04 ~06:00Z): the @convoy wizard's Gate 0 requires them from the
    # LIVE tools/list and goes RED otherwise, so redeploying the old server
    # could never make the wizard green. Read-only verbs answer anywhere.
    # Anything that mutates the thread or SPAWNS sits behind the same write
    # gate as `resume go=true`: a public endpoint never mints a chair or starts
    # a process on a stranger's behalf.
    {
        "name": "choices",
        "description": "Read-only: installed harnesses, known git worktrees, current seats, and whether this host can split an active pane. The wizard renders ONLY what this returns; never a remembered menu. Never a token.",
        "inputSchema": _schema({}),
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
        "description": "Split one already-joined fresh chair into the active pane host. This SPAWNS a process, so it is behind the write gate and refused on a public deploy without spawning anything. consent carries the user's explicit yes when the host asks for it. Never a token.",
        "inputSchema": _schema(
            {"seat": {"type": "string", "description": "chair session_id from join"},
             "consent": {"type": "string"}},
            required=["seat"],
        ),
    },
    # N neurons -> N chairs -> ONE window -> observed connects (2026-09-04, item E).
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
        "name": "await_seated",
        "description": "Observe, do not trust: polls kind=seated rows for the named chairs until each has acked with the token its join/swap minted, or timeout (seconds, max 600; 0 is one snapshot). Per chair connected | pending | stale (an ack citing a token this mint never issued) and the seconds waited. Write gate: it holds the request up to timeout. Never a token.",
        "inputSchema": _schema({"seats": {"type": "array", "items": {"type": "string"}},
                                "timeout": {"type": "number", "default": 120}}, required=["seats"]),
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
    card = _call_tool(root, name, arguments)
    if not _write_tools_enabled():
        _redact_public(name, card)
    return card


def _call_tool(root: Path, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
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
            github=None if args.get("github") is None else _opt_bool(args, "github", False),
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
    if name == "graph":
        neuron = _opt_str(args, "neuron")
        try:
            return neighborhood(root, neuron) if neuron else build_graph(root)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "threads":
        return {"ok": True, "index": str(index_path()), "threads": list_threads()}
    if name == "panes":
        return bodies(root)
    if name == "resume":
        neuron = _opt_str(args, "neuron") or ""
        go = bool(args.get("go"))
        if go and not _write_tools_enabled():
            return {"ok": False, "neuron": neuron, "spawned": False,
                    "error": "resume go=true is behind the write gate on this process (set CONVOY_MCP_WRITE_TOOLS=1 on a gated/loopback deploy); dry read allowed"}
        try:
            return resume_neuron(root, neuron, go=go)
        except ValueError as e:
            return {"ok": False, "error": str(e)}
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
    if name == "choices":
        return launch_choices(root)
    if name == "neurons":
        return neuron_activity(root, since=_opt_str(args, "since"))
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
        try:
            return join_chair(root, to, session_id=_opt_str(args, "session_id"), worktree=_opt_str(args, "worktree"),
                              model=_opt_str(args, "model"), title=_opt_str(args, "title"),
                              effort=_opt_str(args, "effort"), author=_opt_str(args, "author"),
                              where=_opt_str(args, "where"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if name == "launch":
        sid = (_opt_str(args, "seat") or "").strip()
        if not sid:
            return {"ok": False, "spawned": False, "error": "launch requires seat"}
        if not _write_tools_enabled():
            # Refused BEFORE launch_seat is reached: nothing is spawned.
            return {"ok": False, "seat": sid, "spawned": False, "error": _gate_text("launch")}
        try:
            return launch_seat(root, sid, runner=active_pane_runner, consent=_opt_str(args, "consent"))
        except ValueError as e:
            return {"ok": False, "seat": sid, "spawned": False, "error": str(e)}
    if name == "crew":
        seats = args.get("seats")
        if not isinstance(seats, list) or not seats:
            return {"ok": False, "seats": [], "launched": False, "error": "crew requires seats: a non-empty list"}
        if not _write_tools_enabled():
            # Refused BEFORE validation, mint or join: no chair, no git, no window.
            return {"ok": False, "seats": [], "launched": False, "error": _gate_text("crew")}
        launch = _opt_bool(args, "launch", False)
        return crew_chairs(root, seats, thread=_opt_str(args, "thread"), checkout=_opt_str(args, "checkout"),
                           runner=live_runner if launch else None)
    if name == "seated":
        sid = (_opt_str(args, "seat") or "").strip()
        token = _opt_str(args, "token") or ""
        if not sid or not token.strip():
            return {"ok": False, "error": "seated requires seat and token"}
        if not _write_tools_enabled():
            return {"ok": False, "seat": sid, "error": _gate_text("seated")}
        try:
            row = seated_ack(root, sid, token)["row"]
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
    if name == "await_seated":
        seats = args.get("seats")
        if not isinstance(seats, list) or not seats:
            return {"ok": False, "chairs": [], "error": "await_seated requires seats: a non-empty list of chair ids"}
        if not _write_tools_enabled():
            return {"ok": False, "chairs": [], "error": _gate_text("await_seated")}
        raw = args.get("timeout")
        timeout = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 120.0
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
    on the ungated public wire a row carries only the shape graph already
    uses, {available, for}, so a chip can still say "resumable" and nobody
    can lift a session id off a public endpoint. glance found live 2026-09-04
    (3b18a8e); adversarial review the same day reproduced the identical leak
    on terminals / bring_up / open / hide windows and the resume dry read, and
    a second one: the inbox token join/swap mint (the receiver's proof of
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
    return (verb + " is behind the write gate on this process (set CONVOY_MCP_WRITE_TOOLS=1 "
            "on a gated/loopback deploy); nothing was written or spawned")


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
            elif name == "launch" and not _write_tools_enabled():
                sid = str(arguments.get("seat") or "").strip()
                payload = {"ok": False, "spawned": False, "error": _gate_text("launch")}
                if sid:
                    payload["seat"] = sid
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
