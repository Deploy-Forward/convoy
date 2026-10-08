"""crew: N neurons -> N chairs -> ONE window -> they all connect, observed.

The wizard's old sequence (join + launch for chair 1, `seat` for chairs 2..N,
bring_up) left chairs 2..N with no boot prompt - `seat` never writes one - so
those panes came up with a bare harness argv and nobody told them to connect.
crew joins EVERY chair (boot prompt + token), mints
one worktree per local chair from the checkout, and launches once through
bring_up: one wt window, N panes, never launch_seat per chair.

Launched is not connected. await_seated reads kind=seated rows back and calls
a chair connected only when its ack cites the token this mint issued; the
time waited is measured on an injectable clock so the suite never sleeps.

add is the one-neuron verb: the same validate -> mint -> join for one chair,
then the TARGETED launch (inside tmux a split of the caller's pane; on Windows the
thread's own named Windows Terminal window; else the thread's detached tmux
session) instead of a whole new window, which it uses only as the fallback.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from .refusal import next_step
from .bringup import Runner, bring_up, codex_hooks_warning, pane_host_available
from .convoy import list_seats, read_id, read_thread
from .harness_contract import (canonical_harness_id, harness_entries, validate_effort, validate_launch_eligibility,
                               validate_model, validate_where)
from .inbox import connect_mode
from .layer import feed_since
from .lifecycle import join
from .repo import _SEAT_NAME, Runner as GitRunner, mint_worktrees, minted_worktree_path
from .targeted_launch import (Runner as PaneRunner, Which, active_pane_argv, grok_project_trusted, launch_seat,
                              placement_capability, terminal_capability, tmux_attach_command)

EPOCH = "1970-01-01T00:00:00.000000Z"
STATES = ("connected", "pending", "stale")


# A duplicate crew chair names the way to a new one (linted by printed_commands_test).
CREW_NEW_TITLE = next_step("crew", "--seat", "<harness>,title=<name>")

# crew --count: one SPEC repeated N times, at most this many per call.
CREW_COUNT_MAX = 16
CREW_COUNT_CAP = ("crew --count is capped at " + str(CREW_COUNT_MAX) +
                  " per call; run crew again on the same thread for more")
# --here splits the person's own window: one tab of at most four panes.
CREW_HERE_MAX = 4
CREW_HERE_CAP = ("--here takes at most " + str(CREW_HERE_MAX) +
                 " neurons; drop --here to open them in the thread's window in tabs")
# crew --brief waits this long for every chair to seat before sending.
BRIEF_TIMEOUT_S = 300.0
# A crew of several launches its first neuron alone and waits this long for it to seat.
CANARY_TIMEOUT_S = 120.0


def expand_count(seats: list[dict[str, Any]], count: Any) -> list[dict[str, Any]]:
    """`count` repeats the one seat SPEC N times: titles <harness>-<i>, or <title>-<i>
    when the SPEC names a title. None leaves the seats as given. Raises ValueError
    (nothing written yet) for a count beside more than one seat, or outside 1..16."""
    if count is None:
        return seats
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("crew count must be an integer 1.." + str(CREW_COUNT_MAX) + ", got " + repr(count))
    if not isinstance(seats, list) or len(seats) != 1 or not isinstance(seats[0], dict):
        raise ValueError("crew count repeats exactly one seat SPEC; give one --seat with --count")
    if count < 1:
        raise ValueError("crew count must be an integer 1.." + str(CREW_COUNT_MAX) + ", got " + repr(count))
    if count > CREW_COUNT_MAX:
        raise ValueError(CREW_COUNT_CAP)
    spec = seats[0]
    stem = str(spec.get("title") or "").strip() or canonical_harness_id(spec.get("harness"))
    return [{**spec, "title": str(stem) + "-" + str(i)} for i in range(1, count + 1)]


def brief_prefix(i: int, n: int, thread: Any, crew_id: Any) -> str:
    """The one line each neuron's copy of a crew brief starts with."""
    return ("You are neuron " + str(i) + " of " + str(n) + " on thread " + str(thread) + " (crew " + str(crew_id) +
            "). Coordinate through Convoy notes; claim your share before starting.")


