"""Targeted launch: add exactly one fresh Convoy chair to the caller's pane host.

Harness construction and terminal placement are separate contracts.  The
terminal adapter is allowlisted and must be able to name the active context;
there is deliberately no keyboard injection or generic shell fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .bringup import (
    _absolute_harness,
    _harness_bin,
    _is_abs_exe,
    _pane_title,
    _seat_with_agent,
    _with_claude_live_flags,
    ensure_first_run,
    resume_argv,
    resume_target,
)
from .consent import consume_consent, request_consent
from .convoy import list_seats, read_id, read_thread, update_seat
from .resume_first import ensure_session_id
from .harness_contract import effort_contract, harness_entries, harness_exec, model_catalog, where_options
from .inbox import connect_mode

Which = Callable[[str], str | None]
Runner = Callable[[list[str]], dict[str, Any]]
GitWorktrees = Callable[[Iterable[Path]], list[str]]


def terminal_capability(
    *,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Return the terminal adapter a launch goes through, or an explicit refusal.

    tmux is checked first because a tmux pane can be nested inside another
    terminal and TMUX_PANE names the caller's exact pane. On Windows, Windows
    Terminal's CLI cannot split a specific pane: `-w 0 split-pane` splits whatever
    pane has focus in the most recently used window, wherever the person last
    clicked. So Windows never splits the caller's window: every launch targets the
    thread's own named window (placement_capability names it), whether or not the
    caller runs inside Windows Terminal.
    """
    values = os.environ if env is None else env
    platform = os.name if platform_name is None else platform_name

    tmux_session = str(values.get("TMUX") or "").strip()
    tmux_pane = str(values.get("TMUX_PANE") or "").strip()
    tmux = which("tmux") if tmux_session and tmux_pane else None
    if tmux:
        return {
            "can_split": True,
            "adapter": "tmux",
            "executable": str(tmux),
            "target": tmux_pane,
            "target_semantics": "exact-caller-pane",
            "can_close_exact": False,
            "close_reason": "created-pane-id-not-yet-captured",
        }

    wt = which("wt") if platform == "nt" else None
    if wt:
        return {
            "can_split": False,
            "thread_window": True,
            "adapter": "windows-terminal-thread",
            "executable": str(wt),
            "target_semantics": "named-thread-window",
            "can_close_exact": False,
            "close_reason": "windows-terminal-cli-has-no-close-pane-command",
        }

    refusal: dict[str, Any] = {
        "can_split": False,
        "adapter": None,
        "target": None,
        "reason": "no-supported-active-terminal",
        "supported_adapters": ["tmux", "windows-terminal"],
        "can_close_exact": False,
        "close_reason": "no-supported-active-terminal",
    }
    # Outside tmux, a POSIX box with tmux installed (a remote terminal over
    # ssh) can still host a body: a DETACHED session the person attaches to.
    # It is not a split, so can_split stays False and the refusal above stays
    # the answer for anything that needs the caller's own pane.
    tmux_installed = which("tmux") if platform != "nt" else None
    if tmux_installed:
        refusal["detached"] = {
            "can_split": False,
            "can_detach": True,
            "adapter": "tmux-detached",
            "executable": str(tmux_installed),
            "target_semantics": "new-detached-session",
            "can_close_exact": False,
            "close_reason": "created-pane-id-not-yet-captured",
        }
    return refusal


def thread_window_name(convoy_id: Any) -> str:
    """The thread's own terminal window (Windows Terminal) or detached session (tmux):
    `convoy-` + 8 hex of sha256(convoy_id). Short, safe in a wt window name and a tmux
    target, never numeric (wt reads a number as a window id), never 0, deterministic."""
    cid = str(convoy_id or "").strip()
    if not cid:
        raise ValueError("a thread window needs the thread's convoy_id")
    return "convoy-" + hashlib.sha256(cid.encode("utf-8")).hexdigest()[:8]


# The thread window's tab shows the focused pane's title, so each pane title names the
# thread first. " - " and not a middle dot: ASCII, and the nudge title rules read it.
TITLE_SEP = " - "
LABEL_MAX = 24


