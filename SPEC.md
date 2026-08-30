# Convoy

**Repo:** `deploy-forward/convoy` (Grok Bot HTTP MCP + hop CLI)
**Sibling:** `deploy-forward/deploy-forward` (`npx deploy-forward`, tracker, board)
**Native platform:** `Deploy-Forward/platform` (NOT this MCP)
**Sites:** https://convoy.bot (Grok Bot MCP + frontmatter, tweet this) · https://convoy.deployforward.dev (launch product, not live yet, not the tweet)
**Audience:** engineers who can read a CLI, a JSON card, and a git checkout.
**Status of this tree:** work lives at `/workspace/convoy` on the Grok Bot box. Public repo: `https://github.com/Deploy-Forward/convoy`. Names: see `CANON.md`.

This file is the source of truth for **this repo only**. Native platform Convoy and the public capture layer are sibling products. Do not put this MCP in `Deploy-Forward/platform`.

Convoy lets you stay in one thread and send work to other harnesses (Grok, Claude, Codex, cursor-agent, agy) without merging their native sessions. The other harness works on its own meter. You get a compact result back. Main context stays skinny.

That sentence is the product. Everything below is how it is actually true, or honestly not true yet.

Bring your own harness. Do not bring your own API key into Claude Code. Named refuse: UltraCode-Shim (OnlyTerp). We do not wrap Grok as `claude-grok-4-6`. We do not proxy `cli-chat-proxy.grok.com`.

---

## Canonical lock (2026-08-30)

This block is authoritative for Grok Bot MCP layering and native-send DoD. If older notes below disagree, this block wins until they are rewritten.

### Locked layer statement

> Grok Bot is the opposite layer from Herdr and CNVS. This Grok Bot chat is the conductor. MCP is how the conductor attaches (`roster`, `onboard`, `send`, `feed`, `context`, `bring_up`/`open`, `terminals`; tree also has `install` and `hide`). Convoy is the SoT: one visible thread, one `cvy_id`, one tied repo, seats that hop without merging native sessions. Default `send` is headless on purpose. `bring_up` is the terminal view, hashed `--resume`, isolated n-pane. Same-branch overlap is refused. Pointers in, compact card out.
>
> Bring your own harness. Do not wrap the model. Named refuse: UltraCode-Shim, ola-brain as the product, grok `-p`/`-c`, wrapping Grok as `claude-grok-4-6`.

### Neighbors (canonical contrast)

- **Herdr (`herdr.dev`)** owns PTYs on a background server and agents type into sibling TUIs. Convoy does not use PTY paste as the hop bus and does not rebuild Herdr inside this MCP.
- **CNVS (`cnvs.dev`, Max Blade, closed-source macOS Swift ADE)** is voice + infinite canvas with in-app army controls. Convoy is one visible thread + one `cvy_id` + tied checkout contract, not a canvas product.
- **Buzz** is Slack-shaped agent chat. Out of scope except one contrast: their missing terminal view is why `bring_up` exists.

### Current code honesty (tree-verified)

- `src/convoy/mcp_http.py` `call_tool("send", ...)` sets `runner = ola_runner if live else fake_runner`.
- `src/convoy/synapse.py` `ola_runner` executes `ola-brain side-chat send`.
- `src/convoy/mcp_http.py` `TOOLS` includes `onboard`, `hide`, and `install` (plus aliases), but a deployed process can still expose the 7-tool snapshot (`roster`, `send`, `feed`, `context`, `bring_up`, `open`, `terminals`).
- `src/convoy/bringup.py` and `src/convoy/install.py` refuse wrapper names (`ola-brain`, `side-chat`, `UltraCode-Shim`) for those tool paths.

### Native-send + structured talk DoD (locked)

#### Definition

Status: **RED** until live functions pass on `https://convoy.bot/mcp` without shell paste.

#### Successful functions (today)

- **PARTIAL GREEN:** attach/`roster`/`context`/`feed` at MCP layer are attachable.
- **RED:** native live `send` is not done while `live=true` routes through `ola_runner` (`ola-brain side-chat send`).
- **GREEN (scope guard):** `bring_up` and `install` refusal paths already reject wrapper targets.

Until item (1) exists in code, items (2) and (3) cannot be GREEN. Fake dual-send is not talk. `ola_runner` success on one machine is not stranger-attachable proof.

#### Pseudo-code (target shape, not today-file prescription)

```python
def native_send(to, body, context_pack, worktree=None, model=None):
    exe = resolve_vendor_binary_on_path(to)  # grok/claude/codex/cursor-agent/agy
    refuse_wrappers(exe)  # never ola-brain/side-chat/UltraCode-Shim
    stdin_payload = context_pack_pointers_plus_body(context_pack, body)
    card = run_vendor_cli(exe, stdin=stdin_payload, cwd=worktree, model=model)
    return compact_card_real_or_null(card)
```

Native runner work should follow the same PATH-exec principle already used by `bringup.resume_argv` for TUI resume.

#### Implementation notes

- Keep Convoy as SoT (`feed` + pointers + seats).
- Keep `send` headless by default.
- Keep same-branch overlap refusal.
- Keep `bring_up` as the only show command.
- Do not wrap the model.

#### Definition of done (all required for GREEN)

1. **Native BYO send.** Live `send` executes vendor binary on PATH (`grok`, `claude`, `codex`, `cursor-agent`, `agy`). Never `ola-brain`, never `side-chat`, never UltraCode-Shim, never grok `-p`/`-c`. BYO harness/login. `stdin` is `context.pack` pointers plus body. Compact card fields are real or JSON `null` only: `ok`, `to`, `session_id`, `model`, `usage_remaining`, `body`, `convoy_id`, `worktree`, `branch`, `pr`.
2. **Structured talk (not Herdr PTY paste).** Conductor `send` to grok stamps a synapse row. Conductor `send` to claude on same `cvy_id` includes those pointers. Claude card stamps as a new row. `feed --since` from conductor shows both. Neither hop typed into the other's TUI. Neither merged native sessions. Same-branch overlap still refuses.
3. **Stranger attach.** A second Grok Bot (or fresh bind) attaches same MCP URL and same `convoy_id`; `roster` lists seats; `feed` shows talk; `send` hops without `ola-brain` on PATH. Tied checkout fields remain on every card.

Live checks for GREEN:

- `send` `live=true` `to=grok` with unique body token returns that token and process argv is vendor CLI, not `ola-brain side-chat send`.
- Two sends (two `to`s) produce two `session_id`s and two `kind=synapse` rows visible to a second attached client.
- `install to=ola-brain` and `install to=ultracode-shim` refuse; `bring_up` argv never contains those names.

Phase gate note: this is the remaining MCP-attach/send hole inside Phase 7. Do not start a fake Phase 8 while Phase 7 resume-hop remains RED.

---

## Three products (do not collapse them)

| Product | Repo | What it is | What it is not |
|---|---|---|---|
| Convoy MCP + hop CLI | `deploy-forward/convoy` | HTTP MCP tools (`roster`, `onboard`, `terminals`, `context`, `send`, `feed`) plus a Python hop CLI that stamps a layer and fires harness CLIs | Not the native Composer `turn.send`. Not `npx deploy-forward` itself. |
| Installer / tracker / board | `deploy-forward/deploy-forward` | `npx deploy-forward --convoy --tracker --board`. White-glove attach. Tracking and the public board. | Not the MCP process. Board requires tracker. |
| Native platform | `Deploy-Forward/platform` | Skinny Convoy thread/layer inside Composer. Native `turn.send`. | Not this HTTP MCP. Do not land MCP code there. |