def _plan(root: Path, seats: list[dict[str, Any]], bound: str | None) -> list[dict[str, Any]]:
    """Validate every seat before anything is written. A refusal here names
    the field in the harness's own words (validate_* do that) and leaves the
    thread untouched."""
    if not isinstance(seats, list) or not seats:
        raise ValueError("crew requires seats: a non-empty list of {harness, model?, effort?, where?, title?}")
    known = {row["id"] for row in harness_entries()}
    existing = {str(s.get("session_id") or "") for s in list_seats(root)}
    plan: list[dict[str, Any]] = []
    names: set[str] = set()
    for i, raw in enumerate(seats):
        spec = raw if isinstance(raw, dict) else {}
        # `harness` only: the MCP schema names one key, and an undocumented
        # alias is a second spelling the card never told the host about.
        harness = canonical_harness_id(spec.get("harness"))
        if harness not in known:
            raise ValueError("refuse seat " + str(i + 1) + ": unknown harness " + repr(spec.get("harness")) +
                             "; choices.harnesses lists " + ", ".join(sorted(known)))
        where = validate_where(harness, spec.get("where"))
        model = validate_model(harness, spec.get("model"))
        effort = validate_effort(harness, spec.get("effort"))
        title = str(spec.get("title") or "").strip()
        name = title or (harness + "-" + str(i + 1))
        if name in names:
            raise ValueError("refuse seat " + str(i + 1) + ": name " + repr(name) + " used twice in this crew")
        names.add(name)
        sid = name + "-" + (bound or "thread")
        if sid in existing:
            raise ValueError("refuse seat " + str(i + 1) + ": chair already exists: " + sid +
                             "; give it another title (" + CREW_NEW_TITLE.replace("<harness>", harness) + ")")
        plan.append({"harness": harness, "where": where, "model": model, "effort": effort,
                     "title": name, "session_id": sid})
    return plan


def crew(
    root: Path,
    seats: list[dict[str, Any]],
    *,
    thread: str | None = None,
    checkout: Path | str | None = None,
    runner: Runner | None = None,
    mint_runner: GitRunner | None = None,
    author: str | None = None,
    allow_unverified_launch: bool = False,
    write_repo_files: bool | None = None,
    launcher: dict[str, Any] | None = None,
    count: Any = None,
    brief: str | None = None,
    brief_timeout: float = BRIEF_TIMEOUT_S,
    brief_sender: dict[str, Any] | None = None,
    brief_local_writer: bool = True,
    here: bool = False,
    canary: bool = False,
    canary_timeout: float = CANARY_TIMEOUT_S,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = time.sleep,
) -> dict[str, Any]:
    """Validate -> mint -> join each -> bring_up once. runner=None joins the
    chairs and shows the argv without spawning; live_runner pops the window.
    checkout defaults to the root (onboard binds the thread there).

    count repeats the one seat SPEC (expand_count). brief, after a launch, waits
    for every chair to seat (await_seated, brief_timeout) and sends each seated
    neuron its prefixed copy through send_one, the path `convoy send` takes: one
    token per neuron, never typed into a pane. Without a launch the card carries
    the planned briefs and nothing is sent. here splits the person's own window
    (wt -w 0) and takes at most four neurons.

    canary (the CLI and MCP default; off here so a direct caller opts in): a live
    crew of more than one local neuron launches the first alone, waits for it to
    seat (canary_timeout), and only then launches the rest, continuing the layout
    from the canary's pane. A canary that does not seat, or whose harness exits,
    stops the rest: their chairs stay joined, marked launched=false,
    reason=canary_failed, and the card's ok is false."""
    root = Path(root)
    bound = read_thread(root)
    # launched starts False and is read from the runner's RESULT after bring_up.
    # It was `runner is not None`, so a crew refused before any write, with a
    # live runner handed in, claimed to have acted.
    card: dict[str, Any] = {"ok": False, "convoy_id": read_id(root), "thread": bound, "seats": [], "launched": False}
    try:
        seats = expand_count(seats, count)
        if brief is not None and (not isinstance(brief, str) or not brief.strip()):
            raise ValueError("crew brief must be non-empty text")
        if here and isinstance(seats, list) and len(seats) > CREW_HERE_MAX:
            raise ValueError(CREW_HERE_CAP)
    except ValueError as e:
        card["error"] = str(e)
        return card
    if card["convoy_id"] is None:
        card["error"] = "crew requires a bound thread root (onboard, or init + bind)"
        return card
    if thread is not None and bound != thread:
        card["error"] = "thread mismatch: root is bound to " + repr(bound) + ", not " + repr(thread)
        return card
    try:
        plan = _plan(root, seats, bound)
        if runner is not None:
            for p in plan:
                if p["where"] == "local":
                    validate_launch_eligibility(p["harness"], allow_unverified_launch=allow_unverified_launch)
    except ValueError as e:
        card["error"] = str(e)
        return card
    from .launcher import refusal
    refused = refusal(launcher)
    if refused:
        card.update(refused)
        return card   # before any write: no worktree, no chair, no claim, no lead change
    if runner is not None and not pane_host_available():
        card["error"] = "no pane host (wt) on PATH; refuse mint and join"
        return card
    sids = _mint_and_join(card, root, plan, checkout=checkout, mint_runner=mint_runner, author=author)
    if sids is None:
        return _warn_codex_hooks(card, plan)
    if not _seat_launcher(card, root, launcher, sids):
        return _warn_codex_hooks(card, plan)
    local = [sid for sid, p in zip(sids, plan) if p["where"] == "local"]
    if canary and runner is not None and len(local) > 1:
        card = _canary_then_rest(card, root, sids, local[0], bound, runner=runner,
                                 allow_unverified_launch=allow_unverified_launch, write_repo_files=write_repo_files,
                                 here=here, timeout=canary_timeout, clock=clock, sleep=sleep)
    else:
        card = _bring_up_window(card, root, sids, bound, runner=runner, allow_unverified_launch=allow_unverified_launch,
                                write_repo_files=write_repo_files, here=here)
        if canary and runner is None and len(local) > 1:
            # A dry pass waits for nobody; it says what a launch would do first.
            card["canary_plan"] = {"session_id": local[0], "timeout_s": float(canary_timeout),
                                   "then": "the other " + str(len(sids) - 1) + " launch once it is seated, "
                                           "continuing planned_argv from pane 2"}
    if brief is not None:
        _brief(card, root, sids, brief, live=runner is not None, timeout=brief_timeout, sender=brief_sender,
               local_writer=brief_local_writer, clock=clock, sleep=sleep)
    return _warn_codex_hooks(card, plan)