def thread_label(thread: Any, folder: Any, convoy_id: Any) -> str:
    """A short, ASCII label unique to the thread: its bound name, else the repo folder name,
    then `-<4 hex of the window id>` (two repos with one folder name never share a label);
    with neither name, the window's 8 hex. At most LABEL_MAX characters: the name is trimmed,
    never the hex. Never a cvy_ id and never a path (either falls through)."""
    window_hex = thread_window_name(convoy_id).removeprefix("convoy-")
    suffix = "-" + window_hex[:4]
    for raw in (thread, folder):
        text = str(raw or "").strip()
        if not text or text.lower().startswith("cvy_") or "/" in text or "\\" in text or ":" in text:
            continue
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:LABEL_MAX - len(suffix)].strip("-")
        if name:
            return name + suffix
    return window_hex


def root_thread_label(root: Path | str | None, thread: Any = None) -> str:
    """thread_label for a root: its bound thread, its folder, its convoy_id."""
    if root is None:
        return thread_label(thread, "", thread or "thread")
    return thread_label(read_thread(Path(root)), Path(root).resolve().name, read_id(Path(root)) or str(root))


def thread_pane_title(label: str, seat: dict[str, Any]) -> str:
    """`<thread label> - <chair title>`: what the thread window's tab shows for this pane."""
    return label + TITLE_SEP + _pane_title(seat)


def thread_window_live(root: Path, except_sid: Any = None) -> bool:
    """Another chair of this thread has a live pane host, so the thread's window (or
    tmux session) exists: a new neuron splits inside it instead of opening it."""
    return any(hosted_live(root, str(s["session_id"])) for s in list_seats(root)
               if s.get("session_id") and s.get("session_id") != except_sid)


def tmux_attach_command(name: str) -> str:
    """`=` makes tmux match the session name exactly, never by prefix."""
    return "tmux attach -t " + shlex.quote("=" + name)


