"""The wake dispatcher: tail the feed, and wake the one chair each row is for.

Only two things wake anyone. A send wakes its receiver (the synapse row's instance_id), unless
the receiver is its own proven sender. A note citing a token wakes the sender of that token, once,
and never the note's own author. A sender is proven when the send row's verified_by is a verified
method and the row is not marked claimed; a send row without a proven sender wakes nobody on a
reply, because an unknown sender is never guessed. Everything else wakes nobody, so an
acknowledgement of an acknowledgement, which cites no new token, ends the exchange, and a
conductor's own row citing a token wakes nobody either (a conductor answers with a send).

The loop tails `.convoy/feed.jsonl` from a byte cursor (`.convoy/wake/cursor`) and replaces the
cursor only after it has dispatched, so a crash replays rows and the dedupe key
`token:target:reason` absorbs the replay. It stops before a torn last line and skips a line that
is not JSON. Every attempt is a row in `.convoy/wake/outbox.jsonl`; that log is also the
dispatcher's state, so a restart reads where it was. An error on one row is recorded as a held row
for that wake, and the loop and the cursor move on, so one bad row can never stop the loop.

A wake carries a pointer (the token, who sent it, where to read it), never the body: the receiver
pulls the message itself. A budget per pair and per target per hour, a cap per token, and a hold a
person sets refuse a wake, before its first fire and before every refire or ladder step, with a
feed row and at most one alert per target per hour. A cap per reply-chain conversation waits for a
conversation id, which no send records yet.

A send wake is read when the receiver drains its inbox row (acked) or cites the token (answered),
and that read verifies the route. Unread, it is refired once, then dropped with a `wake-dropped`
fault on its route, and the ladder takes over: a channel falls back to the waiter, anything else
alerts the person. How long an unread wake waits is read from the target's Stop pulse: a turn that
ended after the wake without reading waits T_ACK; no turn end since the wake (busy, or never woken)
waits T_ACK_LONG; a target that has never had a Stop pulse has no turn signal and waits T_ACK. A
reply wake has no read receipt, so it is fired once and not timed. A citation whose author is
only claimed (a hosted neuron's honest answer is claimed too) never pre-empts or suppresses a first
fire and never verifies a route; after the first fire, one from the target stops the refire and
the ladder as answered-claimed, which is not delivery and raises no fault. A receiver that is down holds
the wake; `catch_up` re-fires held wakes and pending inbox rows on start.

The routes are an adapter (`fire`, `alert`): this module never spawns, queues or posts anything
itself, and an adapter that raises never escapes the loop.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from .activity import neuron_id
from .convoy import read_id
from .inbox import _consumed_tokens, inbox_dir, inbox_path, pending
from .layer import _VERIFIED_METHODS, _is_conductor_alias, hook
from .pulse import read_pulse_by_source
from .wake_routes import mark_verified, reachability_detail, read_route, record_fault

# per_token caps the fires for one token across its send and reply wakes. It is not a conversation
# cap: a reply chain mints fresh tokens, and no send records the token it answers yet.
LIMITS = {"per_pair_per_hour": 20, "per_target_per_hour": 40, "per_token": 12}
# Seconds a send wake may go unread on its route before it is refired, then dropped.
T_ACK = {"channel": 90, "codex-queue": 90, "board-webhook": 300, "waiter": 120}
# Seconds to wait instead when no turn has ended since the wake: busy cannot be told from not woken.
T_ACK_LONG = 1200
# Where a dropped or failed wake goes next. The ladder always ends at the person.
LADDER = {"channel": "waiter", "waiter": "alert", "codex-queue": "alert", "board-webhook": "alert", "none": "alert"}
ALERT_EVERY_SEC = 3600
# Results that mean a wake already went out for its key: never fire it twice.
_DONE = frozenset(("fired", "acked", "answered", "answered-claimed"))
_CITED = re.compile(r"\b[Tt]oken\s*[=:]?\s*([0-9a-f]{32})\b")


class RouteError(Exception):
    """A route could not deliver the wake; the message says why, in one line."""


class Routes(Protocol):
    def fire(self, route: str, pointer: dict[str, Any], route_row: dict[str, Any]) -> None: ...

    def alert(self, target: str, text: str) -> None: ...


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        value = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def wake_dir(root: Path | str) -> Path:
    return Path(root) / ".convoy" / "wake"


def outbox_path(root: Path | str) -> Path:
    return wake_dir(root) / "outbox.jsonl"


def cursor_path(root: Path | str) -> Path:
    return wake_dir(root) / "cursor"


def holds_path(root: Path | str) -> Path:
    return wake_dir(root) / "holds.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(path: Path, row: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return row


def read_outbox(root: Path | str) -> list[dict[str, Any]]:
    return _read_jsonl(outbox_path(root))


def set_hold(root: Path | str, target: str, *, until: str, by: str) -> dict[str, Any]:
    """Wake nobody at `target` until `until`. The last hold per target wins."""
    who = str(target or "").strip()
    author = str(by or "").strip()
    if not who or not author:
        raise ValueError("refuse a hold with no target or no author")
    if _parse(until) is None:
        raise ValueError("refuse hold until " + repr(until) + ": give an ISO UTC timestamp")
    return _append(holds_path(root), {"target": who, "until": until, "by": author,
                                       "ts": _iso(datetime.now(timezone.utc))})


def cited_tokens(text: str) -> list[str]:
    """The 32-hex tokens a note cites (`re token <t>` or `token=<t>`), in order, once each."""
    return list(dict.fromkeys(_CITED.findall(str(text or ""))))


def proven_author(row: dict[str, Any]) -> str | None:
    """A row's `from` when it is proven (a send's sender, a note's author): a verified method,
    and not marked claimed."""
    sender = row.get("from")
    if not isinstance(sender, str) or not sender:
        return None
    if row.get("verified_by") not in _VERIFIED_METHODS or row.get("author_claimed"):
        return None
    return sender


def wake_targets(row: dict[str, Any], sender_of: Callable[[str], str | None]) -> list[tuple[str, str, str]]:
    """(target, reason, token) for each chair this feed row wakes; empty for everything else."""
    kind = row.get("kind")
    if kind == "synapse":
        token, target = row.get("token"), row.get("instance_id")
        if isinstance(token, str) and token and isinstance(target, str) and target and proven_author(row) != target:
            return [(target, "send", token)]
        return []
    if kind == "note":
        out = []
        for token in cited_tokens(str(row.get("summary") or "")):
            sender = sender_of(token)
            if sender and sender != proven_author(row):  # a claimed author never silences a wake
                out.append((sender, "reply", token))
        return out
    return []


class Dispatcher:
    def __init__(self, root: Path | str, routes: Routes, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.root = Path(root)
        self.routes = routes
        self.clock = clock
        self.thread: str | None = None
        self._sends: dict[str, dict[str, Any]] = {}       # token -> its synapse row
        self._citations: set[tuple[str, str]] = set()     # (author, token) for every proven citing row
        self._claimed: set[tuple[str, str]] = set()       # the same, where the author is only claimed

    # The feed

    def _feed(self) -> Path:
        return self.root / ".convoy" / "feed.jsonl"

    def _read_cursor(self) -> int:
        try:
            return max(0, int(cursor_path(self.root).read_text(encoding="utf-8").strip()))
        except (OSError, ValueError):
            return 0

    def _write_cursor(self, offset: int) -> None:
        path = cursor_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp-" + str(os.getpid()))
        temporary.write_text(str(offset), encoding="utf-8")
        os.replace(temporary, path)

    def _tail(self, offset: int) -> tuple[list[dict[str, Any]], int]:
        """The whole rows after `offset`, and the offset just past the last newline."""
        path = self._feed()
        if not path.is_file():
            return [], offset
        if offset > path.stat().st_size:
            offset = 0  # the feed was replaced; read it again and let dedupe absorb what repeats
        with path.open("rb") as f:
            f.seek(offset)
            data = f.read()
        end = data.rfind(b"\n")
        if end < 0:
            return [], offset
        rows = []
        for line in data[:end + 1].splitlines():
            try:
                row = json.loads(line.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows, offset + end + 1

    def _learn(self, row: dict[str, Any]) -> None:
        token = row.get("token")
        if row.get("kind") == "synapse" and isinstance(token, str) and token:
            self._sends[token] = row
        author = row.get("from")
        if row.get("kind") in ("note", "conductor") and isinstance(author, str) and author:
            if row.get("kind") == "conductor":
                principal = row.get("principal")
                proven = isinstance(principal, dict) and bool(principal.get("bearer"))
            else:
                proven = proven_author(row) == author
            for cited in cited_tokens(str(row.get("summary") or "")):
                (self._citations if proven else self._claimed).add((author, cited))

    def _sender_of(self, token: str) -> str | None:
        return proven_author(self._sends.get(token, {}))

    # The loop

    def start(self) -> None:
        """Learn the whole feed, then catch up on what is still owed."""
        self.thread = read_id(self.root)
        rows, _ = self._tail(0)
        for row in rows:
            self._learn(row)
        self.catch_up()

    def step(self) -> None:
        rows, offset = self._tail(self._read_cursor())
        for row in rows:
            self._learn(row)  # all first, so a send already answered in this batch is not fired
        for row in rows:
            for target, reason, token in wake_targets(row, self._sender_of):
                try:
                    self.dispatch(row, target, reason, token)
                except Exception as e:  # one bad row is recorded and never stops the loop
                    self._record_error(row, target, reason, token, e)
        self._write_cursor(offset)  # after dispatch: a crash replays, and dedupe absorbs it
        self.check_ack_timers()

    def run(self, *, poll_s: float = 1.0, should_stop: Callable[[], bool] = lambda: False,
            sleep: Callable[[float], Any] = time.sleep) -> None:
        self.start()
        while True:
            self.step()
            if should_stop():
                return
            sleep(poll_s)

    def catch_up(self) -> None:
        """Wake every pending inbox row, and every held wake whose receiver is back."""
        for path in sorted(inbox_dir(self.root).glob("*.jsonl")):
            rows = _read_jsonl(path)
            seats = {r.get("session_id") for r in rows if isinstance(r.get("session_id"), str)}
            for seat in sorted(s for s in seats if s):
                for item in pending(self.root, seat):
                    token = item["token"]
                    row = self._sends.get(token) or {"token": token, "instance_id": seat}
                    try:
                        self.dispatch(row, seat, "send", token)
                    except Exception as e:
                        self._record_error(row, seat, "send", token, e)
        for w in self._latest().values():
            if w.get("result") != "held" or w.get("route") == "alert":
                continue
            row = {"token": w.get("token"), "from": w.get("from"), **(w.get("stamp") or {})}
            try:
                if w["reason"] == "send" and w["token"] in self._sends:
                    row = self._sends[w["token"]]  # the send itself, so a proven sender is kept
                if read_route(self.root, w["target"]) is None:
                    continue
                if reachability_detail(self.root, w["target"], now=self._now())["reachable"] == "down":
                    continue
                self.dispatch(row, w["target"], w["reason"], w["token"])
            except Exception as e:
                self._record_error(row, w.get("target"), w.get("reason"), w.get("token"), e)

    # One wake

    def _now(self) -> str:
        return _iso(self.clock())

    def _latest(self) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in read_outbox(self.root):
            # An error row is on the record but is not a state: the wake stays as it was.
            if isinstance(row.get("dedupe_key"), str) and row.get("result") != "error":
                latest[row["dedupe_key"]] = row
        return latest

    def _log(self, base: dict[str, Any], *, route: str | None, attempt: int, result: str, why: str,
             alerted: bool = False) -> dict[str, Any]:
        return _append(outbox_path(self.root), {**base, "route": route, "attempt": attempt, "result": result,
                                                "why": why, "alerted": alerted, "ts": self._now()})

    def _pointer(self, base: dict[str, Any]) -> dict[str, Any]:
        sender = base.get("from")
        return {
            "v": 1, "wake_id": base["wake_id"], "reason": base["reason"],
            "target": base["target"], "token": base["token"],
            "from": sender, "from_neuron": neuron_id(self.thread, sender) if sender else None,
            "stamp": dict(base.get("stamp") or {"device": None, "verified_by": None}),
            "thread": self.thread, "ts": self._now(),
            "read_with": "replies(token)" if _is_conductor_alias(base["target"]) else "inbox(chair)",
        }

    def _alert(self, target: str, text: str) -> bool:
        try:
            self.routes.alert(target, text)
        except Exception:  # an alert that fails must not stop the loop; the row still says why
            return False
        return True

    def _alert_once(self, target: str, text: str) -> bool:
        """Alert unless this target was alerted within the hour."""
        since = self.clock() - timedelta(seconds=ALERT_EVERY_SEC)
        for row in read_outbox(self.root):
            when = _parse(row.get("ts"))
            if row.get("target") == target and row.get("alerted") and when and when > since:
                return False
        return self._alert(target, text)

    def _read_receipt(self, token: str, target: str, *, claimed: bool = False) -> str | None:
        """answered (a proven citation), acked (the inbox row drained), or, only when `claimed` is
        allowed, answered-claimed (a citation whose author is claimed); None when unread."""
        if (target, token) in self._citations:
            return "answered"
        if not _is_conductor_alias(target) and token in _consumed_tokens(_read_jsonl(inbox_path(self.root, target))):
            return "acked"
        if claimed and (target, token) in self._claimed:
            return "answered-claimed"
        return None

    def _budget_refusal(self, sender: str | None, target: str, token: str) -> tuple[str, str] | None:
        """(reason, why) when the wake must not go out; None when it may."""
        now = self.clock()
        holds = [h for h in _read_jsonl(holds_path(self.root)) if h.get("target") == target]
        if holds:
            until = _parse(holds[-1].get("until"))
            if until and until > now:
                return "hold", "hold until " + str(holds[-1]["until"]) + " by " + str(holds[-1].get("by"))
        fired = [r for r in read_outbox(self.root) if r.get("result") == "fired"]
        hour_ago = now - timedelta(hours=1)
        recent = [r for r in fired if (_parse(r.get("ts")) or now) > hour_ago]
        pair = {sender, target}
        if sum(1 for r in recent if {r.get("from"), r.get("target")} == pair) >= LIMITS["per_pair_per_hour"]:
            return "budget", "budget: per_pair_per_hour " + str(LIMITS["per_pair_per_hour"])
        if sum(1 for r in recent if r.get("target") == target) >= LIMITS["per_target_per_hour"]:
            return "budget", "budget: per_target_per_hour " + str(LIMITS["per_target_per_hour"])
        if sum(1 for r in fired if r.get("token") == token) >= LIMITS["per_token"]:
            return "budget", "budget: per_token " + str(LIMITS["per_token"])
        return None

    def dispatch(self, row: dict[str, Any], target: str, reason: str, token: str) -> None:
        key = token + ":" + target + ":" + reason
        if any(r.get("result") in _DONE for r in read_outbox(self.root) if r.get("dedupe_key") == key):
            return  # never twice
        sender = proven_author(row) if reason == "send" else row.get("from")  # a reply's author
        base = {
            "wake_id": "wk_" + uuid.uuid4().hex[:16], "dedupe_key": key, "target": target,
            "reason": reason, "token": token, "from": sender if isinstance(sender, str) and sender else None,
            "stamp": {"device": row.get("device"), "verified_by": row.get("verified_by")},
        }
        if reason == "send" and self._read_receipt(token, target):
            self._log(base, route=None, attempt=0, result="answered", why="handled before the wake")
            return
        if self._refused(base, route=None, attempt=0):
            return
        route = read_route(self.root, target)
        if route is None:
            self._log(base, route=None, attempt=0, result="held", why="no wake route registered")
            return
        state = reachability_detail(self.root, target, now=self._now())
        if state["reachable"] == "down":
            why = "receiver unreachable: " + str(state["reason"])
            alerted = self._alert_once(target, target + " cannot be woken: " + why)
            self._log(base, route=route["route"], attempt=0, result="held", why=why, alerted=alerted)
            return
        self._fire(base, route["route"], route, attempt=1)

    def _refused(self, base: dict[str, Any], *, route: str | None, attempt: int) -> bool:
        """Refuse the wake when a hold or the budget says so: an outbox row, a feed row and at most
        one alert an hour. Checked before the first fire and before every refire or ladder step."""
        refusal = self._budget_refusal(base["from"], base["target"], base["token"])
        if not refusal:
            return False
        kind, why = refusal
        target = base["target"]
        alerted = self._alert_once(target, "a wake to " + target + " was refused: " + why)
        self._log(base, route=route, attempt=attempt, result="refused", why=why, alerted=alerted)
        hook(self.root, kind="refuse", summary="wake to " + target + " refused: " + why, instance_id=target,
             author=None, extra={"reason": kind, "pair": [base["from"], target], "token": base["token"],
                                 "dedupe_key": base["dedupe_key"]})
        return True

    def _record_error(self, row: dict[str, Any], target: str | None, reason: str | None, token: str | None,
                      error: Exception, *, result: str = "held") -> None:
        """A row naming the error, so one bad row is on the record and the loop goes on. held: no
        wake went out, and catch-up retries it. error: the wake keeps its state for the next tick.
        A row with no target, reason or token cannot be keyed and is left as it is."""
        if not all(isinstance(v, str) and v for v in (target, reason, token)):
            return
        base = {"wake_id": "wk_" + uuid.uuid4().hex[:16], "dedupe_key": token + ":" + target + ":" + reason,
                "target": target, "reason": reason, "token": token,
                "from": proven_author(row) if reason == "send" else row.get("from"),
                "stamp": {"device": row.get("device"), "verified_by": row.get("verified_by")}}
        try:
            self._log(base, route=None, attempt=0, result=result, why="error: " + type(error).__name__ + ": " + str(error))
        except Exception:
            pass  # the outbox itself cannot be written; nothing else can record it

    def _guarded_fire(self, base: dict[str, Any], route: str, route_row: dict[str, Any], *, attempt: int) -> None:
        if not self._refused(base, route=route, attempt=attempt):
            self._fire(base, route, route_row, attempt=attempt)

    def _fire(self, base: dict[str, Any], route: str, route_row: dict[str, Any], *, attempt: int) -> None:
        try:
            self.routes.fire(route, self._pointer(base), route_row)
        except Exception as e:  # never let a route stop the loop or a send
            why = str(e) if isinstance(e, RouteError) else type(e).__name__ + ": " + str(e)
            self._log(base, route=route, attempt=attempt, result="held", why=why)
            self._fallback(base, route, route_row, attempt=attempt, why=why)
            return
        self._log(base, route=route, attempt=attempt, result="fired", why=route)

    def _fallback(self, base: dict[str, Any], route: str, route_row: dict[str, Any], *, attempt: int, why: str) -> None:
        nxt = LADDER.get(route, "alert")
        if nxt == "alert":
            alerted = self._alert(base["target"], base["target"] + " did not read wake " + base["dedupe_key"] + ": " + why)
            self._log(base, route="alert", attempt=attempt, result="held",
                      why=("alerted the person: " if alerted else "the alert failed: ") + why, alerted=alerted)
            return
        self._guarded_fire(base, nxt, route_row, attempt=attempt + 1)

    # Acknowledgement timers

    def check_ack_timers(self) -> None:
        now = self.clock()
        for key, w in self._latest().items():
            # dropped is still armed: a drop whose ladder step failed completes on the next tick
            if w.get("result") not in ("fired", "dropped") or w.get("reason") != "send" or w.get("route") not in T_ACK:
                continue
            try:
                self._check_one(now, key, w)
            except Exception as e:  # one bad wake is recorded, stays armed, and never stops the timers
                if self._errored_within(key, T_ACK[w["route"]], now):
                    continue  # at most one error row per wake per T_ACK window
                row = {"from": w.get("from"), **(w.get("stamp") or {})}
                self._record_error(row, w.get("target"), w.get("reason"), w.get("token"), e, result="error")

    def _errored_within(self, key: str, seconds: float, now: datetime) -> bool:
        since = now - timedelta(seconds=seconds)
        for row in read_outbox(self.root):
            when = _parse(row.get("ts"))
            if row.get("dedupe_key") == key and row.get("result") == "error" and when and when > since:
                return True
        return False

    def _check_one(self, now: datetime, key: str, w: dict[str, Any]) -> None:
        """Ack, wait, refire or drop one fired send wake."""
        base = {k: w.get(k) for k in ("wake_id", "dedupe_key", "target", "reason", "token", "from", "stamp")}
        route_row = read_route(self.root, w["target"]) or {}
        got = self._read_receipt(w["token"], w["target"], claimed=True)
        if got == "answered-claimed":
            # The target says it answered, but its authorship is a claim: stop the refire and the
            # ladder, and never count it as delivery or verify the route on it.
            self._log(base, route=w["route"], attempt=w.get("attempt") or 1, result=got,
                      why="the receiver cited the token; its authorship is claimed")
            return
        if got:
            self._log(base, route=w["route"], attempt=w.get("attempt") or 1, result=got,
                      why="the receiver drained its inbox row" if got == "acked" else "the receiver cited the token")
            if route_row:
                mark_verified(self.root, w["target"], ts=self._now())
            return
        if w.get("result") == "dropped":
            self._fallback(base, w["route"], route_row, attempt=w.get("attempt") or 2, why="dropped")
            return
        fired_at = _parse(w.get("ts")) or now
        if (now - fired_at).total_seconds() < self._ack_window(w["target"], w["route"], fired_at):
            return
        if w.get("attempt") == 1:
            self._guarded_fire(base, w["route"], route_row, attempt=2)
            return
        # The fault first: if it fails, nothing is written and the next tick drops again. Then the
        # dropped row, then the ladder: if the ladder fails, the dropped row keeps the wake armed.
        if route_row:
            record_fault(self.root, w["target"], "wake-dropped", reason="no read after 2 wakes: " + key,
                         by="wake-dispatcher", seen_at=self._now())
        self._log(base, route=w["route"], attempt=w.get("attempt") or 2, result="dropped", why="no read after 2 wakes")
        self._fallback(base, w["route"], route_row, attempt=w.get("attempt") or 2, why="dropped")

    def _ack_window(self, target: str, route: str, fired_at: datetime) -> float:
        stop = read_pulse_by_source(self.root, target, "stop")
        ended_at = _parse(stop.get("ts")) if stop else None
        if ended_at is None or ended_at > fired_at:
            return T_ACK[route]  # no turn signal at all, or a turn ended and did not read
        return T_ACK_LONG