def _harness_exit(root: Path, sid: str) -> dict[str, Any] | None:
    """The pane host's exit row for this chair (kind=pane with an exit code), if any.
    A chair this crew just joined has no earlier life, so any such row is this one."""
    hit = None
    for r in feed_since(root, EPOCH):
        if r.get("kind") == "pane" and r.get("instance_id") == sid and r.get("exit") is not None:
            hit = r
    return hit


def _await_canary(root: Path, sid: str, *, timeout: float, clock: Callable[[], float],
                  sleep: Callable[[float], Any], interval: float = 1.0) -> dict[str, Any]:
    """await_seated for one chair, one pass at a time, also stopping at the pane
    host's harness-exit row: a canary whose harness died will never seat."""
    budget = max(0.0, float(timeout))
    start = clock()
    while True:
        snap = await_seated(root, [sid], timeout=0)
        waited = max(0.0, clock() - start)
        if snap.get("ok"):
            return {"ok": True, "session_id": sid, "seated": True, "waited_s": round(waited, 3)}
        dead = _harness_exit(root, sid)
        if dead is not None:
            tail = str(dead.get("stderr_tail") or "").strip()
            return {"ok": False, "session_id": sid, "seated": False, "waited_s": round(waited, 3),
                    "error": "canary " + sid + ": harness exited " + str(dead.get("exit")) + (": " + tail if tail else "")}
        state = (snap.get("chairs") or [{}])[0].get("state")
        if waited >= budget:
            return {"ok": False, "session_id": sid, "seated": False, "waited_s": round(waited, 3),
                    "error": "canary " + sid + ": not seated within " + str(budget) + " s (state " + str(state) + ")"}
        sleep(min(interval, budget - waited))


def _canary_then_rest(card: dict[str, Any], root: Path, sids: list[str], first: str, bound: str | None, *,
                      runner: Runner, allow_unverified_launch: bool, write_repo_files: bool | None, here: bool,
                      timeout: float, clock: Callable[[], float], sleep: Callable[[float], Any]) -> dict[str, Any]:
    """Launch `first` alone, wait for it to seat, then launch the rest as pane 2.. of
    the same layout. The model ids a crew passes are not verified before launch; one
    neuron that cannot start costs one pane instead of N."""
    rest = [sid for sid in sids if sid != first]
    card = _bring_up_window(card, root, [first], bound, runner=runner, allow_unverified_launch=allow_unverified_launch,
                            write_repo_files=write_repo_files, here=here)
    canary_windows = list(card.get("windows") or [])
    if card.get("launched"):
        verdict = _await_canary(root, first, timeout=timeout, clock=clock, sleep=sleep)
    else:
        verdict = {"ok": False, "session_id": first, "seated": False, "waited_s": 0.0,
                   "error": "canary " + first + ": launch failed: " + str(card.get("error") or "terminal adapter failed")}
    card["canary"] = verdict
    if verdict["ok"]:
        card = _bring_up_window(card, root, rest, bound, runner=runner, allow_unverified_launch=allow_unverified_launch,
                                write_repo_files=write_repo_files, here=here, tile_offset=1, tile_total=len(sids))
        card["windows"] = canary_windows + list(card.get("windows") or [])
        card["seated"] = await_seated(root, sids, timeout=0)
        return card
    # The rest stay joined and unlaunched: say so per chair, and how to launch each one.
    card["warnings"] = list(card.get("warnings") or []) + [verdict["error"]]
    card["seats"] = [{**s, "launched": False, "reason": "canary_failed"} if s.get("session_id") in rest else s
                     for s in card.get("seats") or []]
    card["ok"] = False
    card["error"] = verdict["error"] + "; the other chairs were not launched"
    card["not_launched"] = [{"session_id": sid, "launched": False, "reason": "canary_failed"} for sid in rest]
    recovery = [r for r in card.get("recovery") or [] if r.get("session_id") == first]
    card["recovery"] = recovery + [{"session_id": sid, "verb": "launch --seat " + sid} for sid in rest]
    card["seated"] = await_seated(root, sids, timeout=0)
    card["next"] = "launch"
    return card