def placement_capability(
    root: Path,
    row: dict[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
) -> dict[str, Any] | None:
    """The adapter this chair launches through: inside tmux a split of the caller's exact
    pane; on Windows the thread's own named window; outside tmux the thread's own detached
    tmux session; else None. `first` says whether this neuron opens the window (or
    session) or splits inside it."""
    capability = terminal_capability(env=env, which=which, platform_name=platform_name)
    if capability.get("can_split"):
        return capability
    first = not thread_window_live(root, except_sid=row.get("session_id"))
    label = root_thread_label(root)
    if capability.get("thread_window"):
        return {**capability, "target": thread_window_name(read_id(root)), "first": first, "label": label}
    detached = capability.get("detached")
    if not detached:
        return None
    return {**detached, "target": thread_window_name(read_id(root)), "first": first, "label": label}


# Harnesses that accept a session id for a NEW conversation, and the flag
# each one spells it with. Live at claude 2.1.274 (`--session-id <uuid>` in
# --help) and grok 1.0.34 (`-s, --session-id <uuid>`). Codex 0.154.0 has no
# such flag, so Codex's id is observed from its own Stop payload instead and
# nothing here invents one.
# Which harnesses can be told their session id is the CONTRACT's answer
# (`session_id_flag`, with the --help line that evidences it), not a dict
# here, so that adding a harness is a contract edit.


def pane_child_argv(seat: dict[str, Any], *, root: Path | str | None = None,
                    mint: Callable[[], Any] = uuid.uuid4) -> list[str]:
    """Native harness argv executed by the lifecycle host.

    The host runs every pane, so this argv is what the terminal used
    to hold: it must be byte-for-byte what `isolated_wt_argv` built, or the
    move to an owned body would silently change how the harness starts. The
    absolute exe and Claude's live flags are therefore resolved here and not
    only there (they were missing, and `bring_up` would have launched Claude
    without --permission-mode the moment the host took over).

    With a `root`, a chair on a mint-capable harness that carries no
    usable resume is given one before it starts, and the seat row records it
    in the same breath. Without a root nothing is minted - an id in an argv
    that nobody wrote down is worse than no id at all, and this function is
    also the pure builder that dry-run cards use. A mint is a NEW session, so
    it rides as the mint flag and never as --resume, which would name a
    conversation that does not exist yet.
    """
    seat = dict(seat)
    if root is not None:
        # One minting path: ensure_session_id writes resume, resume_for
        # and resume_minted together, and resume_argv reads that provenance to
        # DECLARE the id once. Minting here too would be a second answer.
        seat = dict(ensure_session_id(Path(root), seat, mint=mint))
    inner = resume_argv(seat)
    override = seat.get("exe")
    if override:
        inner = [str(override), *inner[1:]]
    else:
        inner = [_absolute_harness(inner[0]), *inner[1:]]
    inner = _with_claude_live_flags(inner, seat.get("to"))
    if _harness_bin(str(seat.get("to") or "")) == "grok" and seat.get("trust_worktree"):
        if "--trust" not in inner:
            inner.insert(1, "--trust")
    return inner


def _pane_host_program() -> str | None:
    """The `convoy-pane-host` console script: on PATH, or in the script directory that
    belongs to THIS interpreter (venv Scripts/bin, or the user-site Scripts/bin that a
    `pip install --user` writes to and Windows never puts on PATH)."""
    found = shutil.which("convoy-pane-host") or shutil.which("convoy-pane-host.exe")
    # A `which` that answers with some other program (a test double, a shim) is not a host.
    if found and Path(found).name.lower().startswith("convoy-pane-host"):
        return found
    import site
    import sysconfig
    exe = Path(sys.executable).resolve()
    candidates = [exe.parent, exe.parent / "Scripts"]
    try:
        candidates.append(Path(sysconfig.get_path("scripts")))
        candidates.append(Path(sysconfig.get_path("scripts", scheme="nt_user" if os.name == "nt" else "posix_user")))
    except Exception:
        pass
    try:
        ub = Path(site.getuserbase())
        candidates += [ub / ("Python" + sysconfig.get_python_version().replace(".", "")) / "Scripts", ub / "bin"]
    except Exception:
        pass
    for d in candidates:
        for name in ("convoy-pane-host.exe", "convoy-pane-host"):
            p = d / name
            if p.is_file():
                return str(p)
    return None


def managed_host_argv(root: Path, seat: dict[str, Any]) -> list[str]:
    sid = str(seat.get("session_id") or "").strip()
    if not sid:
        raise ValueError("managed pane host requires a chair session_id")
    # The pane runs a PROGRAM, never an interpreter (grep gate): the console script
    # `convoy-pane-host` installed beside `convoy`. `python -m` survives only as the
    # fallback for a checkout that was never installed.
    host = _pane_host_program()
    head = [str(Path(host).resolve())] if host else [str(Path(sys.executable).resolve()), "-m", "convoy.pane_host"]
    return [*head, "--root", str(Path(root).resolve()), "--seat", sid]


def active_pane_argv(
    seat: dict[str, Any],
    capability: dict[str, Any],
    *,
    root: Path | None = None,
) -> list[str]:
    """Build one terminal split (or detached tmux session) command containing one harness invocation."""
    if not (capability.get("can_split") or capability.get("can_detach") or capability.get("thread_window")):
        raise ValueError(str(capability.get("reason") or "terminal cannot split"))
    worktree = str(seat.get("worktree") or "").strip()
    if not worktree:
        raise ValueError("refuse targeted launch without a worktree")
    harness_argv = pane_child_argv(seat)
    if not harness_argv or not _is_abs_exe(str(harness_argv[0])):
        raise ValueError("refuse targeted launch without an absolute harness executable")
    inner = managed_host_argv(root, seat) if root is not None else harness_argv

    terminal = str(capability.get("executable") or "").strip()
    if not terminal:
        raise ValueError("terminal adapter has no executable")
    adapter = capability.get("adapter")
    if adapter == "windows-terminal-thread":
        window = str(capability.get("target") or "").strip()
        if not window or window == "0" or window.isdigit():
            raise ValueError("refuse a Windows Terminal window that is not the thread's own: " + repr(window))
        # The first neuron opens the thread's window as a tab; later ones split inside it.
        # wt splits that window's focused pane: inside the thread's window that is fine,
        # since it only holds this thread's neurons.
        verb = ["new-tab"] if capability.get("first", True) else ["split-pane", "-V"]
        title = thread_pane_title(str(capability.get("label") or window.removeprefix("convoy-")), seat)
        return [terminal, "-w", window, *verb, "--title", title, "-d", worktree,
                *[a.replace(";", "\\;") for a in inner]]
    if adapter == "tmux":
        pane = str(capability.get("target") or "").strip()
        if not pane:
            raise ValueError("tmux adapter has no caller pane")
        return [
            terminal,
            "split-window",
            "-t",
            pane,
            "-v",
            "-c",
            worktree,
            shlex.join(inner),
        ]
    if adapter == "tmux-detached":
        name = str(capability.get("target") or "").strip()
        if not name:
            raise ValueError("detached tmux adapter has no session name")
        # tmux hands the command to the shell as ONE string: quoted here, so a
        # worktree or boot prompt with spaces stays one argument. One session per
        # thread: the first neuron makes it, later ones split its current window.
        if not capability.get("first", True):
            return [terminal, "split-window", "-t", "=" + name + ":", "-c", worktree, shlex.join(inner)]
        title = thread_pane_title(str(capability.get("label") or name.removeprefix("convoy-")), seat)
        return [terminal, "new-session", "-d", "-s", name, "-n", title, "-c", worktree, shlex.join(inner)]
    raise ValueError("unsupported terminal adapter: " + str(adapter))


def active_pane_runner(argv: list[str]) -> dict[str, Any]:
    """Launch one allowlisted terminal split without a shell.

    A detached tmux session is created synchronously: `new-session -d`
    returns at once, and its exit code is the only evidence the session
    exists (a duplicate name exits 1). A split is fire-and-forget."""
    parts = [str(a) for a in argv]
    if len(parts) > 2 and Path(parts[0]).name.lower().removesuffix(".exe") == "tmux" and parts[1:3] == ["new-session", "-d"]:
        try:
            done = subprocess.run(parts, capture_output=True, text=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            # tmux may have made the session and then stalled: not a launch,
            # but a body may exist, and the card says where to look.
            name = parts[4] if len(parts) > 4 else ""
            return {"ok": False, "error": "tmux did not answer in 30 s; a session may exist: tmux ls" +
                    ("; if it is there: " + tmux_attach_command(name) if name else "")}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
        if done.returncode != 0:
            return {"ok": False, "error": "tmux new-session exited " + str(done.returncode) + ": " +
                    ((done.stderr or "") + (done.stdout or "")).strip()}
        return {"ok": True, "pid": None}
    try:
        proc = subprocess.Popen(parts)
        return {"ok": True, "pid": int(proc.pid)}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}


def _seat_for_launch(root: Path, session_id: str) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    for row in list_seats(root):
        if row.get("session_id") == sid:
            return row
    raise ValueError("unknown seat: " + sid)


def grok_project_trusted(seat: dict[str, Any]) -> bool:
    """Ask Grok's read-only inspect command; never infer or edit its trust store."""
    if _harness_bin(str(seat.get("to") or "")) != "grok":
        return True
    worktree = str(seat.get("worktree") or "").strip()
    executable = pane_child_argv({**seat, "trust_worktree": False})[0]
    try:
        result = subprocess.run(
            [executable, "inspect"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("Grok trust preflight failed: " + str(exc)) from exc
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    lowered = combined.lower()
    if "project trusted: yes" in lowered:
        return True
    if "project trusted: no" in lowered:
        return False
    raise ValueError("Grok trust preflight returned no project trust state")


def _claim_path(root: Path, session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return Path(root) / ".convoy" / "launch-claims" / (digest + ".json")


def release_launch_claim(root: Path, session_id: str) -> bool:
    """Drop the persistent launch claim for a chair whose pane is being
    closed. Returns True when a claim existed."""
    path = _claim_path(Path(root), session_id)
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return existed


def read_launch_claim(root: Path, session_id: str) -> dict[str, Any] | None:
    """The claim on disk, or None. Unreadable is None: a claim nobody can read
    is not evidence of an occupant."""
    path = _claim_path(Path(root), session_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def hosted_live(root: Path, session_id: str) -> bool:
    """A pane host recorded on this chair's launch claim is alive: the chair has a live
    body another launch spawned. A reservation without a host pid, or a dead host, is not."""
    claim = read_launch_claim(root, session_id) or {}
    host = claim.get("host_pid")
    if host is None:
        return False
    from . import pane_host
    return bool(pane_host.host_alive(host, claim.get("host_started")))


def take_launch_claim(root: Path, session_id: str, *, host_pid: int | None = None) -> Path:
    """One body per chair, taken with O_EXCL before anything is spawned.

    Two claimants exist and they are not peers. `launch_seat` reserves the
    chair before it asks the terminal to split, and records no host_pid: that
    row means "a pane is on its way". The lifecycle host it spawned then takes
    the same claim WITH its pid, and is allowed to adopt a reservation or a
    claim whose host is gone — otherwise every managed launch would refuse
    itself. A claim whose host_pid is alive is never taken: that is the
    occupancy refusal (it prevents two live bodies on one chair).

    A reservation records the process that took it (reserver_pid and its start
    time). A claim whose holder (its host, else its reserver) is dead has expired:
    a new reservation adopts it, so an invocation that crashed between claim and
    spawn never blocks the chair forever. A claim naming no holder cannot be judged
    and still refuses.
    """
    from . import pane_host
    path = _claim_path(Path(root), session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"session_id": session_id}
    if host_pid is not None:
        payload["host_pid"] = int(host_pid)
        started = pane_host.process_started(host_pid)
        if started is not None:
            payload["host_started"] = started
    else:
        payload["reserver_pid"] = os.getpid()
        started = pane_host.process_started(os.getpid())
        if started is not None:
            payload["reserver_started"] = started
        payload["reserved_at"] = time.time()
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        if host_pid is None:
            return _adopt_expired(path, data, exc)
        claim = read_launch_claim(root, session_id) or {}
        held = claim.get("host_pid")

        if held is not None and pane_host.host_alive(held, claim.get("host_started")):
            raise ValueError(
                "refuse duplicate launch: chair " + str(session_id) +
                " is already hosted by a live pane host (pid " + str(held) + ")")
        path.write_bytes(data)   # a reservation, or a host that is gone
        return path
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


# A reservation is the launching CLI's; it exits right after wt returns, before the pane
# host adopts the claim. A dead reserver inside this window is a handoff in flight.
RESERVATION_GRACE_S = 30.0


def _claim_expired(claim: dict[str, Any] | None, *, age_s: float | None = None) -> bool:
    """The claim's holder is dead: its host when it names one (expired at once), else the
    process that reserved it, and then only once the reservation is older than
    RESERVATION_GRACE_S. A claim naming neither cannot be judged and is not expired."""
    from . import pane_host
    claim = claim or {}
    if claim.get("host_pid") is not None:
        return not pane_host.host_alive(claim["host_pid"], claim.get("host_started"))
    if claim.get("reserver_pid") is not None:
        if pane_host.host_alive(claim["reserver_pid"], claim.get("reserver_started")):
            return False
        try:
            age = time.time() - float(claim["reserved_at"])
        except (KeyError, TypeError, ValueError):
            age = age_s
        return age is not None and age > RESERVATION_GRACE_S
    return False


def _adopt_expired(path: Path, data: bytes, exc: BaseException) -> Path:
    """Take over an expired claim, or refuse "already claimed". The judged bytes are
    re-read before the unlink and must be identical (another adopter may have replaced
    them), and the new claim is created with O_EXCL: of two adopters exactly one wins.
    A Windows PermissionError on this path (a file in use) is the same refusal."""
    refuse = "refuse duplicate launch: chair already claimed"
    try:
        judged = path.read_bytes()
        mtime_age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        judged, mtime_age = b"", None
    except OSError as err:
        raise ValueError(refuse) from err
    try:
        claim = json.loads(judged.decode("utf-8-sig")) if judged else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        claim = {}
    if judged and not _claim_expired(claim if isinstance(claim, dict) else {}, age_s=mtime_age):
        raise ValueError(refuse) from exc
    try:
        if judged:
            if path.read_bytes() != judged:
                raise ValueError(refuse) from exc
            path.unlink()
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except (FileExistsError, FileNotFoundError, PermissionError) as err:
        raise ValueError(refuse) from err
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _claim(root: Path, session_id: str) -> Path:
    """Launcher-side reservation; see take_launch_claim."""
    return take_launch_claim(root, session_id)


def launch_seat(
    root: Path,
    session_id: str,
    *,
    runner: Runner | None = None,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
    consent: str | None = None,
    trust_probe: Callable[[dict[str, Any]], bool] = grok_project_trusted,
    allow_unverified_launch: bool = False,
    write_repo_files: bool | None = None,
    claimed: bool = False,
) -> dict[str, Any]:
    """Plan or launch one fresh join/swap chair.

    claimed=True: the caller already holds this chair's launch reservation (the CLI takes it
    before recording launched_by); it is used, not taken again, and the caller releases it
    when the launch does not spawn.

    write_repo_files None writes every repo file only into a minted worktree (ensure_first_run);
    True is the person's --write-repo-files.

    ``runner=None`` is a read-only dry run. A live call creates an atomic,
    persistent claim before spawning, so two callers cannot split two panes for
    the same chair. A spawn failure removes the claim and leaves the chair
    pending for an explicit retry.
    """
    try:
        row = _seat_for_launch(root, session_id)
        if runner is not None:
            from .harness_contract import validate_launch_eligibility
            validate_launch_eligibility(row.get("to"), allow_unverified_launch=allow_unverified_launch)
        if resume_target(row) is not None or not str(row.get("boot_prompt") or "").strip():
            raise ValueError("refuse launch: chair is not a fresh join/swap")
        if row.get("where") == "cloud":
            # A pane is a local process; splitting one for a cloud chair would
            # label a local session "cloud". No cloud launcher exists (2026-09-04).
            raise ValueError("refuse launch: chair " + session_id + " is where=cloud and no cloud launcher exists; a pane is not a cloud session")
        worktree = str(row.get("worktree") or "").strip()
        if not worktree:
            raise ValueError("refuse targeted launch without a worktree")
        if not Path(worktree).is_dir():
            raise ValueError("refuse missing worktree: " + worktree)
        if not trust_probe(row) and not row.get("trust_worktree"):
            if not consent:
                waiting = request_consent(
                    root,
                    "trust-worktree",
                    session_id=session_id,
                    to=str(row.get("to") or ""),
                    worktree=worktree,
                )
                return {"session_id": session_id, **waiting}
            consume_consent(
                root,
                consent,
                "trust-worktree",
                session_id=session_id,
                to=str(row.get("to") or ""),
                worktree=worktree,
            )
            row = update_seat(root, session_id, trust_worktree=True)
        if runner is not None:
            # The prompt's lead and launcher line is the thread as it is now, not at join.
            from .lifecycle import refresh_identity
            row = refresh_identity(root, row)
        capability = placement_capability(root, row, env=env, which=which, platform_name=platform_name)
        if capability is None:
            raise ValueError(
                "no supported active pane; use `convoy choices` and open a pane manually"
            )

        effective = row
        first_run: dict[str, Any] | None = None
        if runner is not None:
            first_run = ensure_first_run(row, root=root, write_repo_files=write_repo_files)
            if first_run.get("ok") is False:
                raise ValueError(str(first_run.get("error") or "first-run preparation failed"))
            effective = _seat_with_agent(root, row, first_run)
        harness_argv = pane_child_argv(effective)
        argv = active_pane_argv(effective, capability, root=root)
        card: dict[str, Any] = {
            "ok": True,
            "session_id": session_id,
            "to": row.get("to"),
            "worktree": worktree,
            "adapter": capability.get("adapter"),
            "target": capability.get("target"),
            "target_semantics": capability.get("target_semantics"),
            "can_close_exact": bool(capability.get("can_close_exact")),
            "close_reason": capability.get("close_reason"),
            "placement": ("split" if capability.get("can_split") else
                          "thread-window" if capability.get("thread_window") else "detached"),
            "argv": argv,
            "harness_argv": harness_argv,
            "dry_run": runner is None,
        }
        if capability.get("thread_window"):
            card["window"] = capability.get("target")
        elif not capability.get("can_split"):
            card["attach"] = tmux_attach_command(str(capability.get("target")))
        if first_run is not None:
            card["first_run"] = {"would_write": list(first_run.get("would_write") or []),
                                 "notes": list(first_run.get("notes") or []),
                                 "trust_stores_written": list(first_run.get("trust_stores_written") or [])}
        if runner is None:
            return card

        claim = _claim_path(Path(root), session_id) if claimed else _claim(root, session_id)
        try:
            result = runner(argv)
        except Exception as exc:
            claim.unlink(missing_ok=True)
            raise ValueError(type(exc).__name__ + ": " + str(exc)) from exc
        if not isinstance(result, dict) or result.get("ok") is False:
            claim.unlink(missing_ok=True)
            error = result.get("error") if isinstance(result, dict) else None
            raise ValueError(str(error or "terminal adapter failed"))
        update_seat(
            root,
            session_id,
            launch_state="launched",
            launch_adapter=capability.get("adapter"),
            launcher_pid=result.get("pid"),
        )
        card["dry_run"] = False
        if result.get("pid") is not None:
            card["pid"] = result["pid"]
        return card
    except (OSError, ValueError) as exc:
        return {"ok": False, "session_id": session_id, "error": str(exc)}


def _discover_git_worktrees(paths: Iterable[Path]) -> list[str]:
    found: list[str] = []
    for candidate in paths:
        try:
            base = Path(candidate).resolve()
        except Exception:
            continue
        if not base.is_dir():
            continue
        try:
            run = subprocess.run(
                ["git", "-C", str(base), "worktree", "list", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if run.returncode != 0:
            continue
        for line in run.stdout.splitlines():
            if line.startswith("worktree "):
                found.append(line.removeprefix("worktree ").strip())
    return found


def launch_choices(
    root: Path,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    which: Which = shutil.which,
    platform_name: str | None = None,
    git_worktrees: GitWorktrees = _discover_git_worktrees,
) -> dict[str, Any]:
    """List enough safe facts to choose a harness and worktree without memory."""
    rows = list_seats(root)
    seats = [
        {
            "session_id": row.get("session_id"),
            "to": row.get("to"),
            "model": row.get("model"),
            "title": row.get("title"),
            "where": row.get("where"),
            "worktree": row.get("worktree"),
        }
        for row in rows
    ]
    harnesses = []
    for entry in harness_entries():
        executable = harness_exec(str(entry.get("id") or ""))
        path = which(executable)
        catalog = model_catalog(str(entry.get("id") or ""))
        harnesses.append(
            {
                "id": entry.get("id"),
                "name": entry.get("name"),
                "installed": bool(path),
                "executable": str(path) if path else None,
                # Per-harness effort straight from harness_effort.json so a
                # host on the wire can render harness -> effort without the
                # file; null where the contract is silent.
                "effort": effort_contract(str(entry.get("id") or "")),
                # Same for the model catalog: null (with the evidence saying
                # why) wherever no local --help enumerates a closed list.
                "models": catalog["models"],
                "models_evidence": catalog["evidence"],
                # local always; cloud offered only where the contract quotes
                # an interactive attach, else {offered: false, mode, evidence}
                # so the card can say why before a join is refused.
                "where": where_options(str(entry.get("id") or "")),
                # How a launched neuron receives (inbox.HARNESS_INBOX): hook,
                # native-queue-or-cli-drain, or cli-drain. A label the card
                # shows so a hookless harness is never sold as auto-connecting;
                # the seated row, not this word, is the connection.
                "connect_mode": connect_mode(str(entry.get("id") or "")),
            }
        )

    current = Path.cwd() if cwd is None else Path(cwd)
    candidates = [Path(root), current]
    registered = [str(row.get("worktree")) for row in rows if row.get("worktree")]
    discovered = git_worktrees(candidates)
    worktrees: list[str] = []
    seen_worktrees: set[str] = set()
    for value in [*registered, *discovered, str(current)]:
        if not value:
            continue
        try:
            rendered = str(Path(value).resolve())
        except Exception:
            rendered = str(value)
        key = os.path.normcase(os.path.normpath(rendered))
        if key not in seen_worktrees:
            seen_worktrees.add(key)
            worktrees.append(rendered)
    return {
        "ok": True,
        "terminal": terminal_capability(env=env, which=which, platform_name=platform_name),
        "harnesses": harnesses,
        "worktrees": worktrees,
        "seats": seats,
        "example": "convoy join --to <harness> --worktree <path> --launch",
    }