Customer 1 talks to Grok Bot. Grok Bot hops through Convoy. The hop lands on a harness the human already signed into. Three products, one thread.

---

## Objects: Thread, Layer, Synapse

| Object | Lives where | Shape | Owns | Does not own |
|---|---|---|---|---|
| **Thread** | The human conversation (this Grok Bot chat, or any customer thread). Front matter is in the chat, never invented. | Message to/From, Thread path, Skill on disk. The conversation is the durable unit. | The human's questions, compact cards coming back, the decision to hop. | Vendor session_ids. Packed stdin. Full transcripts. |
| **Layer** | `.convoy/feed.jsonl` under a checkout root. On Aether customer 1: `C:\Users\marco\ola\da-integration\.convoy\feed.jsonl`. | JSONL of `{ts, kind, instance_id, summary, ...extra}`. Sliding window via `feed_since`. | Event time. Pointers (thread.md, role.md, `.ola/brief.md`, newest handoff, instance_id, worktree, branch, pr). Who hopped, when. | Bytes of a vendor transcript. `hook-context` / `precompact` / `session-end` from ola-brain. Vendor `--resume`. |
| **Synapse** | One hop: Convoy execs one harness CLI, one instance, one meter. Card comes back compact. | `{ok, to, session_id, model, usage_remaining, body, ...}`. Hook row stamped on send/refuse/spawn. | That harness's native session_id. That harness's cwd/worktree. That harness's remaining quota (or JSON `null`). | Another synapse's session. Another synapse's branch. The Grok Bot main context window. |

Rules that follow from the table:

- Two synapses never share a vendor session.
- The layer is pointers and stamps, not packed bytes in stdin.
- Turn 2+ of a hop resumes **that instance's** `session_id` only.
- Unknown fields are JSON `null`. Never invent `main`, never invent a token count, never invent a session id.

---

## How Grok Bot connects (MCP, historical details)

The canonical lock above is authoritative when this section disagrees.