def _brief(card: dict[str, Any], root: Path, sids: list[str], brief: str, *, live: bool, timeout: float,
           sender: dict[str, Any] | None, local_writer: bool, clock: Callable[[], float],
           sleep: Callable[[float], Any]) -> dict[str, Any]:
    """One brief, N prefixed copies. Live: wait for the seats, then send each seated
    neuron its copy the way `convoy send` does (send_one, fake_runner: the chair's
    inbox, a token, delivered=false). A chair that did not seat gets no send and a
    warning, and ok stays true only when every chair seated and every send landed.
    Not live: the planned copies, nothing sent."""
    from .activity import neuron_id
    from .synapse import fake_runner, send_one
    n = len(sids)
    worktrees = {str(s.get("session_id")): s.get("worktree") for s in card.get("seats") or []}
    crew_id = sids[0] if sids else None
    copies = [brief_prefix(i, n, card.get("thread"), crew_id) + "\n" + brief for i in range(1, n + 1)]
    rows = [{"neuron_id": neuron_id(card.get("convoy_id"), sid), "session_id": sid, "worktree": worktrees.get(sid),
             "send_token": None, "seated": False} for sid in sids]
    card["briefs"] = rows
    warnings: list[str] = []
    if not live:
        for row, text in zip(rows, copies):
            row["brief"] = text
        card["brief_sent"] = False
        card["brief_note"] = "planned only: crew without --launch sends no brief"
        return card
    if not card.get("launched") or (card.get("canary") or {}).get("ok") is False:
        warnings.append("brief not sent: the crew did not launch")
        card["brief_sent"] = False
        card["warnings"] = list(card.get("warnings") or []) + warnings
        card["ok"] = False
        return card
    waited = await_seated(root, sids, timeout=timeout, clock=clock, sleep=sleep)
    card["seated"] = waited
    connected = set(waited.get("connected") or [])
    all_ok = True
    for row, text in zip(rows, copies):
        sid = row["session_id"]
        if sid not in connected:
            all_ok = False
            warnings.append(sid + ": not seated within " + str(waited.get("timeout_s")) + " s; brief not sent")
            continue
        row["seated"] = True
        sent = send_one(root, sid, text, runner=fake_runner, allow_interactive_resume=True, sender=sender,
                        local_writer=local_writer)
        row["send_token"] = sent.get("token")
        row["delivery"] = sent.get("delivery")
        if not sent.get("ok") or not sent.get("token"):
            all_ok = False
            warnings.append(sid + ": brief send failed: " + str(sent.get("error") or "no token"))
    card["brief_sent"] = any(r["send_token"] for r in rows)
    if warnings:
        card["warnings"] = list(card.get("warnings") or []) + warnings
    card["ok"] = bool(card.get("ok")) and all_ok
    return card


def _warn_codex_hooks(card: dict[str, Any], plan: list[dict[str, Any]]) -> dict[str, Any]:
    """A codex chair whose plugin hooks the person has not trusted cannot be woken by a send:
    no Stop hook records its session id, so `codex queue` has no thread to reach. Read-only."""
    warning = codex_hooks_warning(p["harness"] for p in plan)
    if warning and warning not in (card.get("warnings") or []):
        card["warnings"] = list(card.get("warnings") or []) + [warning]
    return card


