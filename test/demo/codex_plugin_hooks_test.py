"""Codex runs Convoy's hooks from the convoy plugin, not from a per-worktree file.

Codex runs a hook only when ~/.codex/config.toml carries `[hooks.state."<key>"] trusted_hash`
for it. A project hook is keyed by its absolute path, so every worktree's `.codex/hooks.json`
is a new key nobody trusted and it never runs. The plugin's hooks are keyed
`convoy@deploy-forward:codex-hooks.json:<event>:<group>:<handler>`, so one review by the person
covers every project. So:

1. A first run writes no `.codex/hooks.json`. One an older Convoy wrote is left alone and the card
   carries a migration note.
2. `codex_hooks_trusted(home)` reads that config ($CODEX_HOME when set), never writes it, and says
   trusted, untrusted, disabled or unknown for each enabled convoy@* plugin's two keys. `add` and
   `crew` cards for a codex chair carry a warning in the state's own words while not trusted.
3. A send to a codex chair says what the wake path did: `wake: "codex-queue-accepted"` when `codex
   queue` exited 0 (accepted is not a turn started), else `wake: "inbox-only"`, each with `why`.
4. The plugin's Stop hook (`convoy end --hook`) records the session id it carries as the chair's
   resume, so the next send native-queues. The id is stamped only by a body of the chair's own
   harness, read from the hook's process ancestry. A different id replaces the recorded one only
   from a top-level codex body (never a nested `codex exec`), in the chair's exact worktree, while
   no pane host owns a live body for the chair, and at most once in ten minutes; a refused flap
   writes one "two codex bodies in one worktree?" row. The incarnation is the pane host's and is
   never touched; a `resume-changed` row carries only hashes of the two ids.

Every home, Convoy home and repository is a temporary folder; no harness is started.
"""
import io
import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_fixture import seated_launcher, widget_lead, with_seated_launcher  # noqa: E402

from convoy.bringup import ensure_first_run
from convoy.cli import main
from convoy.convoy import bind, ensure_id, list_seats, seat
from convoy.crew import add, crew

add = with_seated_launcher(add)
crew = with_seated_launcher(crew)

from convoy.repo import mint_worktrees
from convoy.synapse import fake_runner, send_one

STOP_KEY = "convoy@deploy-forward:codex-hooks.json:stop:0:0"
POST_KEY = "convoy@deploy-forward:codex-hooks.json:post_tool_use:0:0"
WARNING = ("codex hooks not trusted: run /hooks in Codex and trust the two convoy@deploy-forward hooks; "
           "until then this neuron cannot be woken by a send and its identity rests on its folder")
NO_ID_WHY = "no Codex session id recorded (Convoy's Codex hooks not trusted or not yet run)"
ACCEPTED_WHY = ("codex queue accepted the message; that is not proof a turn started, "
                "and only the neuron's own receipt proves delivery")
DISABLED_WARNING = ("codex hooks disabled: run /hooks in Codex and enable the two convoy@deploy-forward hooks; "
                    "until then this neuron cannot be woken by a send and its identity rests on its folder")
UNKNOWN_PREFIX = "codex hook trust unknown: "
PLUGIN_DISABLED_WARNING = ("codex convoy plugin disabled: enable convoy@deploy-forward in Codex "
                           "([plugins.\"convoy@deploy-forward\"] enabled = true); "
                           "until then this neuron cannot be woken by a send and its identity rests on its folder")


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _repo(prefix):
    repo = Path(tempfile.mkdtemp(prefix=prefix))
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=synthetic", "-c", "user.email=synthetic@example.test", "commit", "-qm", "init")
    return repo


HOOK_PID = 900


def _ancestry(body):
    """The Stop hook's process ancestry: python <- shell <- the harness body (or a nested exec)."""
    hook = [{"pid": HOOK_PID, "ppid": 800, "cmdline": "python -m convoy end --hook"},
            {"pid": 800, "ppid": 700, "cmdline": "bash -c \"convoy end --hook\""}]
    if body == "nested":
        return hook[:1] + [{"pid": 800, "ppid": 750, "cmdline": "bash -c \"convoy end --hook\""},
                           {"pid": 750, "ppid": 740, "cmdline": "codex exec \"review this diff\""},
                           {"pid": 740, "ppid": 700, "cmdline": "bash -c \"codex exec review\""},
                           {"pid": 700, "ppid": 1, "cmdline": "codex"}]
    return hook + [{"pid": 700, "ppid": 1, "cmdline": body}]


def as_body(test, body):
    """Run the rest of the test as a hook whose ancestry is that body."""
    from convoy import panes
    for name, value in (("_TEST_PROCS", _ancestry(body)), ("_TEST_PID", HOOK_PID)):
        patch = mock.patch.object(panes, name, value)
        patch.start()
        test.addCleanup(patch.stop)


def _trusted_config(*keys):
    return "".join('[hooks.state."' + k + '"]\ntrusted_hash = "sha256:00ff"\n\n' for k in keys)


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-cxh-home-"))
        convoy_home = Path(tempfile.mkdtemp(prefix="convoy-cxh-chome-"))
        env = mock.patch.dict(os.environ, {"USERPROFILE": str(self.home), "HOME": str(self.home),
                                           "CONVOY_HOME": str(convoy_home)})
        env.start()
        self.addCleanup(env.stop)
        for name in ("CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_HOME"):
            os.environ.pop(name, None)

    def write_config(self, text):
        path = self.home / ".codex" / "config.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


