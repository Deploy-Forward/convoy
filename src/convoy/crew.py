"""crew: N neurons -> N chairs -> ONE window -> they all connect, observed.

The wizard's old sequence (join + launch for chair 1, `seat` for chairs 2..N,
bring_up) left chairs 2..N with no boot prompt - `seat` never writes one - so
those panes came up with a bare harness argv and nobody told them to connect
(reader 4, 2026-09-04). crew joins EVERY chair (boot prompt + token), mints
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
            raise ValueError("refuse seat " + str(i + 1) + ": chair already exists: " + sid)
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
) -> dict[str, Any]:
    """Validate -> mint -> join each -> bring_up once. runner=None joins the
    chairs and shows the argv without spawning; live_runner pops the window.
    checkout defaults to the root (onboard binds the thread there)."""
    root = Path(root)
    bound = read_thread(root)
    # launched starts False and is read from the runner's RESULT after bring_up.
    # It was `runner is not None`, so a crew refused before any write, with a
    # live runner handed in, claimed to have acted (review 2026-09-04).
    card: dict[str, Any] = {"ok": False, "convoy_id": read_id(root), "thread": bound, "seats": [], "launched": False}
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
    return _warn_codex_hooks(_bring_up_window(card, root, sids, bound, runner=runner,
                                              allow_unverified_launch=allow_unverified_launch,
                                              write_repo_files=write_repo_files), plan)


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
                     retry: str = "launch --seat {sid}") -> dict[str, Any]:
    """Launch the joined chairs once through bring_up: one new window, N panes."""
    try:
        up = bring_up(root, thread=bound, runner=runner, session_ids=sids, allow_unverified_launch=allow_unverified_launch,
                      write_repo_files=write_repo_files)
    except OSError as e:
        return _mark_partial(card, root, sids, "launch failed: " + str(e), retry=retry)
    card["windows"] = up.get("windows") or []
    card["cloud"] = up.get("cloud") or []
    # Live 2026-09-09: two cursor-agent seats launched with dead hook files (the
    # resolver found no hook-shell interpreter that imports convoy) and the card
    # said nothing at the top; the caller reported "live" seats whose every tool
    # was refused. Per-window errors now ride the card as warnings.
    warnings: list[str] = []
    for w in card["windows"]:
        if not isinstance(w, dict):
            continue
        for k in ("inbox_hook_error", "identity_error", "agent_error"):
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
               window: str | None = None) -> tuple[str, str]:
    """Where one new neuron goes, decided before anything is written:
    split | thread-window | detached | none, with the reason the card shows."""
    cap = terminal_capability(env=env, which=which, platform_name=platform_name)
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
         env: Mapping[str, str] | None, which: Which, platform_name: str | None) -> dict[str, Any]:
    """What a live add would run, built from the chair it would write, writing nothing."""
    seat = {"to": p["harness"], "session_id": p["session_id"], "title": p["title"], "model": p["model"],
            "effort": p["effort"], "worktree": str(minted_worktree_path(Path(checkout) if checkout else root, p["title"]))}
    card["ok"] = True
    card["session_id"] = p["session_id"]
    card["worktree"] = seat["worktree"]
    try:
        capability = placement_capability(root, seat, env=env, which=which, platform_name=platform_name) or {}
        card["argv"] = active_pane_argv(seat, capability, root=root)
        if capability.get("thread_window"):
            card["window"] = capability.get("target")
        elif not capability.get("can_split"):
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
) -> dict[str, Any]:
    """One neuron: validate -> place -> mint -> join -> launch.

    runner=None is a dry run: it writes nothing and reports the placement.
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
    card["placement"], card["placement_reason"] = _placement(env, which, platform_name, window)
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
        return _dry(card, root, plan[0], bound, checkout=checkout, env=env, which=which, platform_name=platform_name)
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
                           write_repo_files=write_repo_files)
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