def _seat_launcher(card: dict[str, Any], root: Path, launcher: dict[str, Any] | None, sids: list[str]) -> bool:
    """Act on the resolved launcher once every chair has joined (a refused or failed verb
    attaches nobody and moves no lead): the card's `launcher` block, a warning when it is
    unknown, and launched_by on each joined chair, whose prompt then names it."""
    if launcher is None or not sids:
        return True
    from .launcher import UNPROVEN_NEXT, public_block, seat_launcher
    from .lifecycle import record_launcher
    try:
        info = seat_launcher(root, launcher)
    except ValueError as exc:
        # The launcher proved its session but could not attach: nothing is launched, and
        # the joined chairs keep no launcher (`convoy adopt` names one later).
        card.update(ok=False, error=str(exc), next=UNPROVEN_NEXT)
        return False
    card["launcher"] = public_block(info)
    if info.get("warning"):
        card["warnings"] = list(card.get("warnings") or []) + [info["warning"]]
    rows = {sid: record_launcher(root, sid, info.get("launched_by"), info.get("launched_by_why")) for sid in sids}
    keys = ("launched_by", "launched_by_why", "boot_prompt")
    card["seats"] = [{**s, **{k: rows[s["session_id"]].get(k) for k in keys}} if s.get("session_id") in rows else s
                     for s in card.get("seats") or []]
    return True


def _mint_and_join(card: dict[str, Any], root: Path, plan: list[dict[str, Any]], *, checkout: Path | str | None,
                   mint_runner: GitRunner | None, author: str | None) -> list[str] | None:
    """Mint one worktree per local chair, then join each with its boot prompt.
    Returns the joined session ids, or None with card["error"] set."""
    base = Path(checkout) if checkout else root
    card["checkout"] = str(base)
    local = [p for p in plan if p["where"] == "local"]
    minted: dict[str, str] = {}
    if local:
        mint = mint_worktrees(base, len(local), names=[p["title"] for p in local], runner=mint_runner)
        card["mint"] = mint
        if not mint.get("ok"):
            card["error"] = "mint refused: " + str(mint.get("error"))
            return None
        minted = {row["name"]: row["path"] for row in mint["worktrees"]}
    else:
        card["mint"] = {"ok": True, "checkout": str(base), "worktrees": []}
    for p in plan:
        try:
            joined = join(root, p["harness"], session_id=p["session_id"], worktree=minted.get(p["title"]),
                          model=p["model"], title=p["title"], effort=p["effort"], author=author, where=p["where"],
                          calling_session=False)
        except ValueError as e:
            card["error"] = "join refused for " + p["session_id"] + ": " + str(e) + " (" + str(len(card["seats"])) + " chairs already joined)"
            if card["seats"]:
                _mark_partial(card, root, [s["session_id"] for s in card["seats"]], card["error"])
            return None
        card["seats"].append({**joined["seat"], "token": joined["token"], "connect_mode": connect_mode(p["harness"])})
    return [s["session_id"] for s in card["seats"]]


def _bring_up_window(card: dict[str, Any], root: Path, sids: list[str], bound: str | None, *, runner: Runner | None,
                     allow_unverified_launch: bool, write_repo_files: bool | None,
                     retry: str = "launch --seat {sid}", here: bool = False, tile_offset: int = 0,
                     tile_total: int | None = None) -> dict[str, Any]:
    """Launch the joined chairs once through bring_up: one new window, N panes
    (here: a split of the person's own window instead)."""
    try:
        up = bring_up(root, thread=bound, runner=runner, session_ids=sids, allow_unverified_launch=allow_unverified_launch,
                      write_repo_files=write_repo_files, here=here, plan_argv=runner is None,
                      tile_offset=tile_offset, tile_total=tile_total)
    except OSError as e:
        return _mark_partial(card, root, sids, "launch failed: " + str(e), retry=retry)
    card["windows"] = up.get("windows") or []
    card["cloud"] = up.get("cloud") or []
    for k in ("planned_argv", "planned_argv_error"):
        if k in up:
            card[k] = up[k]
    # Seats can launch with dead hook files (the resolver found no hook-shell
    # interpreter that imports convoy); a card silent about that lets a caller
    # report "live" seats whose every tool is refused. Per-window errors ride
    # the card as warnings.
    warnings: list[str] = []
    for w in card["windows"]:
        if not isinstance(w, dict):
            continue
        for k in ("inbox_hook_error", "identity_error"):
            if w.get(k):
                warnings.append(str(w.get("session_id") or "?") + ": " + k + ": " + str(w[k]))
    if warnings:
        # The window's own warnings first; one already on the card (the launcher's) stays.
        card["warnings"] = warnings + [w for w in card.get("warnings") or [] if w not in warnings]
    if up.get("error"):
        card["error"] = str(up["error"])
    else:
        # bring_up records a failed spawn per window and drops top-level ok;
        # the crew card carries the first window's reason itself so a caller
        # does not have to dig windows[i] to learn the terminal never opened.
        failed = [w for w in card["windows"] if isinstance(w, dict) and w.get("ok") is False and w.get("error")]
        if failed:
            card["error"] = "launch failed: " + str(failed[0]["error"])
    # launched is what the runner reported, not what we hoped: a dry pass
    # (runner None) never launched, and a runner that returned ok=False or
    # failed a window did not either.
    card["launched"] = runner is not None and bool(up.get("ok")) and all(
        bool(w.get("ok", True)) for w in card["windows"] if isinstance(w, dict))
    # A snapshot, not a wait: right after launch every chair is pending, and
    # the card says so instead of implying the panes connected.
    card["seated"] = await_seated(root, sids, timeout=0)
    card["ok"] = bool(up.get("ok"))
    card["next"] = "await_seated"
    if not card["ok"] and sids:
        _mark_partial(card, root, sids, str(card.get("error") or "launch failed"), retry=retry)
    return card