class FirstRunWritesNoCodexHooksFile(Sandbox):
    def setUp(self):
        super().setUp()
        main_repo = _repo("convoy-cxh-main-")
        self.wt = Path(mint_worktrees(main_repo, 1, names=["neuron"])["worktrees"][0]["path"])

    def test_no_harness_gets_a_per_worktree_codex_hooks_file(self):
        for to in ("codex", "claude", "grok"):
            card = ensure_first_run({"to": to, "worktree": str(self.wt)}, root=self.wt)
            self.assertTrue(card["ok"], card)
            self.assertFalse((self.wt / ".codex" / "hooks.json").exists(), to)
            self.assertNotIn(".codex/hooks.json", card.get("would_write") or [], to)
            self.assertNotIn(".codex/hooks.json", card.get("left_visible") or [], to)

    def test_an_old_convoy_written_file_stays_byte_identical_and_the_card_says_so(self):
        hooks = self.wt / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        doc = {"hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "convoy end --hook", "timeout": 5}]}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "persons-own-check"}]}],
        }}
        hooks.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        before = hooks.read_bytes()
        card = ensure_first_run({"to": "codex", "worktree": str(self.wt)}, root=self.wt)
        self.assertEqual(hooks.read_bytes(), before, "a person's file is never rewritten")
        notes = [n for n in card.get("notes") or [] if ".codex/hooks.json" in n]
        self.assertEqual(len(notes), 1, card.get("notes"))
        self.assertIn("convoy plugin", notes[0])

    def write_stale(self):
        hooks = self.wt / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        hooks.write_text('{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "convoy end --hook"}]}]}}\n',
                         encoding="utf-8")

    def skills_notes(self, harness):
        # Each call seats the worktree on a fresh thread. A worktree serves one thread, so the
        # previous thread's root pointer is released first.
        from convoy.inbox import POINTER_RELS
        for rel in POINTER_RELS:
            (self.wt / rel).unlink(missing_ok=True)
        root = Path(tempfile.mkdtemp(prefix="convoy-cxh-sroot-"))
        ensure_id(root)
        bind(root, "s")
        seat(root, harness, harness + "-s", worktree=str(self.wt))
        out = io.StringIO()
        with redirect_stdout(out):
            main(["--root", str(root), "skills", "--worktree", str(self.wt)])
        return [n for n in json.loads(out.getvalue())["notes"] if ".codex/hooks.json" in n]

    def test_the_migration_note_is_for_codex_worktrees_only_on_first_run_and_skills(self):
        self.write_stale()
        claude = ensure_first_run({"to": "claude", "worktree": str(self.wt)}, root=self.wt)
        self.assertFalse([n for n in claude.get("notes") or [] if ".codex/hooks.json" in n])
        self.assertEqual(self.skills_notes("claude"), [])
        self.assertEqual(len(self.skills_notes("codex")), 1)

    def test_a_hooks_file_without_convoy_entries_gets_no_note(self):
        hooks = self.wt / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True, exist_ok=True)
        hooks.write_text('{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "mine"}]}]}}\n',
                         encoding="utf-8")
        card = ensure_first_run({"to": "codex", "worktree": str(self.wt)}, root=self.wt)
        self.assertFalse([n for n in card.get("notes") or [] if ".codex/hooks.json" in n], card.get("notes"))


def codex_hooks_trusted(home):
    from convoy.bringup import codex_hooks_trusted as check
    return check(home)


