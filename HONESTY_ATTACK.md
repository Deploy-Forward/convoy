# Honesty attack — send / usage / roster

Attacked tree: `origin/main` `5d3a74d` (PR #2 onboard README).  
Live MCP: `https://convoy.bot/mcp` 2026-08-31, still the 7-tool snapshot (`roster`, `terminals`, `context`, `send`, `feed`, `bring_up`, `open`). No `onboard` / `install` / `hide`. No `session_id` arg.

I am not polite to the spec. SPEC's canonical lock already marks native send RED. README after #2 also marks it RED. That does not make the five claims GREEN. Live process ≠ this tree.

PR #4 (`cursor/native-send-f770`) wrote `native_runner` + resume + named refuse + usage clamp. GitHub: `mergeable=CONFLICTING`, `mergeStateStatus=DIRTY` after #2. Not landed. Not proof.

This PR does **not** ship `native_runner`. That is PR #4's job and it is dirty. This PR only closes two live-proven send-contract holes on current main: named refuse before overlap, and MCP `session_id`/`resume`. `live=true` is still `ola_runner`.

---

## Verdict table

| # | Claim | Verdict | Proof |
|---|---|---|---|
| 1 | `live=true` send is native grok/claude/codex argv, not ola-brain side-chat | **RED** | Tree + live + PR #4 dirty |
| 2 | `usage_remaining` is only number\|object\|null. Never invented 0. Grok always null. Claude blobs die at roster | **RED live / GREEN tree** | Live Claude blob `"probe timeout"`. Tree clamp exists. `normalize(0)` still returns `0` |
| 3 | send can resume an existing seat via `session_id` | **RED** on live 7-tool and on `5d3a74d` MCP schema. CLI already could. | Live grok send, no arg |
| 4 | send `to=ola-brain` / `ultracode-shim` refused by name, not worktree overlap | **RED** on `5d3a74d` and live | Live cards are overlap, not name |
| 5 | No leftover `$` fields. No `"unknown"` strings. No Gemini/DeepSeek hops | **RED** for hops. **GREEN** for `$` / `"unknown"` on live roster JSON | Live gemini/deepseek → overlap. Would hop on a clean root |

Ultracode bar: a stranger who reads README "Convoy refuses wrapper names/paths such as `ola-brain`" and then calls MCP `send` is lied to. That is RED even when README is honest about native send.

---

## 1. Native live send — RED

`5d3a74d` `src/convoy/mcp_http.py` send description (pre-this-PR): `live=true execs ola_runner`.  
`call_tool("send")`: `runner = ola_runner if live else fake_runner`.

`src/convoy/synapse.py` `ola_runner`:

```
brain = os.environ.get("OLA_BRAIN") or shutil.which("ola-brain") or r"C:\Users\marco\.local\bin\ola-brain.exe"
cmd = [brain, "side-chat", "send"]
```

`src/convoy/cli.py`: `--live` is the same `ola_runner`.

Live MCP tool descriptor this run: `live=true execs ola_runner`. Schema: `to`, `body`, `model`, `label`, `worktree`, `live`. No native argv. No vendor bin.

SPEC lock (after PR #1) already says this is RED. README "Truth / proof status" after #2 says the same. Claiming GREEN is a lie. PR #4's `native_runner` is not on main and cannot merge.

I did not exec `live=true` against customer-1 seats. File:line + live schema is enough. A live hop would still be `ola-brain side-chat send`.

**This PR:** description now says native send is RED. Runner unchanged.

---

## 2. usage_remaining types — RED live, GREEN tree

### Tree (`5d3a74d`, already on main from #2)

`src/convoy/usage.py` `normalize_usage_remaining`: bool → null; int/float kept; dict kept; else null.  
`probe("grok")` hard-returns `usage_remaining: None`.  
`_parse_claude` non-JSON remaining is `None`, then clamped.  
`probe("codex")` remaining is always `None` (raw stays on `raw`).  
`build_roster` applies `normalize_usage_remaining`.  
`test/customer1/phase5_usage_test.py` `test_claude_blob_not_usage_remaining` kills `Total cost: $0.00`.

Grok remaining always null: holds in tree.

### Live (this chat, 2026-08-31)

`roster` returned:

| id | present | availability | usage_remaining |
|---|---|---|---|
| grok | true | available | `null` |
| claude | true | available | `"probe timeout"` |
| codex | true | limited | `null` |
| agy | true | available | `null` |
| cursor-agent | true | available | `null` |

Claude blob string survived roster. Claim 2 is dead on the process a stranger attaches. The tree clamp is not the live process. 7-tool snapshot predates #2.

### Residual on tree

`normalize_usage_remaining(0)` returns `0`. "Never invent 0" is a sentinel story, not a type ban. Roster still special-cases `0` + `raw is None` only for grok/agy/cursor-agent. A stub that returns `0` for claude would ship.

I did not invent a remaining count. I did not change the clamp.

---

## 3. Resume via session_id — RED on live MCP / main schema

`send_one` (`synapse.py`): no `instance_id` + existing seat → `error: "seat exists; attach and resume session_id"`.  
CLI: `--instance-id` (`cli.py`). Unit: `phase7_attach_test.py` `test_send_with_instance_id_resumes`.

`5d3a74d` MCP send schema: no `session_id`, no `resume`, no `instance_id`. `additionalProperties: false`.  
`call_tool("send")` never passed `instance_id`.

Live this run, `send to=grok body=honesty-attack-resume-probe live=false`:

```
ok: false
session_id: null
error: "seat exists; attach and resume session_id"
convoy_id: cvy_KE0tAyDLOnqEuWxYHjpsbQ
```

The error tells you to pass `session_id`. The tool cannot accept it. That is a broken contract, not a feature.

**This PR:** MCP `session_id` / `resume` → `send_one(instance_id=...)`. Live 7-tool process still cannot until restart.

---

## 4. Wrapper refuse by name — RED on `5d3a74d` + live

`install.py` `_REFUSE` and `onboard.py` `REFUSED_HARNESSES` refuse `ola-brain` / `ultracode-shim` / `gemini` by name.  
`bringup.py` refuses wrapper exe text in argv.  
`send_one` on `5d3a74d` did not. Order was: dry-run → probe → registry → **seat exists** → **same-branch overlap** → runner.

Live this run:

| to | error |
|---|---|
| `ola-brain` | `two agents on one branch without a worktree is a bug` |
| `ultracode-shim` | same overlap |

Not `"refuse unknown or wrapped harness"`. Overlap. README after #2: "Convoy refuses wrapper names/paths such as `ola-brain`, `side-chat`, `UltraCode-Shim`". Stranger lie. Ultracode bar RED.

On a clean root (no seats, no `live_on_branch` siblings) `5d3a74d` `send` to `ola-brain` would have called `fake_runner` and ACKed. I did not need live for that; `send_one` has no name gate.

**This PR:** named refuse first. Overlap cannot mask a wrap.

---

## 5. `$` / unknown / Gemini / DeepSeek

Live roster JSON: no `$` keys, no `"unknown"` string values. Grok remaining null.  
`$HOME` exists only in `bringup.py` bashrc PATH block (shell, not a card field).  
`normalize_usage_remaining("Total cost: $0.00")` → null (tree).  
`phase_mcp_http_test.py` forbids `"unknown"` in roster blob.  
`onboard.py` uses an `unknown` **key** for unnamed harness ids. That is a list name, not a usage sentinel.

No DeepSeek hop implementation in `src/`. Gemini is refused by `install` / `onboard`, not by `send` on `5d3a74d`.

Live this run:

| to | error |
|---|---|
| `gemini` | overlap, not name |
| `deepseek` | overlap, not name |

Same hole as claim 4. Clean root = fake hop. "No Gemini/DeepSeek hops" is false for the send path.

**This PR:** `gemini`, `gemini-cli`, `deepseek`, `deepseek-cli`, `grok-cli` join the send name-refuse set.

SPEC still documents `availability: available / limited / unknown` and front matter `usage remaining {n\|unknown}`. Runtime roster uses `available` / `limited` / JSON null. SPEC leftover. Not a live `"unknown"` string.

---

## What this PR is / is not

Is: named refuse + MCP resume arg + this file. Tests in `phase_mcp_http_test.py` and `phase5_usage_test.py`.

Is not: native PATH runner. Not a live MCP restart. Not a usage invention. Not a harness wrap. Not a rebase of dirty PR #4.

Until convoy.bot is a process built from a tree that is not `ola_runner`, claim 1 stays RED. Anyone who marks it GREEN from unit tests is lying.