def _auto(value: Any) -> str | None:
    """Blank and "auto" both mean: pass no flag, so the harness picks its own default."""
    text = str(value).strip() if isinstance(value, str) else ""
    return None if not text or text.lower() == "auto" else text


def _placement(env: Mapping[str, str] | None, which: Which, platform_name: str | None,
               window: str | None = None, here: bool = False) -> tuple[str, str]:
    """Where one new neuron goes, decided before anything is written:
    here | split | thread-window | detached | none, with the reason the card shows.
    `here` is the person's opt-in to split the window they are working in."""
    cap = terminal_capability(env=env, which=which, platform_name=platform_name, here=here)
    if here:
        if cap.get("can_split"):
            return "here", "inside tmux: a split of the caller's exact pane (--here)"
        if cap.get("here"):
            return "here", "Windows Terminal: a split of the window you are working in (wt -w 0 split-pane, --here)"
        return "none", str(cap.get("reason"))
    if cap.get("can_split"):
        return "split", "inside tmux: a split of the caller's exact pane"
    if cap.get("thread_window"):
        return "thread-window", ("Windows Terminal: this thread's own window " + str(window) +
                                 "; the first neuron opens it as a tab, later ones split inside it"
                                 " (never the caller's window)")
    if cap.get("detached"):
        return "detached", ("not inside tmux; tmux is installed, so this thread's own detached session " +
                            str(window) + "; the first neuron makes it, later ones split inside it")
    nt = (os.name if platform_name is None else platform_name) == "nt"
    # The pane host runs an interactive harness only inside a terminal. One
    # headless turn is a different verb, and it is not a seat.
    tail = "; a harness with headless turns can still take one through `convoy send --live`, which is not a seat"
    if nt:
        return "none", "no terminal to split and no Windows Terminal (wt) on PATH; install it or run from one" + tail
    return "none", "no terminal to split and no tmux; install tmux or use crew in a desktop session" + tail


def _dry(card: dict[str, Any], root: Path, p: dict[str, Any], bound: str | None, *, checkout: Path | str | None,
         env: Mapping[str, str] | None, which: Which, platform_name: str | None, here: bool = False) -> dict[str, Any]:
    """What a live add would run, built from the chair it would write, writing nothing."""
    seat = {"to": p["harness"], "session_id": p["session_id"], "title": p["title"], "model": p["model"],
            "effort": p["effort"], "worktree": str(minted_worktree_path(Path(checkout) if checkout else root, p["title"]))}
    card["ok"] = True
    card["session_id"] = p["session_id"]
    card["worktree"] = seat["worktree"]
    try:
        capability = placement_capability(root, seat, env=env, which=which, platform_name=platform_name, here=here) or {}
        card["argv"] = active_pane_argv(seat, capability, root=root)
        if capability.get("thread_window"):
            card["window"] = capability.get("target")
        elif not capability.get("can_split") and not capability.get("here"):
            card["session_name"] = capability.get("target")
            card["attach"] = tmux_attach_command(str(capability.get("target")))
    except ValueError as e:
        card["argv"] = None
        card["argv_error"] = str(e)
    return card


def _free_name(root: Path, harness: str, bound: str | None) -> str:
    """<harness>-<n>, the lowest n whose chair does not exist yet."""
    existing = {str(s.get("session_id") or "") for s in list_seats(root)}
    n = 1
    while (harness + "-" + str(n) + "-" + (bound or "thread")) in existing:
        n += 1
    return harness + "-" + str(n)