class TheTrustCheck(Sandbox):
    def test_no_config_is_untrusted_and_nothing_is_created(self):
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "untrusted")
        self.assertEqual(card["keys"], {STOP_KEY: "untrusted", POST_KEY: "untrusted"})
        self.assertFalse((self.home / ".codex").exists(), "a read never creates the store")

    def test_both_keys_with_a_hash_are_trusted_and_the_file_is_unchanged(self):
        path = self.write_config('model = "x"\n\n' + _trusted_config(STOP_KEY, POST_KEY))
        before, mtime = path.read_bytes(), path.stat().st_mtime_ns
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "trusted")
        self.assertEqual(card["keys"], {STOP_KEY: "trusted", POST_KEY: "trusted"})
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), (before, mtime))

    def test_one_key_missing_is_untrusted(self):
        self.write_config(_trusted_config(STOP_KEY))
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "untrusted")
        self.assertEqual(card["keys"][POST_KEY], "untrusted")

    def test_a_project_path_key_does_not_count(self):
        self.write_config("[hooks.state.'C:\\\\w\\\\.codex\\\\hooks.json:stop:0:0']\ntrusted_hash = \"sha256:1\"\n")
        self.assertEqual(codex_hooks_trusted(self.home)["state"], "untrusted")

    def test_an_unparseable_config_is_unknown_with_a_reason(self):
        self.write_config("[hooks.state\nnot toml")
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "unknown")
        self.assertEqual(card["keys"], {STOP_KEY: "unknown", POST_KEY: "unknown"})
        self.assertTrue(card["reason"], card)

    def test_codex_home_is_honoured_when_no_home_is_given(self):
        codex_home = Path(tempfile.mkdtemp(prefix="convoy-cxh-codexhome-"))
        (codex_home / "config.toml").write_text(_trusted_config(STOP_KEY, POST_KEY), encoding="utf-8")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
            card = codex_hooks_trusted(None)
        self.assertEqual(card["state"], "trusted", card)
        self.assertEqual(card["store"], str(codex_home / "config.toml"))

    def test_a_disabled_hook_is_disabled(self):
        self.write_config(_trusted_config(POST_KEY) + '[hooks.state."' + STOP_KEY + '"]\n'
                          'trusted_hash = "sha256:00ff"\nenabled = false\n')
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "disabled")
        self.assertEqual(card["keys"], {STOP_KEY: "disabled", POST_KEY: "trusted"})

    def test_an_enabled_convoy_plugin_from_another_marketplace_is_read(self):
        other = ("convoy@other:codex-hooks.json:stop:0:0", "convoy@other:codex-hooks.json:post_tool_use:0:0")
        self.write_config('[plugins."convoy@other"]\nenabled = true\n\n' + _trusted_config(*other))
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "trusted", card)
        self.assertEqual(sorted(card["keys"]), sorted(other))

    def test_the_repo_marketplace_plugin_convoy_at_convoy_is_read(self):
        """README installs convoy@convoy from this repository's marketplace; its keys clear the warning."""
        from convoy.bringup import codex_hooks_warning
        local = ("convoy@convoy:codex-hooks.json:stop:0:0", "convoy@convoy:codex-hooks.json:post_tool_use:0:0")
        self.write_config('[plugins."convoy@convoy"]\nenabled = true\n\n' + _trusted_config(*local))
        card = codex_hooks_trusted(self.home)
        self.assertEqual((card["state"], card["plugin"]), ("trusted", "convoy@convoy"), card)
        self.assertEqual(sorted(card["keys"]), sorted(local))
        self.assertIsNone(codex_hooks_warning(["codex"], self.home))
        self.write_config('[plugins."convoy@convoy"]\nenabled = true\n')
        self.assertIn("convoy@convoy", codex_hooks_warning(["codex"], self.home))

    def test_a_disabled_plugin_is_not_read_beside_an_enabled_one(self):
        other = ("convoy@other:codex-hooks.json:stop:0:0", "convoy@other:codex-hooks.json:post_tool_use:0:0")
        self.write_config('[plugins."convoy@other"]\nenabled = false\n\n'
                          '[plugins."convoy@deploy-forward"]\nenabled = true\n\n' + _trusted_config(*other))
        card = codex_hooks_trusted(self.home)
        self.assertEqual(card["state"], "untrusted", card)
        self.assertEqual(sorted(card["keys"]), sorted((STOP_KEY, POST_KEY)))

    def test_every_listed_convoy_plugin_disabled_is_disabled(self):
        self.write_config('[plugins."convoy@deploy-forward"]\nenabled = false\n\n' + _trusted_config(STOP_KEY, POST_KEY))
        self.assertEqual(codex_hooks_trusted(self.home)["state"], "disabled")

    def test_a_disabled_plugin_is_told_to_enable_the_plugin(self):
        from convoy.bringup import codex_hooks_warning
        self.write_config('[plugins."convoy@deploy-forward"]\nenabled = false\n\n' + _trusted_config(STOP_KEY, POST_KEY))
        self.assertEqual(codex_hooks_warning(["codex"], self.home), PLUGIN_DISABLED_WARNING)


class AddAndCrewCardsWarn(Sandbox):
    def setUp(self):
        super().setUp()
        self.repo = _repo("convoy-cxh-repo-")
        ensure_id(self.repo)
        bind(self.repo, "demo")

    def add_dry(self, harness):
        return add(self.repo, harness, env={"WT_SESSION": "synthetic"}, which=lambda n: "C:\\Tools\\" + str(n),
                   platform_name="nt")

    def test_add_codex_warns_while_untrusted(self):
        card = self.add_dry("codex")
        self.assertTrue(card["ok"], card)
        self.assertIn(WARNING, card.get("warnings") or [])

    def test_add_codex_says_nothing_once_trusted(self):
        self.write_config(_trusted_config(STOP_KEY, POST_KEY))
        card = self.add_dry("codex")
        self.assertTrue(card["ok"], card)
        self.assertNotIn(WARNING, card.get("warnings") or [])

    def test_add_codex_says_disabled_in_its_own_words(self):
        self.write_config(_trusted_config(STOP_KEY, POST_KEY).replace(
            'trusted_hash = "sha256:00ff"\n', 'trusted_hash = "sha256:00ff"\nenabled = false\n', 1))
        warnings = self.add_dry("codex").get("warnings") or []
        self.assertIn(DISABLED_WARNING, warnings)
        self.assertNotIn(WARNING, warnings)

    def test_add_codex_says_unknown_never_untrusted_when_the_config_does_not_parse(self):
        self.write_config("[hooks.state\nnot toml")
        warnings = self.add_dry("codex").get("warnings") or []
        self.assertNotIn(WARNING, warnings)
        self.assertEqual(len([w for w in warnings if w.startswith(UNKNOWN_PREFIX)]), 1, warnings)

    def test_add_claude_never_carries_the_codex_warning(self):
        card = self.add_dry("claude")
        self.assertNotIn(WARNING, card.get("warnings") or [])

    def test_crew_with_a_codex_seat_warns_while_untrusted(self):
        card = crew(self.repo, [{"harness": "codex", "title": "cx"}, {"harness": "claude", "title": "cl"}])
        self.assertTrue(card["ok"], card)
        self.assertEqual([w for w in card.get("warnings") or [] if w == WARNING], [WARNING])


