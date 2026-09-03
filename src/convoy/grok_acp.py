"""Grok ACP session-message client.

Grok's TUI has no `grok queue`. Inbox + PreToolUse is deferred delivery at
tool time, not a wake. The vendor session-message API is ACP `session/prompt`
over `grok agent stdio` (NDJSON JSON-RPC; the published TS client writes one
JSON object per line). A live TUI is itself an ACP client of an in-process
or leader-backed agent.

- Throwaway / ACP-hosted seat: `grok agent --always-approve --no-leader stdio`
  then `session/new` + `session/prompt`.
- Live TUI: only when a leader is up. Connect `grok agent --leader stdio`,
  `session/resume` (or `session/load`) the vendor session id, then
  `session/prompt`. Loading a pid-held TUI session from a second
  `--no-leader` agent is a steal; refuse.
- Never grok `-p` / `-c`, never `--resume` of a live TUI, never WM_CHAR.

A successful `session/prompt` is `delivery: native-queued`, not delivered.
Delivery is the occupant's ack citing the inbox token.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ACP_PONG = "ACP_PONG"
PROTOCOL_VERSION = 1
CLIENT_INFO = {"name": "convoy", "title": "Convoy", "version": "0.1.0"}
DEFAULT_INIT_TIMEOUT = 45.0
DEFAULT_RPC_TIMEOUT = 45.0
DEFAULT_PROMPT_TIMEOUT = 120.0


class AcpError(RuntimeError):
    def __init__(self, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = payload or {}


def grok_bin() -> str | None:
    return shutil.which("grok") or shutil.which("grok.exe") or shutil.which("grok.CMD")


def leader_socket_path() -> Path:
    env = str(os.environ.get("GROK_LEADER_SOCKET") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".grok" / "leader.sock"


def active_tui_sessions(path: Path | None = None) -> list[dict[str, Any]]:
    dest = path or (Path.home() / ".grok" / "active_sessions.json")
    if not dest.is_file():
        return []
    try:
        raw = json.loads(dest.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def looks_like_grok_vendor_id(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    parts = text.split("-")
    if len(parts) != 5:
        return False
    widths = (8, 4, 4, 4, 12)
    hexdigits = set("0123456789abcdef")
    return all(len(p) == w and set(p) <= hexdigits for p, w in zip(parts, widths))


def vendor_session_for_cwd(cwd: str | Path | None) -> str | None:
    if cwd is None:
        return None
    try:
        want = Path(cwd).resolve()
    except OSError:
        return None
    for row in active_tui_sessions():
        raw = row.get("cwd")
        sid = row.get("session_id")
        if not isinstance(raw, str) or not isinstance(sid, str):
            continue
        try:
            if Path(raw).resolve() == want:
                return sid
        except OSError:
            continue
    return None


def leader_status(*, socket: Path | None = None, exe: str | None = None) -> dict[str, Any]:
    """Is a grok leader accepting clients? `grok leader list` is SoT."""
    bin_path = exe or grok_bin()
    sock = socket or leader_socket_path()
    out: dict[str, Any] = {
        "ok": bool(bin_path),
        "available": False,
        "socket": str(sock),
        "socket_exists": sock.exists(),
        "raw": None,
        "error": None,
    }
    if not bin_path:
        out["error"] = "grok not on PATH"
        return out
    cmd = [bin_path, "leader", "list"]
    if socket is not None:
        cmd.extend(["--leader-socket", str(socket)])
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        out["error"] = type(e).__name__ + ": " + str(e)
        return out
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    out["raw"] = text[-1500:] if text else ""
    out["exit_code"] = result.returncode
    if result.returncode == 0 and text and "no leader" not in text.lower():
        out["available"] = True
    return out


class AcpClient:
    """One `grok agent stdio` (or a test fake) speaking NDJSON JSON-RPC."""

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.argv = list(argv)
        self.cwd = str(cwd) if cwd is not None else None
        self._id = 0
        self._pending: dict[int, dict[str, Any]] = {}
        self._notifications: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._dead = False
        self._stderr_chunks: list[str] = []
        self.initialize_result: dict[str, Any] | None = None
        merged = os.environ.copy()
        if env:
            merged.update(env)
        merged.setdefault("GROK_DISABLE_AUTOUPDATER", "1")
        self.proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=merged,
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._err_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._err_thread.start()

    def _read_stderr(self) -> None:
        err = self.proc.stderr
        if err is None:
            return
        try:
            while True:
                chunk = err.readline()
                if not chunk:
                    break
                self._stderr_chunks.append(chunk.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            return

    def _read_stdout(self) -> None:
        out = self.proc.stdout
        if out is None:
            self._mark_dead()
            return
        buf = b""
        try:
            while True:
                chunk = out.readline()
                if not chunk:
                    break
                buf += chunk
                while True:
                    msg, buf = _take_message(buf)
                    if msg is None:
                        break
                    self._dispatch(msg)
        except (OSError, ValueError):
            pass
        self._mark_dead()

    def _mark_dead(self) -> None:
        with self._cv:
            self._dead = True
            self._cv.notify_all()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        has_id = "id" in msg
        is_result = has_id and ("result" in msg or "error" in msg)
        if has_id and method and not is_result:
            self._answer_agent_request(msg)
            return
        with self._cv:
            if is_result:
                try:
                    rid = int(msg["id"])
                except (TypeError, ValueError):
                    rid = msg["id"]
                self._pending[rid] = msg
            else:
                self._notifications.append(msg)
            self._cv.notify_all()

    def _answer_agent_request(self, msg: dict[str, Any]) -> None:
        method = str(msg.get("method") or "")
        req_id = msg.get("id")
        if method == "session/request_permission":
            option_id = _first_allow_option(msg.get("params") or {})
            result: dict[str, Any]
            if option_id:
                result = {"outcome": {"outcome": "selected", "optionId": option_id}}
            else:
                result = {"outcome": {"outcome": "cancelled"}}
            self._write({"jsonrpc": "2.0", "id": req_id, "result": result})
            return
        self._write({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": "method not supported by convoy acp client: " + method},
        })

    def _write(self, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"
        stdin = self.proc.stdin
        if stdin is None:
            raise AcpError("agent stdin closed")
        with self._lock:
            stdin.write(raw)
            stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = DEFAULT_RPC_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)
        deadline = time.time() + timeout
        with self._cv:
            while True:
                if rid in self._pending:
                    msg = self._pending.pop(rid)
                    if msg.get("error"):
                        err = msg["error"]
                        raise AcpError(
                            method + " error: " + json.dumps(err)[:800],
                            payload=msg,
                        )
                    result = msg.get("result")
                    return result if isinstance(result, dict) else {"value": result}
                if self._dead:
                    raise AcpError(
                        method + ": agent exited before reply; stderr=" + self.stderr()[-800:],
                    )
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise AcpError(method + ": timed out after " + str(timeout) + "s")
                self._cv.wait(timeout=min(0.5, remaining))

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._write(payload)

    def initialize(self, *, timeout: float = DEFAULT_INIT_TIMEOUT) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientInfo": CLIENT_INFO,
                "clientCapabilities": {
                    "fs": {"readTextFile": False, "writeTextFile": False},
                },
            },
            timeout=timeout,
        )
        self.initialize_result = result
        try:
            self.notify("notifications/initialized", {})
        except AcpError:
            pass
        return result

    def session_new(self, cwd: str | Path, *, yolo: bool = True) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cwd": str(Path(cwd).resolve()),
            "mcpServers": [],
        }
        if yolo:
            params["_meta"] = {"yoloMode": True}
        return self.request("session/new", params)

    def session_load(self, session_id: str, cwd: str | Path) -> dict[str, Any]:
        return self.request(
            "session/load",
            {
                "sessionId": session_id,
                "cwd": str(Path(cwd).resolve()),
                "mcpServers": [],
            },
            timeout=DEFAULT_PROMPT_TIMEOUT,
        )

    def session_resume(self, session_id: str, cwd: str | Path) -> dict[str, Any]:
        return self.request(
            "session/resume",
            {
                "sessionId": session_id,
                "cwd": str(Path(cwd).resolve()),
                "mcpServers": [],
            },
        )

    def session_resume_or_load(self, session_id: str, cwd: str | Path) -> dict[str, Any]:
        caps = (self.initialize_result or {}).get("agentCapabilities") or {}
        resume_cap = False
        if isinstance(caps, dict):
            session_caps = caps.get("sessionCapabilities") or {}
            if isinstance(session_caps, dict) and "resume" in session_caps:
                resume_cap = True
        if resume_cap:
            try:
                return {"ok": True, "via": "session/resume", "result": self.session_resume(session_id, cwd)}
            except AcpError as e:
                return {"ok": False, "via": "session/resume", "error": str(e), "payload": e.payload}
        if caps.get("loadSession"):
            try:
                return {"ok": True, "via": "session/load", "result": self.session_load(session_id, cwd)}
            except AcpError as e:
                return {"ok": False, "via": "session/load", "error": str(e), "payload": e.payload}
        return {"ok": False, "via": None, "error": "agent advertises neither session/resume nor loadSession"}

    def session_prompt(self, session_id: str, text: str, *, timeout: float = DEFAULT_PROMPT_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            before = len(self._notifications)
        result = self.request(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": str(text)}],
            },
            timeout=timeout,
        )
        chunks: list[str] = []
        with self._lock:
            for msg in self._notifications[before:]:
                chunks.extend(_agent_text_chunks(msg))
        return {
            "ok": True,
            "result": result,
            "stop_reason": result.get("stopReason") if isinstance(result, dict) else None,
            "text": "".join(chunks),
        }

    def drain_notifications(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._notifications)
            self._notifications.clear()
            return items

    def stderr(self) -> str:
        return "".join(self._stderr_chunks)

    def close(self) -> None:
        proc = self.proc
        if proc.poll() is None:
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._mark_dead()

    def __enter__(self) -> "AcpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _take_message(buf: bytes) -> tuple[dict[str, Any] | None, bytes]:
    """Pull one JSON-RPC message. NDJSON, or LSP Content-Length if present."""
    if not buf:
        return None, buf
    lower = buf.lower()
    if lower.startswith(b"content-length:"):
        header_end = buf.find(b"\r\n\r\n")
        sep_len = 4
        if header_end < 0:
            header_end = buf.find(b"\n\n")
            sep_len = 2
        if header_end < 0:
            return None, buf
        try:
            n = int(buf.split(b":", 1)[1].split(b"\n", 1)[0].strip())
        except ValueError:
            return None, buf[header_end + sep_len:]
        start = header_end + sep_len
        if len(buf) < start + n:
            return None, buf
        body = buf[start:start + n]
        rest = buf[start + n:]
        try:
            msg = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None, rest
        return (msg if isinstance(msg, dict) else None), rest
    nl = buf.find(b"\n")
    if nl < 0:
        return None, buf
    line = buf[:nl].strip()
    rest = buf[nl + 1:]
    if not line or line[:1] != b"{":
        return None, rest
    try:
        msg = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError:
        return None, rest
    return (msg if isinstance(msg, dict) else None), rest


def _first_allow_option(params: Any) -> str | None:
    if not isinstance(params, dict):
        return None
    options = params.get("options")
    if not isinstance(options, list):
        return None
    allow: str | None = None
    first: str | None = None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        oid = opt.get("optionId")
        if not isinstance(oid, str) or not oid:
            continue
        if first is None:
            first = oid
        kind = str(opt.get("kind") or "").lower()
        if kind.startswith("allow"):
            return oid
        if allow is None and "allow" in kind:
            allow = oid
    return allow or first


def _agent_text_chunks(msg: dict[str, Any]) -> list[str]:
    """Pull agent_message_chunk text once. Grok nests it at params.update."""
    found: list[str] = []
    params = msg.get("params")
    if not isinstance(params, dict):
        return found
    update = params.get("update")
    node = update if isinstance(update, dict) else params
    kind = str(node.get("sessionUpdate") or "")
    content = node.get("content")
    if kind == "agent_message_chunk" and isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            found.append(text)
    return found


def agent_argv(
    *,
    leader: bool = False,
    socket: Path | str | None = None,
    extra: list[str] | None = None,
    exe: str | None = None,
) -> list[str]:
    bin_path = exe or grok_bin()
    if not bin_path:
        raise AcpError("grok not on PATH")
    argv = [bin_path, "agent", "--always-approve"]
    if leader:
        argv.append("--leader")
    else:
        argv.append("--no-leader")
    if socket is not None:
        argv.extend(["--leader-socket", str(socket)])
    if extra:
        argv.extend(extra)
    argv.append("stdio")
    return argv


def spawn_agent(
    *,
    leader: bool = False,
    socket: Path | str | None = None,
    cwd: str | Path | None = None,
    exe: str | None = None,
    extra: list[str] | None = None,
    argv: list[str] | None = None,
) -> AcpClient:
    return AcpClient(argv or agent_argv(leader=leader, socket=socket, extra=extra, exe=exe), cwd=cwd)


def capabilities_card(result: dict[str, Any]) -> dict[str, Any]:
    caps = result.get("agentCapabilities") if isinstance(result, dict) else None
    if not isinstance(caps, dict):
        caps = {}
    session_caps = caps.get("sessionCapabilities") if isinstance(caps.get("sessionCapabilities"), dict) else {}
    return {
        "protocolVersion": result.get("protocolVersion"),
        "agentInfo": result.get("agentInfo"),
        "loadSession": bool(caps.get("loadSession")),
        "resume": "resume" in session_caps,
        "promptCapabilities": caps.get("promptCapabilities"),
        "mcpCapabilities": caps.get("mcpCapabilities"),
        "authMethods": result.get("authMethods"),
        "meta_keys": sorted((result.get("_meta") or {}).keys()) if isinstance(result.get("_meta"), dict) else [],
    }


def probe_session_prompt(*, cwd: str | Path | None = None, exe: str | None = None) -> dict[str, Any]:
    """Throwaway session/new + session/prompt. Never attaches a live TUI."""
    work = Path(cwd) if cwd is not None else Path(tempfile.mkdtemp(prefix="convoy-grok-acp-"))
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    card: dict[str, Any] = {
        "ok": False,
        "kind": "session/prompt",
        "cwd": str(work),
        "session_id": None,
        "pong": False,
        "text": None,
        "capabilities": None,
        "elapsed_ms": None,
        "error": None,
    }
    try:
        with spawn_agent(leader=False, cwd=work, exe=exe) as client:
            init = client.initialize()
            card["capabilities"] = capabilities_card(init)
            created = client.session_new(work)
            sid = created.get("sessionId")
            card["session_id"] = sid
            if not isinstance(sid, str) or not sid.strip():
                card["error"] = "session/new returned no sessionId: " + json.dumps(created)[:500]
                return card
            prompted = client.session_prompt(
                sid,
                "Do not use tools. Do not read files. Reply with exactly the token "
                + ACP_PONG
                + " and then stop.",
            )
            text = str(prompted.get("text") or "")
            card["text"] = text[:2000]
            card["stop_reason"] = prompted.get("stop_reason")
            card["pong"] = ACP_PONG in text
            card["ok"] = True
            if not card["pong"]:
                # The wire worked even if the model did not echo the token.
                card["note"] = "session/prompt returned; token not in streamed text"
            return card
    except AcpError as e:
        card["error"] = str(e)
        return card
    finally:
        card["elapsed_ms"] = int((time.time() - t0) * 1000)


def probe_shared_leader(*, exe: str | None = None) -> dict[str, Any]:
    """Two ACP clients on a private leader: does B's session/prompt reach A?

    This is the TUI-wake analog. A live TUI is client A; Convoy is client B.
    Never uses the occupant's TUI session id.
    """
    bin_path = exe or grok_bin()
    t0 = time.time()
    card: dict[str, Any] = {
        "ok": False,
        "kind": "leader-share",
        "available": False,
        "shared": False,
        "via": None,
        "session_id": None,
        "pong": False,
        "error": None,
    }
    if not bin_path:
        card["error"] = "grok not on PATH"
        return card
    tmp = Path(tempfile.mkdtemp(prefix="convoy-grok-leader-"))
    sock = tmp / "leader.sock"
    work = tmp / "cwd"
    work.mkdir()
    leader_cmd = [
        bin_path, "agent", "--always-approve",
        "--leader-socket", str(sock),
        "leader", "--no-exit-on-disconnect", "--relay-on-demand",
    ]
    leader = None
    client_a = None
    client_b = None
    try:
        err_path = tmp / "leader.stderr"
        err_handle = err_path.open("wb")
        leader = subprocess.Popen(
            leader_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=err_handle,
            cwd=str(work),
            env={**os.environ, "GROK_DISABLE_AUTOUPDATER": "1"},
        )
        if not _wait_leader(sock, exe=bin_path, timeout=12.0):
            try:
                err_handle.close()
            except OSError:
                pass
            err = ""
            try:
                err = err_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                err = ""
            card["error"] = (
                "leader did not come up: "
                + (err or "grok leader list empty; on this host leader.sock was not created")
            )[:800]
            card["leader_exit"] = leader.poll()
            card["socket_exists"] = sock.exists()
            return card
        try:
            err_handle.close()
        except OSError:
            pass
        card["available"] = True
        client_a = spawn_agent(leader=True, socket=sock, cwd=work, exe=bin_path)
        client_a.initialize()
        created = client_a.session_new(work)
        sid = created.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            card["error"] = "client A session/new returned no sessionId"
            return card
        card["session_id"] = sid
        client_b = spawn_agent(leader=True, socket=sock, cwd=work, exe=bin_path)
        init_b = client_b.initialize()
        card["capabilities"] = capabilities_card(init_b)
        loaded = client_b.session_resume_or_load(sid, work)
        card["via"] = loaded.get("via")
        if not loaded.get("ok"):
            card["error"] = "client B could not attach: " + str(loaded.get("error") or loaded)
            return card
        prompted = client_b.session_prompt(
            sid,
            "Do not use tools. Reply with exactly the token " + ACP_PONG + " and then stop.",
        )
        text_b = str(prompted.get("text") or "")
        # Give A a moment to receive the same updates over the shared leader.
        deadline = time.time() + 8.0
        text_a = ""
        while time.time() < deadline:
            for msg in client_a.drain_notifications():
                text_a += "".join(_agent_text_chunks(msg))
            if ACP_PONG in text_a:
                break
            time.sleep(0.2)
        card["text_b"] = text_b[:1500]
        card["text_a"] = text_a[:1500]
        card["pong"] = ACP_PONG in text_b or ACP_PONG in text_a
        card["shared"] = bool(text_a.strip()) or ACP_PONG in text_a
        card["ok"] = True
        if not card["shared"]:
            card["note"] = (
                "client B session/prompt succeeded, but client A saw no streamed "
                "chunks — leader may exclusive-lock the session (TUI wake still blocked)"
            )
        return card
    except AcpError as e:
        card["error"] = str(e)
        return card
    finally:
        card["elapsed_ms"] = int((time.time() - t0) * 1000)
        for client in (client_b, client_a):
            if client is not None:
                try:
                    client.close()
                except OSError:
                    pass
        if leader is not None and leader.poll() is None:
            try:
                leader.terminate()
                leader.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    leader.kill()
                except OSError:
                    pass


def _wait_leader(socket: Path, *, exe: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = leader_status(socket=socket, exe=exe)
        if status.get("available"):
            return True
        time.sleep(0.4)
    return False


def try_grok_acp(
    session_id: str | None,
    body: str,
    *,
    cwd: str | Path | None = None,
    leader_required: bool = True,
) -> dict[str, Any] | None:
    """Push `body` into an existing Grok vendor session via ACP.

    Returns a native-queued card, or None so the caller falls back to inbox.
    Refuses `--no-leader` attach to a pid-held TUI session (that is a steal).
    """
    sid = str(session_id or "").strip()
    if not sid or not looks_like_grok_vendor_id(sid):
        if cwd is not None:
            sid = str(vendor_session_for_cwd(cwd) or "").strip()
        if not sid or not looks_like_grok_vendor_id(sid):
            return None
    if not grok_bin():
        return None
    status = leader_status()
    if leader_required and not status.get("available"):
        return None
    held = {str(row.get("session_id") or "") for row in active_tui_sessions()}
    if sid in held and not status.get("available"):
        return None
    try:
        with spawn_agent(leader=bool(status.get("available")), cwd=cwd) as client:
            client.initialize()
            loaded = client.session_resume_or_load(sid, cwd or Path.cwd())
            if not loaded.get("ok"):
                return None
            prompted = client.session_prompt(sid, body)
            return {
                "ok": True,
                "runner": "grok-acp",
                "delivery": "native-queued",
                "exit_code": 0,
                "session_id": sid,
                "via": loaded.get("via"),
                "stop_reason": prompted.get("stop_reason"),
                "leader": bool(status.get("available")),
            }
    except AcpError:
        return None


def cli_grok_acp(args: Any) -> dict[str, Any]:
    """CLI entry: probe the vendor API, or refuse a steal."""
    if getattr(args, "probe", False):
        card = probe_session_prompt()
        if getattr(args, "share", False):
            card["share"] = probe_shared_leader()
            if card.get("ok") and not card["share"].get("ok"):
                # Probe of session/prompt still counts as ungating the API.
                pass
        card["leader"] = leader_status()
        return card
    message = str(getattr(args, "message", None) or "").strip()
    session_id = str(getattr(args, "session_id", None) or "").strip() or None
    cwd = getattr(args, "cwd", None)
    if session_id and message:
        held = {str(row.get("session_id") or "") for row in active_tui_sessions()}
        status = leader_status()
        if session_id in held and not status.get("available"):
            return {
                "ok": False,
                "error": "refuse: session is a live TUI and no grok leader is up; "
                         "session/load from a second --no-leader agent would steal. "
                         "Launch the seat with grok --leader, or use inbox / PreToolUse.",
                "session_id": session_id,
                "leader": status,
            }
        if getattr(args, "leader", False) and not status.get("available"):
            return {
                "ok": False,
                "error": "no grok leader is up",
                "session_id": session_id,
                "leader": status,
            }
        pushed = try_grok_acp(session_id, message, cwd=cwd)
        if pushed is None:
            return {
                "ok": False,
                "error": "grok-acp did not attach (no leader, or session/resume failed)",
                "session_id": session_id,
                "leader": status,
            }
        return pushed
    return {
        "ok": True,
        "kind": "status",
        "leader": leader_status(),
        "active_tui": active_tui_sessions(),
        "hint": "convoy grok-acp --probe  (throwaway session/prompt; add --share to try a private leader)",
    }