def add(
    root: Path,
    harness: str,
    model: str | None = None,
    *,
    effort: str | None = None,
    title: str | None = None,
    thread: str | None = None,
    checkout: Path | str | None = None,
    runner: PaneRunner | None = None,
    window_runner: Runner | None = None,
    mint_runner: GitRunner | None = None,
    author: str | None = None,
    allow_unverified_launch: bool = False,
    write_repo_files: bool | None = None,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
    trust_probe: Callable[[dict[str, Any]], bool] = grok_project_trusted,
    launcher: dict[str, Any] | None = None,
    here: bool = False,
) -> dict[str, Any]:
    """One neuron: validate -> place -> mint -> join -> launch.

    runner=None is a dry run: it writes nothing and reports the placement.
    here=True is the person's opt-in to split the window they are working in
    (Windows: wt -w 0 split-pane; inside tmux: a split of their pane); the card
    says `placement: here`, and anywhere else it refuses before any write.
    Live, `runner` splits the caller's pane or starts a detached tmux session
    (launch_seat). `window_runner` is kept for callers and unused: Windows
    launches into the thread's own named window through `runner` too. It was bring_up's new window, used only
    where neither exists. Placement is decided before the first write, so
    "nowhere to launch" refuses with no chair and no worktree left behind. A
    spawn that fails AFTER the join leaves the chair joined and the card says
    not launched, with the `launch --seat` that retries it: the token and
    boot prompt are already on the thread, and rolling them back would erase
    the record of a join that did happen.
    """
    root = Path(root)
    bound = read_thread(root)
    hid = canonical_harness_id(harness)
    chosen_model, chosen_effort = _auto(model), _auto(effort)
    card: dict[str, Any] = {"ok": False, "convoy_id": read_id(root), "thread": bound, "harness": hid,
                            "model": chosen_model or "auto", "effort": chosen_effort or "auto",
                            "seats": [], "launched": False, "dry_run": runner is None}
    if card["convoy_id"] is None:
        card["error"] = "add requires a bound thread root (onboard, or init + bind)"
        return card
    if thread is not None and bound != thread:
        card["error"] = "thread mismatch: root is bound to " + repr(bound) + ", not " + repr(thread)
        return card
    name = str(title or "").strip() or _free_name(root, hid, bound)
    if not _SEAT_NAME.fullmatch(name):
        card["error"] = "refuse seat name (letters, digits, . _ - only): " + repr(name)
        return card
    try:
        plan = _plan(root, [{"harness": harness, "model": chosen_model, "effort": chosen_effort, "title": name}], bound)
        if runner is not None:
            validate_launch_eligibility(hid, allow_unverified_launch=allow_unverified_launch)
    except ValueError as e:
        card["error"] = str(e)
        return card
    _warn_codex_hooks(card, plan)
    from .targeted_launch import thread_window_name
    window = thread_window_name(card["convoy_id"])
    card["placement"], card["placement_reason"] = _placement(env, which, platform_name, window, here=here)
    if card["placement"] == "thread-window":
        card["window"] = window
    if card["placement"] == "none":
        card["error"] = card["placement_reason"]
        return card
    from .launcher import refusal
    refused = refusal(launcher)
    if refused:
        if runner is None:   # a dry run says what a live add would do: refuse
            card.update({k: v for k, v in refused.items() if k != "error"}, would_refuse=refused["error"])
            return card
        card.update(refused)
        return card          # before any write
    if runner is None:
        if launcher is not None:
            # A dry run attaches nobody; it says what a live add would do with the launcher.
            card["launcher"] = {"kind": launcher.get("kind"), "chair": launcher.get("chair"),
                                "would_attach": launcher.get("kind") == "unseated", "why": launcher.get("why")}
        return _dry(card, root, plan[0], bound, checkout=checkout, env=env, which=which, platform_name=platform_name,
                    here=here)
    # The retry each path prints is the command that works on that path, with
    # the person's own opt-ins, so it is never refused for a flag left off.
    flags = ((" --allow-unverified-launch" if allow_unverified_launch else "") +
             (" --write-repo-files" if write_repo_files else ""))
    sids = _mint_and_join(card, root, plan, checkout=checkout, mint_runner=mint_runner, author=author)
    if sids is None:
        return card
    if not _seat_launcher(card, root, launcher, sids):
        return card
    launched = launch_seat(root, sids[0], runner=runner, env=env, which=which, platform_name=platform_name,
                           trust_probe=trust_probe, allow_unverified_launch=allow_unverified_launch,
                           write_repo_files=write_repo_files, here=here)
    card["launch"] = launched
    if launched.get("state") == "awaiting-user-consent":
        # The chair waits on the person, not on a retry: grant, then launch it.
        card["error"] = "launch waits for the person's consent to trust the worktree"
        card["next"] = "consent"
        card["consent_request"] = launched.get("consent_request")
        request = str((launched.get("consent_request") or {}).get("request_id") or "<request_id>")
        # Only after the person's explicit yes: grant prints the one-time consent the verb takes.
        card["recovery"] = [{"session_id": sids[0], "grant": "consent --grant " + request,
                             "verb": "launch --seat " + sids[0] + flags + " --consent <consent>"}]
        card["seated"] = await_seated(root, sids, timeout=0)
        return card
    if not launched.get("ok"):
        return _mark_partial(card, root, sids, "launch failed: " + str(launched.get("error") or "terminal adapter failed"),
                             retry="launch --seat {sid}" + flags)
    if launched.get("attach"):
        card["attach"] = launched["attach"]
    card["ok"] = True
    card["launched"] = True
    card["seated"] = await_seated(root, sids, timeout=0)
    card["next"] = "await_seated"
    return card