Transport: HTTP MCP at `https://convoy.bot/mcp` (or a user daemon reachable from Grok Bot's computer). **NOT** stdio on the Grok Bot box pointing at Windows `localhost:4717`. That failed.

2026-08-28 wire snapshot (customer 1): Shell on Aether-Deployed `machineId` `64a3fdd5-2c54-4038-8984-019382b68a78` running `C:\.grok\Invoke-AgentChannel.ps1` and `C:\.grok\ConvoyLayer.ps1` wrapping `ola-brain.exe`. MCP catalog had no Convoy plugin at that time. Status then: **RED** for HTTP MCP, **GREEN** for PC CLI hop.

The copy of `ConvoyLayer.ps1` in this tree (`/workspace/convoy/ConvoyLayer.ps1`) is the same contract: `hook`, `feed-since`, `send-dry`. Live hops on Aether still go through ola-brain. Default `python -m convoy send` uses a fake runner. Pass `--live` to exec ola-brain. HTTP MCP server code is in `src/convoy/mcp_http.py` (`python -m convoy mcp --root ROOT --port 8788`). Do not treat this paragraph as current attach status; use the canonical split above.

### Required MCP tools and JSON cards

#### `roster`

Returns live agents. Fields, all present, nulls not guesses:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable agent / harness id (`grok`, `claude`, `codex`, `agy`, `cursor-agent`, …) |
| `name` | string | Display name |
| `present` | bool | Binary is on PATH / machine |
| `wired` | bool | Convoy can actually exec it |
| `auth` | string \| null | Login state if the harness exposes it, else null |
| `models` | list \| null | What the harness reports, else null |
| `availability` | string | Probe result: available / limited / unknown. Availability is **not** DF tracking. |
| `usage_remaining` | number \| object \| null | `null` if unknown. Never a remembered number. |
| `tracking` | `off` \| `on` \| `untracked` | DF tracker flag |
| `board` | `off` \| `on` \| `hidden` | DF board flag. Board requires tracker. |
| `thread` | string \| null | Thread path if known |
| `worktree` | string \| null | Checkout path for the live instance |
| `branch` | string \| null | `git rev-parse --abbrev-ref HEAD` or JSON null |
| `pr` | number \| null | `gh pr view` number or JSON null |

#### `onboard`

First run after MCP attach. The human names which harnesses they already have.

- MCP tool: `onboard`
- CLI: `python -m convoy onboard`
- User-facing chat command mapping: `/onboard` and `/onboard -convoy` are the same flow.

Args:

- `to` (required list): one or more harness ids from `grok`, `claude`, `codex`, `cursor-agent`, `agy`
- optional `thread`
- optional `checkout_root`

Refuse list: `gemini-cli`, community `grok-cli`, `UltraCode-Shim`, `ola-brain`.

JSON card shape (per named harness; unnamed are never silently added):

| Field | Type | Meaning |
|---|---|---|
| `to` | string | Named harness id from the allowed set |
| `present` | bool | `shutil.which` / install `_which` found the binary |
| `wired` | bool | Convoy can exec it from PATH right now |
| `path` | string \| null | Resolved executable path if found |
| `availability` | string | `available`, `limited`, or `missing` |
| `usage_remaining` | number \| object \| string \| null | Probe value if the harness exposes one; `null` when unknown. Never invented `0`. |
| `limited` | bool | True when probe says limited |
| `install` | object \| null | For missing named harnesses only: hint to use MCP/CLI `install` with opt-in |

Pseudo-code:

```python
def onboard(root, named, thread=None, checkout_root=None):
    ids = normalize(named)  # dedupe, lower
    refuse_if_empty_or_wrapped(ids)
    refuse_if_unknown(ids, allowed={"grok","claude","codex","cursor-agent","agy"})
    target_root = resolve_checkout(root, checkout_root)
    path_card = ensure_interactive_path()  # ~/.bashrc block for next shell PATH
    convoy_id, bound_thread = bind_thread_if_requested_without_stomp(target_root, thread)
    rows = []
    for hid in ids:
        path = which(hid)
        row = {"to": hid, "present": bool(path), "wired": bool(path), "path": path}
        row["usage_remaining"] = probe_usage_or_null(hid, present=bool(path))
        if checkout_root:
            row["first_run"] = ensure_first_run({"to": hid, "worktree": str(target_root)})
        if not path:
            row["install"] = {"tool": "install", "opt_in_required": True}
        rows.append(row)
    return card(convoy_id, bound_thread, target_root, path_card, rows)
```

Implementation:

- `src/convoy/onboard.py` implements normalization/refusal, declared-only probing, optional bind, and install hints.
- `src/convoy/mcp_http.py` exposes MCP tool `onboard`.
- `src/convoy/cli.py` exposes CLI `python -m convoy onboard`.

Definition of done (emulator):

1. MCP is connected (or unittest fakes simulate PATH with `test/fakes/`).
2. `onboard` with named harnesses returns cards only for named `to`, each with truthful `present`/`wired` from PATH.
3. `usage_remaining` is real-or-null; never invented `0`.
4. Wrapper names are refused.
5. Flow is dry with respect to UI: no window pop / no `wt` spawn.

#### `terminals`

Live windows + instance records for a thread (`thread=` or `convoy_id=`). Optional grep. **No PTY dump.** Pointers and metadata only (`to`, `session_id`, `resume`, `resume_key`, `worktree`, `rect`). Desktop access is this plus `bring_up`, not a second product. Conductor grok-bot is not a window. Historical 2026-08-28 snapshot marked HTTP MCP RED; use canonical lock for current status.

#### `context`

Packed pointers only:

- `thread.md`
- `role.md`
- `.ola/brief.md`
- newest handoff
- `instance_id`
- `worktree`
- `branch`
- `pr`

Not file contents. Not a vendor transcript. Not stdin bytes.

#### `send`

Args: `to=harness|instance_id`, `body`, optional `model` / `label` / `worktree`. Returns a compact card. Refuses if unavailable (limited quota, missing binary, same-branch pair with no worktree). Does not wait 120s on a known-limited harness. Default hop is headless: `send` never pops a TUI and never calls `live_runner` / `CREATE_NEW_CONSOLE`.

#### `feed`

Events since `ts`. Default last window, not unbounded vendor `--resume`. Maps to `feed_since` in `src/convoy/layer.py`.

#### `bring_up` (alias `open`)

Args: `thread=` or `convoy_id=`. Resumes every hop seat for that thread **visible** (`headless=false`) with that harness's own CLI `--resume` (not ola-brain, not grok `-p`/`-c`). Returns a windows card:

| Field | Type | Meaning |
|---|---|---|
| `ok` | bool | False on mismatch or a refused seat |
| `convoy_id` | string \| null | Durable id |
| `thread` | string \| null | Bound thread key |
| `conductor` | string | Always `grok-bot`. Not a window. No harness chip. |
| `lead` | string \| null | Hop lead harness |
| `windows` | list | One card per hop seat. Not grok-bot. |

Each window: `to`, `session_id`, `resume` (vendor id passed to `--resume`; never null if ok; never invented), `resume_key` (`cvr_` + sha256(convoy_id + "\0" + thread + "\0" + to).hexdigest()[:16]; hash is the map key, resume is the harness argument), `worktree`, `rect` `{x,y,w,h}`, plus CLI extras `argv`, `ok`. Lookup by thread+to returns the same resume. No PTY dump. Historical 2026-08-28 snapshot marked HTTP MCP RED; use canonical lock for current status. CLI: `python -m convoy bring-up` / `open` `[convoy_id] [--thread T] [--dry-run]`.

First-run Claude bypass warning is ungated by `bring_up` / `ensure_first_run`. Anthropic ignores `skipDangerousModePermissionPrompt` in project `{worktree}/.claude/settings.json` — that key only works in the **user** file `~/.claude/settings.json`. Merge `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create `~/.claude/` if missing; merge, do not clobber other keys). Do **not** set `permissions.defaultMode` on the user global file (that would make ALL Claude sessions on the machine bypass). Still write the project copy (`skipDangerousModePermissionPrompt: true`, `permissions.defaultMode: bypassPermissions`) as a record. Never write `~/.claude` if the worktree **is** the home dir. Grok/codex no-op on Claude settings. Not a user paste. Not a step-by-step TUI guide. User once-gates only: attach `https://convoy.bot/mcp`, and vendor CLI login. `roster.present` is `shutil.which` on the MCP process PATH, not an already-open desktop terminal. Interactive bash skips `.profile`, so `~/.local/bin` (claude, codex) can be installed and still `command not found` while grok (`.bashrc`) works. `roster` and `bring_up` / `ensure_first_run` call `ensure_interactive_path`, which writes an idempotent `# >>> convoy harness PATH >>>` block into `~/.bashrc` (`$HOME/.local/bin` and `$HOME/.grok/bin`). No-op on Windows (WT inherits user PATH). Does not source a foreign PID; already-open terminals still need `source ~/.bashrc` or a new shell. Roster JSON includes `path` (`path_ok`, `path_written`, `path_bashrc`, `path_host`). Folder trust, Claude Bypass Permissions, `role.md` persona, isolated WT tiling, and agent-driven verify are Convoy's job. Dry-run still calls `ensure_first_run` (cards show `first_run.prepared`, `home_written`, `settings_home`; `settings` stays the project path) and must not Popen `wt`. Claude live argv keeps `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`. Persona is `role.md` in the worktree, not CLI `--append-system-prompt`.



#### `install`

Opt-in vendor harness download. HTTP `dry_run` defaults true. Live requires `opt_in=true` (and CLI `--live --opt-in`). Does not log the user in. `affiliate` is always JSON null.

Allowed hosts only: `x.ai` (grok), `claude.ai` (claude), `chatgpt.com` (codex), `cursor.com` (cursor-agent), `antigravity.google` (agy). Refuse gemini CLI, community grok CLI, UltraCode-Shim, ola-brain. After a live install, `ensure_interactive_path` runs.

Unit GREEN: `test/customer1/phase_install_test.py`.

#### `hide` (aliases `minimize`, `background`)

Default hop (`send`) is headless: it never pops a TUI and never calls `live_runner` / `CREATE_NEW_CONSOLE`. `bring_up` / `open` is the only show command (HTTP `dry_run` still defaults true so a public URL cannot pop windows; CLI `bring-up` without `--dry-run` uses `live_runner`, which Popen's **one** `wt.exe` whose ArgumentList is `isolated_wt_argv` — FileName is wt, not in the list; `--window new`; first command `nt`; n=2 one `-V`; n=3 `-V` then `-H`; absolute exe positional after `-d DIR`; never `--` before the exe; never `-w 0`; never per-seat `CREATE_NEW_CONSOLE` + `MoveWindow`; never `WM_CLOSE`). Isolated spawn is a new WINDOW not a new PROCESS. Dry-run still calls `ensure_first_run` and must not Popen `wt`. Never ola-brain / side-chat / UltraCode-Shim. `hide` / `minimize` / `background` minimize hop windows (Win32 `SW_MINIMIZE` = 6; optional `mode=hide` is `SW_HIDE` = 0). Sessions keep running. Not `taskkill`. Never kills `grok.exe` / `claude.exe` / `Grok Bot.exe`. Conductor grok-bot is not a window. `restore` is `bring_up`, not this tool. HTTP MCP attach is still RED.

### Front matter in this chat, never invented

```
Message to/From: {Agent} | {model} | {effort}
Thread: {filepath} | usage remaining {n|unknown}
Skill on disk: /home/box/agent-data/workflows/agent-channel/SKILL.md
```

If a field is unknown, write `unknown` or JSON `null`. Do not fill it from memory.

### Definition of done (legacy attach checklist)

Historical attach checklist only. Current canonical DoD is the native-send + structured-talk block above: attach/roster/feed may be PARTIAL GREEN, while native `send` remains RED until live vendor PATH execution replaces `ola_runner`.

---


## Phases (hard gate)

Step N is Phase N. Do not start Phase N+1 until Phase N Definition of done is GREEN, proven on customer 1 (this chat / Aether). Unit tests with a fake runner are not enough to unlock the next phase.

| Phase | Name | Status |
|---|---|---|
| 1 | Threaded context | GREEN 2026-08-28 Aether auto-register grok-session-phase1autoreg |
| 2 | Temporally aware | GREEN 2026-08-28 CLI feed --since (utf-8-sig) |
| 3 | Feature branch | GREEN 2026-08-28 branch integration/convoy-web-poc-20260828 PR 167 |
| 4 | Worktree | GREEN 2026-08-28 |
| 5 | Usage remaining | GREEN 2026-08-28 |
| 6 | Parallel native send | GREEN 2026-08-28 grok-session-phase6bgrok + claude-session-phase6bclaude |
| 7 | Durable convoy_id / attach / bring-up | bind+attach stamps GREEN 2026-08-28 `cvy_KE0tAyDLOnqEuWxYHjpsbQ` thread `customer1`; resume hop RED silent hang; bring-up dry-run unit this fold; live TUI RED. Not Phase 8. |

MCP attach status is split: attach/roster/context/feed can be PARTIAL GREEN while native `send` is still RED. This remains a Phase 7 hole, not a Phase 8 launch.

## Phase 1 Threaded context

### Definition

The human conversation is the thread. The layer is pointers, not pack bytes in stdin. Turn 2+ resumes **this** instance `session_id` only. Two harnesses never share a vendor session. A dry-run that prints an instance id without a registry row is a bug.

### Successful functions

- **GREEN:** ola-brain `side-chat send grok --label synapse-proof` → `grok-session-synapseproof` `SYNAPSE_OK` 34s; turn 2 `SYNAPSE_TURN2` 11s; turn 3 via convoy mention `SYNAPSE_TURN3`; registry `session_id` `01a04890-17df-7af0-b54c-9b69dd81b3b2` (2026-08-28 Aether).
- **GREEN:** `Invoke-AgentChannel.ps1 context` (packed pointers).
- **RED:** CLI side-chat `send` skips the IDE hydration pointer (cold message). Codex JSON has no `session_id` so next turn is `resume --last` (hostile).
- **RED:** dry-run printed instance id without `register_agent`.
- **GREEN (this tree):** `context.py` pack/stdin pointers. `ola_runner` passes `--label` before target. `parse_session_id` reads JSON or ola-brain `instance_id: reply` (must contain `-session-`). No UUID regex. Dry-run session_id is JSON null. Live 2026-08-28: pointers in, PHASE1_T1/T2, vendor `01a048ee-3072-7011-b996-6ae068bbed4d`. CLI auto-register from stdout was the remaining gap.

### Pseudo-code

```python
def context_pack(root, instance_id=None):
    # pointers only — never file contents, never a vendor transcript
    return {
        "thread": pointer(root / "thread.md"),
        "role": pointer(root / "role.md"),
        "brief": pointer(root / ".ola" / "brief.md"),
        "handoff": newest_handoff(root),
        "instance_id": instance_id,
        "worktree": git_worktree(root),   # JSON null if not a checkout
        "branch": git_branch(root),       # JSON null if not a checkout
        "pr": gh_pr_number(root),         # JSON null if none
    }

def send(to, body, label=None, instance_id=None, worktree=None):
    packed = context_pack(worktree or cwd(), instance_id)
    stdin = "read these paths, then do the body:\n" + json.dumps(packed)
    if instance_id:
        # turn 2+ resumes THIS instance only
        return resume(to, instance_id, stdin, body)
    card = spawn(to, stdin, body, label=label, cwd=worktree)
    session_id = parse_session_id_from_json(card)  # not regex guess, not Codex --last
    register_agent(session_id, to, worktree)
    hook(kind="synapse", instance_id=session_id, summary=f"send {to}")
    return card
```

### Implementation

- Add `src/convoy/context.py` with `pack()` returning only paths and ids.
- `synapse.py` `ola_runner` must pass `--label` and parse the real `session_id` from ola-brain JSON, not a regex guess over mixed stdout/stderr.
- Never Codex `--last`. Codex JSON today has no `session_id`; treating `--last` as "the other agent" is hostile and merges sessions.
- MCP `context` tool maps 1:1 onto `context.pack`. MCP `send` first line of hop stdin says "read those paths".
- Registry row is required before any printed instance id. A test that sees a dry-run id without a registry row fails.

Current `ola_runner` (must change):

```python
cmd = ["ola-brain", "side-chat", "send", to, body]
# missing --label
# session_id = first token that looks like a uuid  ← regex guess, forbidden
```

Target `ola_runner`:

```python
cmd = ["ola-brain", "side-chat", "send", to, body, "--label", label]
payload = json.loads(stdout)
session_id = payload["session_id"]   # KeyError if missing; do not guess
```

### Definition of done

- `context` MCP tool returns only paths/ids.
- First hop stdin says read those paths.
- Turn 2 uses the returned `session_id`.
- Two harnesses never share a vendor session.
- Test fails if dry-run prints an id without a registry row.

---

## Phase 2 Temporally aware

### Definition

Event time is the hook stamp on the layer. Sliding window = grep feed by `ts`. Not vendor `--resume`. Not ola-brain `hook-context` / `precompact` / `session-end`. Asking "what happened in the last 10 minutes" reads the layer, not a vendor transcript.

### Successful functions

- **GREEN unit:** `test/customer1/temporal_hooks_test.py` (`hook` + `feed_since`). Asserts `ts`, `kind`, `instance_id`, `summary` and that `feed_since(later["ts"])` returns the new hop.
- **GREEN Aether:** convoy hook stamps `{ts,kind,instance_id,summary}` to `C:\Users\marco\ola\da-integration\.convoy\feed.jsonl` via `C:\.grok\ConvoyLayer.ps1`. `convoy feed --since` returns that window. Example c1-locked ts `2026-08-28T14:42:46.975866Z`.
- **GREEN code:** `src/convoy/layer.py` `hook()`, `feed_since()`. CLI: `python -m convoy hook <kind> <summary> [--instance-id]` and `python -m convoy feed --since <ISO>`.
- **RED:** MCP `feed` tool not attached to this chat. ola-brain feed is a different object and hung when probed.

`hook()` today writes:

```python
event = {"ts": utc_now(), "kind": kind, "instance_id": instance_id, "summary": summary}
# extra fields merged if provided
# appended as one JSONL line under root/.convoy/feed.jsonl
```

`feed_since()` today returns every row whose `ts >= since_iso`. Inclusive lower bound. Empty file → `[]`.

### Pseudo-code

```python
def hook(root, kind, summary, instance_id=None, extra=None):
    event = {
        "ts": utc_now(),            # ISO UTC, microseconds, trailing Z
        "kind": kind,               # synapse | refuse | spawn | note | ping | ...
        "instance_id": instance_id,
        "summary": summary,
    }
    if extra:
        event.update(extra)
    append_jsonl(root / ".convoy" / "feed.jsonl", event)
    return event

def feed(root, since, until=None):
    rows = []
    for row in read_jsonl(root / ".convoy" / "feed.jsonl"):
        if row["ts"] < since:
            continue
        if until is not None and row["ts"] > until:
            continue
        rows.append(row)
    return rows
```

Every `send` / `refuse` / `spawn` calls `hook`. MCP `feed` maps to `feed_since`. CLI `/hook` is `python -m convoy hook`.

### Implementation

- Keep `src/convoy/layer.py` as the single writer. Do not invent a second feed format.
- `synapse.send_many` already calls `hook(..., kind="synapse", ...)` after each card. That must stay, and refuse/spawn paths must call `hook` too (they do not yet — refuse path does not exist in this tree).
- MCP `feed` is a thin wrapper: args `since` (required), `until` (optional). Default last window when `since` omitted at the MCP layer, not unbounded.
- A hop without a stamp fails the test. Do not let `ola_runner` return a card that never hit `hook`.
- Do not call ola-brain `hook-context`, `precompact`, or `session-end` and call that the layer.

### Definition of done

- After two hops, `feed --since T0` returns both synapse rows with `ts`.
- A hop without a stamp fails the test.
- Grok Bot can ask "what happened in the last 10 minutes" and get that window from `feed`, not a vendor transcript.
- HTTP MCP `feed --since` works from this chat without Shell paste (still RED today).

---

## Phase 3 Feature branch understanding

### Definition

Each live instance carries `branch` + `pr` on the layer. The thread can say which hop owns which PR. Probes are `git rev-parse --abbrev-ref HEAD` and `gh pr view`, never guessed. JSON `null` if not a git checkout. Never invent `main`.

### Successful functions

- **GREEN unit:** `test/customer1/phase3_branch_test.py`. Non-git pack is JSON null, never `"main"`. Two send_one roots (`feat-a`, `feat-b`) stamp two different `git_branch` fields.
- **in flight:** live `git rev-parse` / `gh pr view` on Aether da-integration.
- Probes: `git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`, `gh pr view --json number`. Never a remembered branch name.
- Probes, when implemented: `git rev-parse --abbrev-ref HEAD` and `gh pr view`. Never a remembered branch name.

### Pseudo-code

```python
def git_state(cwd):
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    sha = run(["git", "rev-parse", "HEAD"], cwd=cwd)
    pr = run(["gh", "pr", "view", "--json", "number", "-q", ".number"], cwd=cwd)
    return {
        "git_branch": branch if branch else None,   # JSON null, never "main"
        "git_sha": sha if sha else None,
        "pr_number": int(pr) if pr else None,
    }

def send(to, body, worktree=None, pr=None):
    state = git_state(worktree or cwd())
    if pr is not None:
        state["pr_number"] = pr
    # refuse silently using another instance's branch
    other = live_instance_on_branch(state["git_branch"], excluding=None)
    if other and other.worktree == (worktree or cwd()):
        raise OverlapError("same branch, same cwd, two agents")
    card = spawn(to, body, cwd=worktree)
    hook(kind="synapse", instance_id=card["session_id"], extra=state)
    return card
```

### Implementation

- Extra fields on `hook` + instance record: `git_branch`, `git_sha`, `pr_number`.
- MCP `roster` / `context` expose `branch`, `pr`.
- `send --pr` optional (CLI + MCP).
- If the cwd is not a git checkout, store JSON `null`. A test that sees the string `"main"` when `rev-parse` failed fails CI.
- Do not copy a branch name from another instance's card.

### Definition of done

- Two synapses on two branches show two different `branch` fields.
- `null` if not a git checkout (never invent a branch name).
- Test asserts JSON `null` not `"main"`.

---

## Phase 4 Worktree understanding

### Definition

A synapse records its worktree / checkout path. Two agents on one branch without a worktree is a bug. Grok and `cursor-agent` already have `--worktree` flags on their CLIs. Convoy must pass those through. Missing worktree on a same-branch pair is an explicit error, not a silent overlap.

### Successful functions

- **GREEN unit:** `test/customer1/phase4_worktree_test.py`. Non-git worktree is JSON null. Second send on the same branch without `--worktree` returns explicit error. Two `--worktree` paths do not share cwd.
- CLI: `send --worktree <path>`. `ola_runner` passes `--worktree` for grok/cursor-agent. MCP still RED.
- Live dual hop is Phase 6. Not started.

### Pseudo-code

```python
def send(to, body, worktree=None):
    if worktree:
        cwd = worktree
    else:
        cwd = os.getcwd()
    siblings = live_instances(branch=git_branch(cwd))
    if siblings and not worktree:
        raise WorktreeRequired(
            "two agents on one branch without a worktree is a bug"
        )
    card = spawn(to, body, cwd=cwd, worktree_flag=worktree)
    hook(kind="synapse", instance_id=card["session_id"], extra={"worktree": cwd})
    return card

def spawn(to, body, cwd, worktree_flag):
    if to in ("grok", "cursor-agent") and worktree_flag:
        argv = [to, "--worktree", worktree_flag, ...]
    else:
        argv = harness_argv(to, body)
    return run(argv, cwd=cwd)
```

### Implementation

- CLI: `send --worktree <path>`.
- `ola_runner` `cwd=worktree` (already in the signature, not wired from CLI).
- `cursor-agent` / `grok` pass their `--worktree` flag.
- MCP `send.worktree`.
- `roster` shows each instance's `worktree`.
- Same-branch pair with missing worktree → explicit error card, not a silent overlap.

### Definition of done

- Two parallel hops with two worktree paths do not share cwd.
- `roster` shows each instance's worktree.
- Missing worktree on a same-branch pair is an explicit error, not a silent overlap.

---

## Phase 5 Usage remaining per harness (BLOCKED)

### Definition

Probe the way the harness actually exposes limits **before** spawn. Unknown is `null`. Limited ⇒ refuse, do not wait 120s. Availability is not DF tracking. Never copy a number from memory. A test that invents `0` tokens fails CI.

### Successful functions

- **GREEN probe:** `claude -p /usage` JSON. 5-hour session 100% used, reset 11:30 AM America/New_York 2026-08-28, week 69%, Fable week 70%.
- **GREEN probe:** `codex login status` logged in ChatGPT; `codex doctor` silent on quota; `codex exec /status` stdin closed ⇒ `Your workspace is out of credits.` Hop without probe hung.
- **GREEN roster field:** `usageRemaining` JSON `null` (`Invoke-AgentChannel.ps1` never guesses).
- **RED:** grok has no `/usage` subcommand (`models` / `doctor` / `login` only); probe aborted.
- **RED:** `cursor-agent status` logged in `marcoantonioruffinelli@gmail.com`, no remaining quota in `status` / `about`.
- **RED:** `agy.exe` present with `-p`, not on ola-brain agents list. Gemini auth unknown.

Refuse rules:

- Claude session 100% ⇒ refuse.
- Codex `out of credits` ⇒ refuse.
- Missing probe ⇒ `usage_remaining` null, still may hop unless last probe said limited.

### Pseudo-code

```python
def probe(harness):
    match harness:
        case "claude":
            raw = run(["claude", "-p", "/usage"])
            data = parse_usage_json(raw)
            limited = data.get("session_pct") == 100
            return {"usage_remaining": data, "limited": limited, "raw": raw}
        case "codex":
            raw = run(["codex", "exec", "/status"])  # closed stdin; do not hang
            limited = "out of credits" in raw.lower()
            remaining = None if limited or not raw else raw
            return {"usage_remaining": remaining, "limited": limited, "raw": raw}
        case "grok":
            # no /usage subcommand — models/doctor/login only
            return {"usage_remaining": None, "limited": False, "raw": None}
        case "agy":
            return {"usage_remaining": None, "limited": False, "raw": None}
        case "cursor-agent":
            # status/about have login, no remaining quota
            return {"usage_remaining": None, "limited": False, "raw": None}
        case _:
            return {"usage_remaining": None, "limited": False, "raw": None}

def send(to, body, **kw):
    p = probe(to)
    if p["limited"]:
        hook(kind="refuse", summary=f"{to} limited", extra={"raw": p["raw"]})
        return {"ok": False, "to": to, "refused": True,
                "usage_remaining": p["usage_remaining"],
                "body": p["raw"]}          # no 120s hang
    return spawn(to, body, **kw)
```

### Implementation

- New file: `src/convoy/usage.py` with `probe(harness)`.
- `roster` calls `probe` per present harness.
- `send` calls `probe` before spawn.
- Never copy a number from memory. Live Claude at 100% is a probe result from 2026-08-28, not a constant in code.
- Timeout on probe must be short. Codex hop without probe hung; that is the bug this step exists to kill.
- A unit test that stubs `0` tokens and expects a hop to succeed (or invents a remaining count) fails CI.

### Definition of done

- Live Claude at 100% returns a refused card with the `/usage` text, no 120s hang.
- Codex out of credits same.
- Grok hop with `usage_remaining` null is allowed and the card says unknown/`null`.
- A test that invents `0` tokens fails CI.

---

## Phase 6 Parallel native send

### Definition

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Each synapse on its own meter. Fake runner and Aether `send-dry` prove the plumbing. Live dual is the remaining bar.

### Successful functions

- **GREEN** fake runner: `python -m convoy send --to grok --to claude` (`src/convoy/synapse.py` `fake_runner` + `send_many` via `ThreadPoolExecutor`). Unit: `test/customer1/parallel_agents_test.py` (`test_two_synapses_own_session_ids`). Distinct `session_id` values; CLI returns 2 if parallel send merged ids.
- **GREEN** Aether `send-dry`: `dry-grok-51884583` and `dry-claude-5a173460`. Two distinct ids, two hook rows. Implemented in `C:\.grok\ConvoyLayer.ps1` `Send-Dry` (and the copy at `/workspace/convoy/ConvoyLayer.ps1`).
- **GREEN** live dual 2026-08-28 11:59 AM ET: `send --live --to grok --to claude --label phase6b` with two worktrees. session_ids `grok-session-phase6bgrok` (da-integration, PR 167) and `claude-session-phase6bclaude` (ola-brain `feat/side-chat`). Both bodies PHASE6B. First try failed on grok cp1252 decode + ola-brain `--worktree` argv; UTF-8 replace + cwd-only worktree fixed it. Codex not hopped (probe timeout refuse).

### Pseudo-code

```python
def send_many(root, targets, body, runner=None, worktree=None):
    if len(targets) < 1:
        raise ValueError("need at least one --to")
    run = runner or fake_runner
    cards = []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futs = {pool.submit(run, t, body): t for t in targets}
        for fut in as_completed(futs):
            card = fut.result()
            hook(root, kind="synapse",
                 summary=f"send {card.get('to')}",
                 instance_id=card.get("session_id"),
                 extra={"to": card.get("to"), "ok": card.get("ok")})
            cards.append(card)
    cards.sort(key=lambda c: str(c.get("to")))
    ids = [c.get("session_id") for c in cards]
    if len(targets) >= 2 and len(set(ids)) < 2:
        raise MergedSessionError("parallel send merged session ids")
    return cards
```

That shape is already in `src/convoy/synapse.py` / `cli.py`. Live dual needs the runner to be a real harness CLI, `--label` + JSON `session_id` (Step 1), probe-before-spawn (Step 5), and argv that does not split.

### Implementation

- Keep `ThreadPoolExecutor` in `send_many`. Default runner stays fake so unit tests do not exec ola-brain.
- `--live` execs `ola_runner`. Live dual on Aether must pass `--label`, parse JSON `session_id`, stamp two hook rows, return two cards.
- grok argv must not split (the 10:51 ET failure). agy must see the prompt, not print a generic hello.
- Probe first (Step 5): do not start a 120s Claude hop when `/usage` already said 100%.
- MCP `send` with two sequential or parallel calls must produce two cards in this thread, not a Shell paste.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread. Not dry-run. Not fake runner.

---


## Phase 7 Durable convoy_id / attach

### Definition

A durable `convoy_id` keys harness + model + thread (`session_id`) + worktree to one convoy. The hop chip is a live seat. The convoy is the parent. Home layer is `--root` (customer 1: `C:\Users\marco\ola\da-integration`). Seats MAY point at other worktrees (Phase 6 dual hop: grok on da-integration, claude on ola-brain). One convoy, many worktrees.

Knowledge layer = `context.pack` pointers (`thread.md`, `role.md`, brief, handoff, branch, sha, worktree) plus feed. Not packed transcripts. A closed Grok Bot chat can `attach` and resume those seats on the same pointers. Resume uses the registered `session_id`. Do not mint a sibling `grok-session-*` and call it the same seat. Unknown fields are JSON `null`. Model on a seat is stored if provided; do not invent one.

### Successful functions

- **GREEN unit:** `test/customer1/phase7_attach_test.py` (14 tests). Prior 8: `init` writes `.convoy/id` (`cvy_` + url-safe random); second `init` same id. `id` before init is JSON `null` and does not create. Two seats (grok + claude) under one `convoy_id`, different worktrees; `seats` returns both; session_ids unchanged. `attach` unknown id → `ok` False, `convoy_id mismatch`, no seats. `attach` after init+seats → `ok` True, same `convoy_id`, both seats, pointers dict with no file contents. Fake-runner send WITH `instance_id` resumes `sess-grok` (not `spawned-grok`). Fake-runner send WITHOUT `instance_id` when a grok seat exists → refuse, do not spawn. Dry-run `session_id` still JSON `null`. Fold-in 6: `bind` writes `.convoy/thread` + short `thread.md` (convoy_id + thread key); pack/attach `pointers.thread` is the path, not file bytes; bind does not mint a second convoy_id; first attach stamps kind `attach` with `since` JSON null and `feed` `[]`; second attach `since` == first `ts`, feed includes the first attach row (`ts >= since`), second `ts` > first; mismatch attach does not append an attach hook; `send_one` card has `convoy_id` from `read_id` after init (null if none).
- **GREEN live attach (2026-08-28 ~4:26 PM ET):** `init` wrote `cvy_KE0tAyDLOnqEuWxYHjpsbQ` at `C:\\Users\\marco\\ola\\da-integration\\.convoy\\id`. Seated `grok-session-phase6bgrok` (`grok-4.6`, da-integration) and `claude-session-phase6bclaude` (`Fable 5`, ola-brain). `attach` returned both plus pointers (branch `integration/convoy-web-poc-20260828`, PR 167, sha `76874008c529cb908aded8de681af52d372cdd80`). Spawn without `--instance-id` refused `seat exists`. Wrong id refused `convoy_id mismatch`.
- **RED live (parent):** bind this Grok Bot thread, two attach stamps, `feed --since`, resume hop body. Not done on Aether in this fold.
- **RED live resume hop:** `send --live --instance-id grok-session-phase6bgrok PHASE7_ATTACH` kept that session_id (no sibling mint) but `ok` false, TimeoutExpired 120s. ola-brain invoked `grok.EXE -p ... -c` (continue latest in cwd), not a successful turn body. Hostile. Bring-up must not use grok `-p` or `-c`.
- **GREEN unit (this fold, 2026-08-29):** `test/customer1/phase7_bringup_test.py`. `resume_argv` is native `[grok, --resume, session_id]` / `[claude, --resume, session_id]`, cwd=worktree. Not ola-brain, not `side-chat`, not grok `-p`/`-c`/`--output-format`. Dry-run `bring-up` / `open` returns two windows, distinct tile rects on 1920x1080, conductor grok-bot is not a window, `resume` equals registered `session_id` (never minted). `resume_key = "cvr_" + sha256(convoy_id + "\0" + thread + "\0" + to).hexdigest()[:16]`; same convoy_id+thread+to → same key; different thread → different key. Lookup by thread+to returns the same resume. Missing session_id refuses that seat. MCP JSON cards exist in CLI (`bring_up` / `terminals`); attach/read can be partial GREEN, native `send` remains RED.
- **GREEN unit (2026-08-29 first-run ungate):** `test/customer1/phase7_first_run_test.py`. Anthropic ignores project `skipDangerousModePermissionPrompt`; user-level `~/.claude/settings.json` is required for that one key (do not set user-global `defaultMode`). `ensure_first_run` writes thread `{worktree}/.claude/settings.json` (`skipDangerousModePermissionPrompt` + `permissions.defaultMode: bypassPermissions`) and merges `skipDangerousModePermissionPrompt: true` into `~/.claude/settings.json` (create dir if missing; merge existing home keys). Refuses if worktree is home. Grok/codex no-op (no home write). Dry-run `bring_up` still calls it (`first_run.prepared`, `home_written`, `settings_home`) and does not Popen `wt`. Live Claude argv adds `--allow-dangerously-skip-permissions` (no duplicate) plus `--permission-mode bypassPermissions`. `isolated_wt_argv` is a pure argv builder. Live GREEN on WT 1.24.11911.0 (Aether 2026-08-29): `--window new`, first command `nt`, n=3 one `-V` then one `-H`, absolute exe positional after `-d DIR` (never `--` before the exe; that pops GUI Help), never `-w 0`, never `-w <thread-name>` (Help), literal `;`. No live WT spawn in unit tests.
- **GREEN unit (2026-08-29 isolated live_runner wire):** `bring_up` + `live_runner` spawn **one** `wt.exe` per named thread. Argv matches `isolated_wt_argv`. Never per-seat `CREATE_NEW_CONSOLE`, never `MoveWindow`, never `WM_CLOSE` (close-on-fail TDD killed Marco's 7-tab `C:\` session because `--window new` shares one `WindowsTerminal.exe` process). Duplicate-launch guard: do not add the same seat twice (same worktree+to, or same resume_key/session_id). Not one pane per harness name — two grok hops on different worktrees (wt-grok-1 vs wt-grok-2) are two panes (n=3 claude+grok+grok: `--window new`, `nt`, `; split-pane -V`, `; split-pane -H`). Grok Bot conductor is never a window. Titles `{to}-{i}`.
- Unit tests BYO fake abs binaries under `test/fakes/`; never vendor login; live WT is Windows-only.

- **GREEN live isolated n-pane TDD (2026-08-29 ~4:21–4:23 PM ET):** `C:\\Users\\marco\\ola\\evco-test\\.convoy\\tdd-panes.jsonl`. One new CASCADIA per combo, splits inherited: n=2 grok+grok, n=2 claude+grok, n=3 claude+grok+grok, n=2 claude+claude. `C:\\` hwnd 67496 untouched. `--version`, `-w <name>`, and `--` before exe popped WT Help 1.24.11911.0 (RED, dialog closed).
- **RED live bring-up:** parent pops visible TUIs only when Marco says bring up a thread. Do not exec live TUIs from unit tests.

### Pseudo-code

```python
def ensure_id(root):
    path = root / ".convoy" / "id"
    if path.is_file():
        return path.read_text(encoding="utf-8-sig").strip()  # never regenerate
    cid = "cvy_" + urlsafe_random()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cid + "\n", encoding="utf-8")  # one line, no BOM
    return cid

def read_id(root):
    path = root / ".convoy" / "id"
    if not path.is_file():
        return None  # do not create
    return path.read_text(encoding="utf-8-sig").strip() or None

def make_resume_key(convoy_id, thread, to):
    return "cvr_" + sha256(convoy_id + "\0" + thread + "\0" + to).hexdigest()[:16]

def seat(root, to, session_id, worktree=None, model=None, resume=None):
    if not session_id:
        raise ValueError("refuse empty session_id")
    cid = ensure_id(root)
    thread = read_thread(root) or ""
    resume_val = resume or session_id  # never invent; default session_id
    row = {"convoy_id": cid, "to": to, "session_id": session_id,
           "worktree": worktree, "model": model,
           "resume": resume_val, "resume_key": make_resume_key(cid, thread, to)}
    append_jsonl(root / ".convoy" / "seats.jsonl", row)
    register(root, session_id, to, extra={...})
    return row

def list_seats(root, convoy_id=None):
    # utf-8-sig (BOM happened on Aether). latest row per session_id
    ...

def attach(root, convoy_id=None):
    disk = read_id(root)
    if convoy_id is not None and convoy_id != disk:
        return {"ok": False, "error": "convoy_id mismatch", "convoy_id": disk, "seats": []}
    if convoy_id is None and disk is None:
        return {"ok": False, "error": "no convoy_id"}
    cid = convoy_id or disk
    return {"ok": True, "convoy_id": cid, "seats": list_seats(root, cid),
            "pointers": pack(root)}  # home layer pointers; do not merge other worktrees

def send_one(root, to, body, instance_id=None, dry_run=False, **kw):
    if dry_run:
        return {"ok": True, "session_id": None, "dry_run": True, ...}
    if instance_id:
        return resume(to, instance_id, body)  # registered session_id only
    cid = read_id(root)
    if cid and any(s.get("to") == to for s in list_seats(root, cid)):
        return {"ok": False, "session_id": None,
                "error": "seat exists; attach and resume session_id"}  # no sibling spawn
    return spawn(to, body)
```

### Implementation

- `src/convoy/convoy.py`: `ensure_id`, `read_id`, `read_thread`, `bind`, `seat`, `list_seats`, `attach`, `make_resume_key`, `lookup_resume`.
- Persist `.convoy/id` and `.convoy/thread` (one line each, utf-8, no BOM) and `.convoy/seats.jsonl` (utf-8 write, utf-8-sig read). `bind` writes short `thread.md` (convoy_id + thread key only).
- `seat` stamps `convoy_id` from `ensure_id` and calls existing `register()` so `lookup` / `--instance-id` resume still works. Optional `resume=` stored on the row (default `session_id`). Always stores `resume_key`.
- CLI: `init`, `id`, `bind --thread KEY`, `seat --to H --session-id S [--worktree P] [--model M] [--resume R]`, `seats [--convoy-id ID]`, `attach [convoy_id]`, `bring-up`/`open` `[convoy_id] [--thread T] [--dry-run]`, `terminals`.
- `send_one` guard: harness name, seat already exists under this convoy, no `instance_id` → refuse spawn. Dry-run still cannot mint a session_id. Cards include `convoy_id` from `read_id(root)` (JSON null if none).
- Successful `attach` calls Phase 2 `hook(kind="attach")` and returns `thread`, `ts`, `since` (prior attach ts or null), `feed` (`feed_since` when since set, else `[]`). Failed attach does not stamp. Pointers = `pack(root)` only.
- `src/convoy/bringup.py`: `resume_argv(seat)` → `[grok|--resume|<id>]` / `[claude|--resume|<id>]` (cwd=worktree, no spawn in unit tests). `ensure_first_run` writes thread `.claude/settings.json` and merges user-level `skipDangerousModePermissionPrompt` into `~/.claude/settings.json` (not user-global `defaultMode`; refuse if worktree is home). `isolated_wt_argv` builds WT argv (`--window new`, no `--` before exe; Claude live `--permission-mode bypassPermissions` and `--allow-dangerously-skip-permissions`; no spawn). `bring_up` with a runner fires **one** `isolated_wt_argv` via `live_runner` (Popen FileName=wt, ArgumentList=argv[1:]; never per-seat `CREATE_NEW_CONSOLE` / `MoveWindow` / `WM_CLOSE`). Default runner no-op; dry-run still ungates first-run. `tile_rects` still on window cards. `terminals` metadata, no PTY. ola-brain / side-chat / UltraCode-Shim is not in argv and not an MCP tool name.

### Definition of done

- **unit GREEN:** bind + attach stamp + since (14 tests in `test/customer1/phase7_attach_test.py`). Bring-up dry-run unit in `test/customer1/phase7_bringup_test.py`. Live still RED for parent (bind this Grok Bot thread, two attach stamps, feed --since, resume hop body, visible bring-up TUIs).
- **live attach GREEN / live bind+two-attach+feed --since+resume hop RED / live bring-up RED:** see Successful functions. Phase 7 is not fully GREEN. Do not start Phase 8.

## Installer (`npx deploy-forward`)

One package, sibling repo `deploy-forward/deploy-forward`. Flags:

| Flag | Meaning |
|---|---|
| `--convoy` | Install / wire Convoy MCP + hop CLI |
| `--tracker` | Install DF tracker |
| `--board` | Install DF board. **Requires tracker.** |
| y / n / i | Interactive per-component (yes / no / install) |
| `--yes` | Confirm the current prompt. **`--yes` is not all-yes.** |

White-glove path: `npx deploy-forward --convoy`, attach HTTP MCP at `https://convoy.bot/mcp`, `roster` says who will actually hop, then `send` fires grok / claude / codex / agy / cursor-agent as themselves.

Keep this section short. Installer code does not live in this tree.

---

## Customer 1 log (2026-08-28)

Grok Bot is customer 1. Tests live in `test/customer1/`. These tests must fail until native code passes them. No invented usage. No claiming MCP until HTTP works from this chat.

- Temporal hooks: **GREEN** on Aether. `convoy hook` stamps `{ts,kind,instance_id,summary}` to `.convoy/feed.jsonl`. `convoy feed --since` returns that window. This is not ola-brain `hook-context` / `precompact` / `session-end`. Unit GREEN: `test/customer1/temporal_hooks_test.py`. Code GREEN: `src/convoy/layer.py` `hook()`, `feed_since()`. Example c1-locked ts `2026-08-28T14:42:46.975866Z` on `C:\Users\marco\ola\da-integration\.convoy\feed.jsonl` via `C:\.grok\ConvoyLayer.ps1`.
- Parallel native chat: **GREEN** on fake runner (`python -m convoy send --to grok --to claude`). **GREEN** on Aether `send-dry` (two distinct `session_id` values, two hook rows: `dry-grok-51884583` and `dry-claude-5a173460`). **LIVE dual hop not proven:** Claude 5-hour session was 100% until 11:30 AM ET; Codex was out of credits. Sequential live hops were proven earlier the same day (synapse-proof / SYNAPSE_OK / SYNAPSE_TURN2 / SYNAPSE_TURN3, registry `01a04890-17df-7af0-b54c-9b69dd81b3b2`). grok+agy first live attempt 2026-08-28 10:51 ET started together (pids `79160`, `94228`) but grok argv split and agy printed a generic hello (prompt not seen).
- Grok Bot HTTP MCP: still absent from the catalog. This chat is not natively connected yet. Status **RED** for HTTP MCP, **GREEN** for PC CLI hop via Shell on Aether-Deployed `machineId` `64a3fdd5-2c54-4038-8984-019382b68a78` running `C:\.grok\Invoke-AgentChannel.ps1` and `C:\.grok\ConvoyLayer.ps1` wrapping `ola-brain.exe`. Stdio MCP to Windows `localhost:4717` from the Grok Bot box **failed**.
- Threaded context: **GREEN** ola-brain `side-chat send grok --label synapse-proof`. **GREEN** `Invoke-AgentChannel.ps1 context` (packed pointers). **RED** CLI side-chat send skips IDE hydration pointer (cold message). **RED** Codex JSON has no `session_id` so next turn is `resume --last` (hostile). **RED** dry-run printed instance id without `register_agent`. **RED** this tree: `layer.py` is feed only; no `context.py`; `ola_runner` regex-guesses `session_id`.
- Feature branch understanding: **RED**. Not in `layer.py` events today.
- Worktree understanding: **RED** for Convoy. Need to pass through to harness CLI.
- Usage remaining: **GREEN** probes as logged below. **GREEN** roster `usageRemaining` JSON `null` (never guesses). Live Claude 100% and Codex out of credits blocked the dual hop. Grok / cursor-agent / agy / Gemini probes do not expose remaining quota.
- Usage probes (same day): `claude -p /usage` JSON, 5-hour session 100% used, reset 11:30 AM America/New_York, week 69%, Fable week 70%. `codex login status` logged in ChatGPT; `codex doctor` silent on quota; `codex exec /status` stdin closed ⇒ `Your workspace is out of credits.` Hop without probe hung. grok has no `/usage` (models/doctor/login only); probe aborted. `cursor-agent status` logged in `marcoantonioruffinelli@gmail.com`, no remaining quota in status/about. `agy.exe` present with `-p`, not on ola-brain agents list. Gemini auth unknown.

---

## Honesty bar

Claims in this file must be true of **this tree** or of a named customer-1 run with a timestamp. If a function is not in `src/convoy/`, it is not GREEN for this tree.

This tree today (`/workspace/convoy`, not a landed GitHub checkout):

| Path | What it actually does |
|---|---|
| `src/convoy/layer.py` | `hook()`, `feed_since()`, `utc_now()`, `feed_path()`. Feed only. No branch, no worktree, no usage. |
| `src/convoy/synapse.py` | `fake_runner`, `ola_runner`, `send_one/send_many`. `ola_runner` still shells `ola-brain side-chat send` for live mode; fake runner stays default. |
| `src/convoy/cli.py` | CLI includes `onboard`, `context`, `send`, `roster`-adjacent probes, convoy id/attach/seat/bind helpers, and bring-up/hide/install paths. |
| `src/convoy/context.py` | `pack()` pointers only. |
| `src/convoy/onboard.py` | Declared-harness onboarding: refuse wrappers, probe only named harnesses, optional thread bind, install hints, first-run PATH ungate. |
| `src/convoy/usage.py` | `probe()`. Unknown remaining is JSON null. |
| HTTP MCP server | `src/convoy/mcp_http.py` JSON-RPC POST `/mcp`. Attach/read tools may be PARTIAL GREEN when bound; native `send` is RED while `live=true` routes to `ola_runner`. |
| `test/customer1/temporal_hooks_test.py` | GREEN unit for hook + feed window |
| `test/customer1/parallel_agents_test.py` | GREEN unit for two fake synapses, two session ids |
| `ConvoyLayer.ps1` | Aether contract copy: `hook`, `feed-since`, `send-dry` |
| `pyproject.toml` | `convoy` 0.1.0, packages under `src` |

We do not:

- Wrap Grok as `claude-grok-4-6` (or any Anthropic-shaped alias) behind Claude Code / UltraCode-Shim.
- Proxy `cli-chat-proxy.grok.com` / `api.x.ai` / Codex OAuth / cursor-agent HTTP so another product can wear our meter.
- Merge native sessions. A synapse execs the harness CLI the human already signed into. The other CLI keeps its own `session_id` and its own meter.
- Pretend a LAN stdio MCP to Windows `localhost:4717` is a Grok Bot MCP.
- Invent usage numbers, branch names, session ids, or MCP attach.
- Claim full HTTP MCP GREEN while native `send` still routes to `ola_runner`.
- Land this MCP in `Deploy-Forward/platform`.

If a PR starts looking like UltraCode-Shim (OnlyTerp, https://github.com/OnlyTerp/UltraCode-Shim — local proxy, Claude Code stays the shell, `/model` ids must start with `claude` or `anthropic`, Grok becomes a backend, `grok_build` hits `cli-chat-proxy.grok.com`), it does not land in `deploy-forward/convoy`.

Bring your own harness. Do not bring your own API key into someone else's harness.

Unknown is `null`. Limited is refuse. Dry-run is not live. Feed is the layer, not vendor `--resume`. The thread stays skinny.

## Phase 6 Parallel native send

Fire more than one synapse at once. Each keeps its own `session_id`. Sequential `@mention` is not this step.

GREEN: `test/customer1/parallel_agents_test.py` fake runner. Aether `send-dry` wrote `dry-grok-51884583` and `dry-claude-5a173460` plus two hook rows.

RED live: grok+agy 10:51 ET started together (pids 79160, 94228) but grok argv split and agy never saw the ping.

### Definition of done

Two live harnesses, two `session_id`s, two hook rows, two compact cards in this thread.