class TheSendCardIsHonest(Sandbox):
    """`codex queue` exiting 0 is not a turn started: a row was once found in Codex's own store for
    a dead pane. The card says what the wake path did, never that the neuron woke."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="convoy-cxh-root-"))
        ensure_id(self.root)
        bind(self.root, "t1")

    def send(self, **kw):
        return send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                        allow_interactive_resume=False, **kw)

    def test_no_session_id_is_inbox_only_and_says_why(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.root))
        with mock.patch("convoy.synapse.try_codex_queue") as queue:
            card = self.send()
        queue.assert_not_called()
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(card["wake"], "inbox-only")
        self.assertEqual(card["why"], NO_ID_WHY)
        self.assertNotIn("woken", card)

    def test_native_queued_says_the_queue_accepted_and_no_more(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native):
            card = self.send()
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(card["wake"], "codex-queue-accepted")
        self.assertEqual(card["why"], ACCEPTED_WHY)
        self.assertNotIn("woken", card)
        self.assertFalse(card["delivered"], "accepted is not delivered; only the receipt is")

    def test_a_failed_native_queue_is_inbox_only_and_says_so(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")
        with mock.patch("convoy.synapse.try_codex_queue", return_value=None):
            card = self.send()
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(card["wake"], "inbox-only")
        self.assertIn("codex queue", card["why"])

    def test_a_missing_codex_binary_is_inbox_only(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")
        with mock.patch("convoy.synapse.shutil.which", return_value=None):
            card = self.send()
        self.assertEqual(card["delivery"], "queued")
        self.assertEqual(card["wake"], "inbox-only")
        self.assertIn("codex queue", card["why"])

    def test_a_dry_run_send_carries_no_wake_field(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.root), resume="01codex")
        with mock.patch("convoy.synapse.try_codex_queue") as queue:
            card = self.send(dry_run=True)
        queue.assert_not_called()
        self.assertTrue(card["dry_run"])
        self.assertNotIn("wake", card)
        self.assertNotIn("woken", card)


class ThePluginStopHookRecordsTheSessionId(Sandbox):
    """The plugin's Stop hook is `convoy end --hook`; its stdin carries session_id, turn_id, cwd
    and hook_event_name. The chair learns the id once and the next send native-queues."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="convoy-cxh-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-cxh-wt-"))
        ensure_id(self.root)
        bind(self.root, "t1")
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        from convoy.inbox import write_root_pointer
        write_root_pointer(self.wt, self.root)
        spawn = mock.patch("convoy.end._spawn_waiter", return_value={"spawned": True, "pid": 1})
        spawn.start()
        self.addCleanup(spawn.stop)
        as_body(self, "codex")

    def stop(self, session_id, turn):
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(self.wt), "session_id": session_id,
                              "turn_id": turn})
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(out):
            rc = main(["end", "--hook"])
        return rc

    def resume(self):
        return {r["session_id"]: r for r in list_seats(self.root)}["c-t1"].get("resume")

    def feed(self):
        path = self.root / ".convoy" / "feed.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def changed_rows(self):
        return [r for r in self.feed() if r.get("kind") == "resume-changed"]

    def seat_row(self):
        return {r["session_id"]: r for r in list_seats(self.root)}["c-t1"]

    def test_stop_records_the_id_and_the_next_send_native_queues(self):
        self.assertEqual(self.stop("019codex-native", "t-1"), 0)
        self.assertEqual(self.resume(), "019codex-native")
        self.assertEqual(self.stop("019codex-native", "t-2"), 0)
        self.assertEqual(self.changed_rows(), [], "the same id again changes nothing")
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native) as queue:
            card = send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                            allow_interactive_resume=False)
        self.assertEqual(queue.call_args.args[0], "019codex-native")
        self.assertEqual(card["delivery"], "native-queued")
        self.assertEqual(card["wake"], "codex-queue-accepted")

    def test_a_restarted_codex_in_the_same_worktree_replaces_the_id(self):
        from convoy.convoy import update_seat
        update_seat(self.root, "c-t1", incarnation=2)
        self.stop("019codex-old", "t-1")
        self.assertEqual(self.resume(), "019codex-old")
        self.assertEqual(self.seat_row().get("incarnation"), 2, "a first id is a record, not a new life")
        self.stop("019codex-new", "t-2")
        self.assertEqual(self.resume(), "019codex-new", "the live body is the one taking turns")
        self.assertEqual(self.seat_row().get("incarnation"), 2, "the incarnation is the pane host's")
        [row] = self.changed_rows()
        self.assertEqual(row["instance_id"], "c-t1")
        self.assertNotIn("incarnation", row)
        self.assertTrue(row["old_sha256"] and row["new_sha256"] and row["old_sha256"] != row["new_sha256"], row)
        raw = json.dumps(self.feed())
        self.assertNotIn("019codex-old", raw, "the feed never carries a vendor session id")
        self.assertNotIn("019codex-new", raw)
        native = {"ok": True, "runner": "codex-queue", "delivery": "native-queued", "exit_code": 0}
        with mock.patch("convoy.synapse.try_codex_queue", return_value=native) as queue:
            send_one(self.root, "codex", "hello", runner=fake_runner, instance_id="c-t1",
                     allow_interactive_resume=False)
        self.assertEqual(queue.call_args.args[0], "019codex-new")

    def flap_rows(self):
        return [r for r in self.feed() if r.get("kind") == "resume-flap"]

    def test_two_bodies_flapping_flip_the_chair_at_most_once_and_warn_once(self):
        for i, sid in enumerate(("019codex-a", "019codex-b", "019codex-a", "019codex-b", "019codex-a")):
            self.stop(sid, "t-" + str(i))
        self.assertEqual(self.resume(), "019codex-b", "one flip, then the chair holds")
        self.assertEqual(len(self.changed_rows()), 1)
        [warn] = self.flap_rows()
        self.assertIn("two codex bodies in one worktree?", warn["summary"])
        self.assertNotIn("019codex-a", json.dumps(self.feed()))

    def test_a_nested_codex_exec_never_repoints_the_chair(self):
        self.stop("019codex-live", "t-1")
        as_body(self, "nested")
        self.stop("019codex-exec", "t-2")
        self.assertEqual(self.resume(), "019codex-live")
        self.assertEqual(self.changed_rows(), [])

    def test_a_live_pane_host_body_owns_the_chair(self):
        from convoy.convoy import update_seat
        self.stop("019codex-hosted", "t-1")
        update_seat(self.root, "c-t1", process_state="running", harness_pid=4242, incarnation=3)
        with mock.patch("convoy.pane_host.pid_alive", return_value=True):
            self.stop("019codex-other", "t-2")
        self.assertEqual(self.resume(), "019codex-hosted")
        self.assertEqual(self.seat_row().get("incarnation"), 3)
        self.assertEqual(self.changed_rows(), [])
        with mock.patch("convoy.pane_host.pid_alive", return_value=False):
            self.stop("019codex-other", "t-3")
        self.assertEqual(self.resume(), "019codex-other", "a dead hosted body owns nothing")

    def test_a_codex_body_never_stamps_a_claude_chair(self):
        wt = Path(tempfile.mkdtemp(prefix="convoy-cxh-cwt-"))
        seat(self.root, "claude", "cl-t1", worktree=str(wt))
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(wt), "session_id": "019codex-x", "turn_id": "t"})
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(io.StringIO()):
            main(["--root", str(self.root), "end", "--hook"])
        self.assertIsNone({r["session_id"]: r for r in list_seats(self.root)}["cl-t1"].get("resume"))

    def test_a_stop_from_a_subfolder_never_replaces_the_id(self):
        self.stop("019codex-old", "t-1")
        sub = self.wt / "nested"
        sub.mkdir()
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(sub), "session_id": "019codex-inner",
                              "turn_id": "t-2"})
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(io.StringIO()):
            main(["--root", str(self.root), "end", "--hook"])
        self.assertEqual(self.resume(), "019codex-old", "exact worktree only; never a prefix match")
        self.assertEqual(self.changed_rows(), [])

    def test_a_claude_chair_still_keeps_its_first_id(self):
        as_body(self, "claude")
        wt = Path(tempfile.mkdtemp(prefix="convoy-cxh-cwt-"))
        seat(self.root, "claude", "cl-t1", worktree=str(wt))
        for sid, turn in (("claude-1", "t-1"), ("claude-2", "t-2")):
            payload = json.dumps({"hook_event_name": "Stop", "cwd": str(wt), "session_id": sid, "turn_id": turn})
            with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(io.StringIO()):
                main(["--root", str(self.root), "end", "--hook"])
        self.assertEqual({r["session_id"]: r for r in list_seats(self.root)}["cl-t1"]["resume"], "claude-1")
        self.assertEqual(self.changed_rows(), [])