def _mark_partial(card: dict[str, Any], root: Path, sids: list[str], error: str,
                  retry: str = "launch --seat {sid}") -> dict[str, Any]:
    """Chairs from this call exist; the window did not. Recovery is per chair."""
    card["ok"] = False
    card["launched"] = False
    card["partial"] = True
    card["error"] = error
    card["recovery"] = [{"session_id": sid, "verb": retry.format(sid=sid)} for sid in sids]
    card["seated"] = await_seated(root, sids, timeout=0)
    card["next"] = "launch"
    return card


def _stale_incarnation(row: dict[str, Any], seated_row: dict[str, Any]) -> bool:
    """Is this ack from a life that is already over?

    Only when BOTH numbers exist and the ack's is lower. A seated row without
    an incarnation predates the field, and a seat without one was never hosted
    by a body-owning launch; in either case the token comparison is all the
    evidence there is and this must not invent more.
    """
    acked = seated_row.get("incarnation")
    current = row.get("incarnation")
    if acked is None or current is None:
        return False
    try:
        return int(acked) < int(current)
    except (TypeError, ValueError):
        return False


def _seated_states(root: Path, session_ids: list[str], after: str | None = None) -> list[dict[str, Any]]:
    """after: ISO ts; a seated row stamped BEFORE it is an old life of the
    chair (pre-relaunch) and does not count. Connected must be proven again.

    An ack naming an incarnation older than the seat's current one is skipped
    the same way: a slow previous body can ack AFTER the relaunch timestamp
    with the very token this chair's join minted, so the clock alone does not
    separate the lives."""
    seats = {str(s.get("session_id") or ""): s for s in list_seats(root)}
    unknown = [sid for sid in session_ids if sid not in seats]
    if unknown:
        raise ValueError("unknown seat: " + ", ".join(unknown))
    rows = feed_since(root, EPOCH)
    out: list[dict[str, Any]] = []
    for sid in session_ids:
        mint = None
        seated = None
        for r in rows:
            if r.get("instance_id") != sid:
                continue
            if r.get("kind") in ("join", "swap"):
                mint = r
            elif r.get("kind") == "seated":
                if after and str(r.get("ts") or "") < after:
                    continue
                if _stale_incarnation(seats[sid], r):
                    continue
                seated = r
        # connected: the ack cites the token THIS mint issued. seated_ack
        # itself accepts any non-empty token (lifecycle.py), so the comparison
        # is made here, where the claim is read back, not trusted.
        if seated is None:
            state = "pending"
        elif mint is not None and seated.get("token") == mint.get("token"):
            state = "connected"
        else:
            state = "stale"
        out.append({
            "session_id": sid,
            "to": seats[sid].get("to"),
            "where": seats[sid].get("where"),
            "state": state,
            "connect_mode": connect_mode(seats[sid].get("to")),
            "minted_at": mint.get("ts") if mint else None,
            "seated_at": seated.get("ts") if seated else None,
        })
    return out


def await_seated(
    root: Path,
    session_ids: list[str],
    *,
    timeout: float = 120.0,
    interval: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Any] = time.sleep,
    after: str | None = None,
) -> dict[str, Any]:
    """Poll kind=seated rows until every chair is connected or timeout passes.
    Returns per chair connected | pending | stale and the seconds waited on
    `clock`. timeout=0 is one pass (a snapshot). Never a token on the card."""
    sids = [str(s) for s in session_ids]
    budget = max(0.0, float(timeout))
    step = max(0.0, float(interval))
    start = clock()
    while True:
        chairs = _seated_states(Path(root), sids, after=after)
        waited = max(0.0, clock() - start)
        if all(c["state"] == "connected" for c in chairs) or waited >= budget:
            break
        sleep(min(step, budget - waited) if step else budget - waited)
    by_state = {state: [c["session_id"] for c in chairs if c["state"] == state] for state in STATES}
    return {
        "ok": bool(chairs) and not by_state["pending"] and not by_state["stale"],
        "waited_s": round(waited, 3),
        "timeout_s": budget,
        "after": after,
        "chairs": chairs,
        **by_state,
    }