class TheInboxHookStampsTheSameWay(Sandbox):
    """The plugin's PostToolUse hook (`convoy inbox --hook-pretooluse`) stamps the chair's first id
    under the same gate as the Stop hook: the identified body's harness, nothing from a nested
    body, and the process table read only when the payload's id differs from the recorded one."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="convoy-cxh-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-cxh-wt-"))
        ensure_id(self.root)
        bind(self.root, "t1")
        from convoy.inbox import write_root_pointer
        write_root_pointer(self.wt, self.root)

    def hook(self, session_id):
        from convoy.inbox import hook_pretooluse
        payload = {"hook_event_name": "PreToolUse", "cwd": str(self.wt), "session_id": session_id}
        with mock.patch("convoy.inbox._hook_payload_from_stdin", return_value=payload):
            return hook_pretooluse(self.wt)

    def resume(self, chair):
        return {r["session_id"]: r for r in list_seats(self.root)}[chair].get("resume")

    def test_a_top_level_codex_body_stamps_its_codex_chair(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        as_body(self, "codex")
        self.hook("019codex-live")
        self.assertEqual(self.resume("c-t1"), "019codex-live")

    def test_a_nested_codex_exec_stamps_nothing(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        as_body(self, "nested")
        self.hook("019codex-exec")
        self.assertIsNone(self.resume("c-t1"))

    def test_a_codex_body_never_stamps_a_claude_chair(self):
        seat(self.root, "claude", "cl-t1", worktree=str(self.wt))
        as_body(self, "codex")
        self.hook("019codex-x")
        self.assertIsNone(self.resume("cl-t1"))

    def test_the_process_table_is_read_only_for_a_new_id(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-live")
        with mock.patch("convoy.panes.hook_body", return_value={"harness": "codex", "nested": False}) as body:
            self.hook("019codex-live")
            body.assert_not_called()
            self.hook("019codex-other")
            body.assert_called_once()


class HookSandbox(Sandbox):
    """A thread root, a worktree that points at it, a synthetic hook pid, and the hooks to run."""

    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp(prefix="convoy-cxh-root-"))
        self.wt = Path(tempfile.mkdtemp(prefix="convoy-cxh-wt-"))
        ensure_id(self.root)
        bind(self.root, "t1")
        from convoy.inbox import write_root_pointer
        write_root_pointer(self.wt, self.root)
        from convoy import panes
        for name, value in (("_TEST_PROCS", None), ("_TEST_PID", HOOK_PID)):
            patch = mock.patch.object(panes, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        spawn = mock.patch("convoy.end._spawn_waiter", return_value={"spawned": True, "pid": 1})
        spawn.start()
        self.addCleanup(spawn.stop)

    def table(self, body, error=False):
        return mock.patch("convoy.panes.enumerate_processes",
                          side_effect=OSError("synthetic failure") if error else None,
                          return_value=_ancestry(body))

    def pretool(self, session_id, event="PreToolUse"):
        from convoy.inbox import hook_pretooluse
        payload = {"hook_event_name": event, "cwd": str(self.wt), "session_id": session_id}
        with mock.patch("convoy.inbox._hook_payload_from_stdin", return_value=payload):
            return hook_pretooluse(self.wt)

    def stop(self, session_id, turn):
        payload = json.dumps({"hook_event_name": "Stop", "cwd": str(self.wt), "session_id": session_id,
                              "turn_id": turn})
        with mock.patch("sys.stdin", io.StringIO(payload)), redirect_stdout(io.StringIO()):
            return main(["end", "--hook"])

    def resume(self, chair):
        return {r["session_id"]: r for r in list_seats(self.root)}[chair].get("resume")


class HookCost(HookSandbox):
    """A hook reads the process table at most once per (chair, id), with one short attempt; a
    failed read decides "no stamp" for ten minutes only; the Stop heartbeat never waits on it."""

    def test_a_claude_chair_whose_id_moved_on_reads_once(self):
        seat(self.root, "claude", "cl-t1", worktree=str(self.wt), resume="claude-before-clear")
        with self.table("claude") as enumeration:
            for _ in range(5):
                self.pretool("claude-after-clear")
        self.assertLessEqual(enumeration.call_count, 1)
        self.assertEqual(self.resume("cl-t1"), "claude-before-clear")

    def test_a_nested_exec_reads_once_across_its_tool_calls(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        with self.table("nested") as enumeration:
            for _ in range(5):
                self.pretool("019codex-exec")  # PreToolUse: the gate is the same on every event
        self.assertLessEqual(enumeration.call_count, 1)
        self.assertIsNone(self.resume("c-t1"))

    def test_a_second_body_beside_a_hosted_chair_reads_once(self):
        from convoy.convoy import update_seat
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-hosted")
        update_seat(self.root, "c-t1", process_state="running", harness_pid=4242)
        with self.table("codex") as enumeration, mock.patch("convoy.pane_host.pid_alive", return_value=True):
            for i in range(5):
                self.stop("019codex-other", "t-" + str(i))
        self.assertLessEqual(enumeration.call_count, 1)
        self.assertEqual(self.resume("c-t1"), "019codex-hosted")

    def test_one_short_attempt_inside_a_hook(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        with self.table("codex") as enumeration:
            self.pretool("019codex-live")
        self.assertEqual(self.resume("c-t1"), "019codex-live")
        kwargs = enumeration.call_args.kwargs
        self.assertEqual(kwargs.get("attempts"), 1)
        self.assertLessEqual(kwargs.get("timeout"), 2)

    def test_a_failed_read_decides_no_stamp_for_ten_minutes_only(self):
        import time as real_time
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        now = real_time.time()
        with self.table("codex", error=True) as failed, mock.patch("convoy.inbox.time.time", return_value=now):
            self.pretool("019codex-live")
            self.pretool("019codex-live")
        self.assertEqual(failed.call_count, 1)
        self.assertIsNone(self.resume("c-t1"))
        with self.table("codex") as enumeration, mock.patch("convoy.inbox.time.time", return_value=now + 601):
            self.pretool("019codex-live")
        self.assertEqual(enumeration.call_count, 1)
        self.assertEqual(self.resume("c-t1"), "019codex-live")

    def test_the_stop_heartbeat_is_written_before_any_process_read(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        with mock.patch("convoy.panes.hook_body", side_effect=RuntimeError("slow table")):
            self.stop("019codex-live", "t-1")
        rows = [json.loads(l) for l in (self.root / ".convoy" / "feed.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()]
        self.assertEqual(len([r for r in rows if r.get("kind") == "heartbeat"]), 1)

    def test_the_table_proven_session_chair_read_is_reused(self):
        seat(self.root, "claude", "cl-t1", worktree=str(self.wt), resume="claude-recorded")
        with self.table("claude") as enumeration, \
                mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "", "CODEX_THREAD_ID": ""}), \
                mock.patch("convoy.sessions.list_threads", return_value=[{"root": str(self.root), "present": True}]), \
                mock.patch("convoy.sessions.is_temp_root", return_value=False):
            self.pretool("claude-new")
        self.assertEqual(enumeration.call_count, 1, "one table for identity and the stamp gate")


class HookReadBudget(HookSandbox):
    """Inside a hook every process-table read is one attempt: 3 s on the Stop hook (its read is
    shared by identity and the stamp gate, and leaves room for interpreter start and the git
    snapshot under the plugin's 5 s timeout), 2 s on the inbox hook. A hook reads the table at
    most once, even when that read fails. Callers outside a hook keep the long default (3
    attempts, 150 s)."""

    STOP_BUDGET = {"attempts": 1, "timeout": 3.0}
    INBOX_BUDGET = {"attempts": 1, "timeout": 2.0}

    def identity_read(self):
        """No native id in the environment and a seat with a recorded id: identity reads the table."""
        stack = [mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "", "CODEX_THREAD_ID": ""}),
                 mock.patch("convoy.sessions.list_threads", return_value=[{"root": str(self.root), "present": True}]),
                 mock.patch("convoy.sessions.is_temp_root", return_value=False)]
        for p in stack:
            p.start()
            self.addCleanup(p.stop)

    def budgets(self, enumeration):
        return [{"attempts": c.kwargs.get("attempts"), "timeout": c.kwargs.get("timeout")}
                for c in enumeration.call_args_list]

    def heartbeats(self):
        feed = self.root / ".convoy" / "feed.jsonl"
        rows = [json.loads(l) for l in feed.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if r.get("kind") == "heartbeat"]

    def test_the_stop_identity_read_is_one_three_second_attempt_shared_with_the_stamp(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-recorded")
        self.identity_read()
        with self.table("codex") as enumeration:
            self.stop("019codex-new", "t-1")
        self.assertEqual(self.budgets(enumeration), [self.STOP_BUDGET])

    def test_the_stop_stamp_read_alone_is_one_three_second_attempt(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        with self.table("codex") as enumeration:
            self.stop("019codex-first", "t-1")
        self.assertEqual(self.budgets(enumeration), [self.STOP_BUDGET])
        self.assertEqual(self.resume("c-t1"), "019codex-first")

    def test_the_inbox_identity_read_is_one_two_second_attempt_shared_with_the_stamp(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-recorded")
        self.identity_read()
        for event in ("PreToolUse", "PostToolUse"):
            with self.subTest(event=event), self.table("codex") as enumeration, \
                    mock.patch("convoy.inbox.stamp_usage_row"):  # PostToolUse's meter is not under test
                self.pretool("019codex-new-" + event, event=event)
                self.assertEqual(self.budgets(enumeration), [self.INBOX_BUDGET])

    def test_the_stop_heartbeat_is_written_when_the_read_times_out(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-recorded")
        self.identity_read()
        timeout = subprocess.TimeoutExpired(cmd="powershell", timeout=3.0)
        with mock.patch("convoy.panes.enumerate_processes", side_effect=timeout) as enumeration:
            self.stop("019codex-new", "t-1")
        self.assertEqual(self.budgets(enumeration), [self.STOP_BUDGET], "a failed read is not read again")
        beats = self.heartbeats()
        self.assertEqual(len(beats), 1)
        self.assertEqual((beats[0].get("from"), beats[0].get("instance_id")), ("c-t1", "c-t1"))
        self.assertEqual(self.resume("c-t1"), "019codex-recorded")

    def test_the_inbox_hook_does_not_read_again_after_a_failed_identity_read(self):
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-recorded")
        self.identity_read()
        timeout = subprocess.TimeoutExpired(cmd="powershell", timeout=2.0)
        with mock.patch("convoy.panes.enumerate_processes", side_effect=timeout) as enumeration:
            self.pretool("019codex-new")
        self.assertEqual(self.budgets(enumeration), [self.INBOX_BUDGET])

    def test_callers_outside_a_hook_keep_the_long_default(self):
        from convoy.sessions import proven_session_chair
        from convoy.end import end_task
        seat(self.root, "codex", "c-t1", worktree=str(self.wt), resume="019codex-recorded")
        self.identity_read()
        long_default = {"attempts": 3, "timeout": 150}
        with self.table("codex") as enumeration:
            proven_session_chair(self.wt)
        self.assertEqual(self.budgets(enumeration), [long_default])
        with self.table("codex") as enumeration:
            end_task(cwd=self.wt, summary="manual end")
        self.assertEqual(self.budgets(enumeration), [long_default])


class AFailedShortReadNeverStopsALongerOne(HookSandbox):
    """A no-read decision records the budget of the read that failed. It suppresses a later hook
    only when that hook's budget is no larger, so a failed 2 s inbox read never stops the Stop
    hook's 3 s read, and a failed Stop read still holds for STAMP_RETRY_S.

    The case this pins: `convoy add codex` seated a fresh chair whose pane host was
    live; the first PostToolUse read failed and cached no-read; the Stop 25 s later read nothing,
    and the chair had no id for ten minutes, so every send was inbox-only."""

    HOSTED_PID = 40000

    def fresh_hosted_codex(self):
        from convoy.convoy import update_seat
        seat(self.root, "codex", "c-t1", worktree=str(self.wt))
        update_seat(self.root, "c-t1", process_state="running", harness_pid=self.HOSTED_PID)
        alive = mock.patch("convoy.pane_host.pid_alive", return_value=True)
        alive.start()
        self.addCleanup(alive.stop)
        self.assertIsNone(self.resume("c-t1"))

    def failing(self):
        return mock.patch("convoy.panes.enumerate_processes",
                          side_effect=subprocess.TimeoutExpired(cmd="powershell", timeout=2.0))

    def decisions(self):
        path = self.root / ".convoy" / "hook-stamps.json"
        return list(json.loads(path.read_text(encoding="utf-8")).values()) if path.exists() else []

    def post(self, session_id):
        with mock.patch("convoy.inbox.stamp_usage_row"):  # the PostToolUse meter is not under test
            return self.pretool(session_id, event="PostToolUse")

    def test_the_live_sequence_a_failed_inbox_read_then_stop_stamps_the_first_id(self):
        self.fresh_hosted_codex()
        with self.failing() as failed:
            self.post("019codex-first")
        self.assertEqual(failed.call_count, 1)
        self.assertIsNone(self.resume("c-t1"))
        with self.table("codex") as enumeration:
            self.stop("019codex-first", "t-1")
        self.assertEqual([c.kwargs.get("timeout") for c in enumeration.call_args_list], [3.0])
        self.assertEqual(self.resume("c-t1"), "019codex-first")

    def test_a_no_read_decision_records_its_budget(self):
        self.fresh_hosted_codex()
        with self.failing():
            self.post("019codex-first")
        [decision] = self.decisions()
        self.assertEqual((decision["decision"], decision.get("budget")), ("no-read", 2.0))

    def test_a_failed_inbox_read_still_holds_for_the_next_inbox_hook(self):
        self.fresh_hosted_codex()
        with self.failing() as failed:
            self.post("019codex-first")
            self.post("019codex-first")
            self.pretool("019codex-first")
        self.assertEqual(failed.call_count, 1)

    def test_a_failed_stop_read_still_holds_for_stop_and_inbox_hooks(self):
        self.fresh_hosted_codex()
        with self.failing() as failed:
            self.stop("019codex-first", "t-1")
            self.stop("019codex-first", "t-2")
            self.post("019codex-first")
        self.assertEqual(failed.call_count, 1)
        [decision] = self.decisions()
        self.assertEqual((decision["decision"], decision.get("budget")), ("no-read", 3.0))
        self.assertIsNone(self.resume("c-t1"))
        self.assertEqual(len(self.heartbeats()), 2, "the heartbeat never waits on the read")

    def test_a_first_id_is_stamped_under_a_live_pane_host(self):
        self.fresh_hosted_codex()
        with self.table("codex"):
            self.stop("019codex-first", "t-1")
        self.assertEqual(self.resume("c-t1"), "019codex-first", "the live-host refusal is for a replace only")
        self.assertEqual(self.decisions(), [])

    def heartbeats(self):
        feed = self.root / ".convoy" / "feed.jsonl"
        rows = [json.loads(l) for l in feed.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if r.get("kind") == "heartbeat"]


class OptionFirstNestedExec(unittest.TestCase):
    def body(self, exec_cmd):
        from convoy.panes import hook_body
        procs = [{"pid": 900, "ppid": 750, "cmdline": "python -m convoy end --hook"},
                 {"pid": 750, "ppid": 700, "cmdline": exec_cmd},
                 {"pid": 700, "ppid": 1, "cmdline": "codex"}]
        return hook_body(pid=900, procs=procs)

    def test_a_model_option_before_exec_is_still_nested(self):
        self.assertIs(self.body("codex -m o3 exec review")["nested"], True)

    def test_a_config_option_before_exec_is_still_nested(self):
        self.assertIs(self.body("codex -c x=y exec review")["nested"], True)

    def test_a_plain_child_codex_with_a_model_is_one_body(self):
        self.assertIs(self.body("codex -m o3")["nested"], False)


class TheListenGuidance(Sandbox):
    def test_the_agents_block_says_codex_never_waits_in_the_foreground(self):
        from convoy.identity import _AGENTS_BLOCK
        self.assertIn("--wait is for Claude and Grok background tasks", _AGENTS_BLOCK)
        self.assertIn("Codex is woken through its native queue", _AGENTS_BLOCK)
        self.assertIn("never run `inbox --wait` in the foreground", _AGENTS_BLOCK)
        self.assertNotIn(".codex/hooks.json", _AGENTS_BLOCK)

    def test_the_inbox_wait_help_says_the_same(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit):
            main(["inbox", "--help"])
        text = " ".join(out.getvalue().split())
        self.assertIn("for Claude and Grok background tasks", text)
        self.assertIn("Codex is woken through its native queue", text)
        self.assertIn("never run --wait in the foreground", text)



class NoOptInRoute(unittest.TestCase):
    """The opt-in route only chose the words of the retired Codex note; no verb takes it now."""

    def test_no_launch_verb_takes_an_opt_in_route(self):
        import inspect
        from convoy import bringup, crew as crew_module, relaunch, targeted_launch
        for fn in (bringup.ensure_first_run, bringup.bring_up, crew_module.crew, crew_module.add,
                   relaunch.relaunch, targeted_launch.launch_seat):
            self.assertNotIn("opt_in_route", inspect.signature(fn).parameters, fn.__qualname__)

if __name__ == "__main__":
    unittest.main()
