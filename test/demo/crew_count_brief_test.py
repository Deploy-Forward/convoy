"""`crew --count N` and `crew --brief`: N neurons with one task, tiled in 2x2 tabs.

1. --count repeats the one --seat SPEC N times (titles <harness>-<i>, or <title>-<i>),
   refuses beside a second --seat, and refuses above 16 before anything is written.
2. --brief, after --launch, waits for every chair to seat and then sends each neuron
   its copy through send_one (the path `convoy send` takes): one token per neuron,
   recorded as a synapse row, never typed into a pane. Each copy starts with one line
   naming the neuron's number, the thread and the crew. A chair that does not seat in
   time gets no send and a warning, and ok is false. Without --launch the card carries
   the planned briefs and nothing is sent.
3. More than four panes tile in tabs of four, each a 2x2 grid (new-tab, split-pane -V,
   move-focus left ; split-pane -H, move-focus right ; split-pane -H), one -w for the
   whole argv, never `--`, never -w 0 except --here, which takes at most four.
   tmux splits are followed by `select-layout tiled`.

Runners are mocks, which() answers fakes and the await clock is injected: nothing
spawns and nothing sleeps.
"""
import io
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_fixture import seated_launcher, with_seated_launcher, work_seats  # noqa: E402

from convoy import synapse  # noqa: E402
from convoy.bringup import _live_argv, isolated_wt_argv  # noqa: E402
from convoy.cli import main  # noqa: E402
from convoy.convoy import bind, ensure_id, read_id  # noqa: E402
from convoy.crew import CREW_COUNT_CAP, CREW_HERE_CAP, brief_prefix, crew, expand_count  # noqa: E402
from convoy.layer import feed_since  # noqa: E402
from convoy.lifecycle import seated_ack  # noqa: E402
from convoy.targeted_launch import active_pane_argv, terminal_capability  # noqa: E402

crew = with_seated_launcher(crew)

EPOCH = "1970-01-01T00:00:00.000000Z"
WT = r"C:\abs\wt.exe"
FIRST_RUN = {"ok": True, "prepared": False, "wrote": False, "settings": None, "home_written": False,
             "settings_home": None}


def _git(*argv, cwd):
    return subprocess.run(["git", *argv], cwd=str(cwd), check=True, capture_output=True, text=True, timeout=30)


def _git_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    _git("init", "-q", cwd=d)
    (d / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=d)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init", cwd=d)
    return d


def _which(name):
    return "C:\\Tools\\" + str(name).removesuffix(".exe") + ".exe"


def _seats(n):
    return [{"to": "grok", "session_id": "sess-" + str(i), "resume": "sess-" + str(i), "worktree": "wt-" + str(i),
             "exe": r"C:\abs\grok.exe"} for i in range(1, n + 1)]


def _commands(argv):
    """The wt command opening each segment: the subcommand and, for split-pane and
    move-focus, its direction."""
    segs, cur = [], []
    for a in argv[3:]:
        if a == ";":
            segs.append(cur)
            cur = []
        else:
            cur.append(a)
    segs.append(cur)
    return [" ".join(s[:2]) if s[0] in ("split-pane", "move-focus") else s[0] for s in segs]


class Base(unittest.TestCase):
    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "crew-n")
        for target, kw in (("convoy.bringup.ensure_first_run", {"return_value": dict(FIRST_RUN)}),
                           ("convoy.bringup.shutil.which", {"side_effect": _which})):
            p = mock.patch(target, **kw)
            p.start()
            self.addCleanup(p.stop)
        self.runner = mock.Mock(return_value={"ok": True, "pid": 4242})


class CountExpandsOneSpec(Base):
    def test_titles_are_harness_i(self):
        seats = expand_count([{"harness": "codex", "effort": "high"}], 3)
        self.assertEqual([s["title"] for s in seats], ["codex-1", "codex-2", "codex-3"])
        self.assertTrue(all(s["effort"] == "high" and s["harness"] == "codex" for s in seats))

    def test_titles_are_title_i_when_the_spec_names_one(self):
        seats = expand_count([{"harness": "codex", "title": "fixer"}], 2)
        self.assertEqual([s["title"] for s in seats], ["fixer-1", "fixer-2"])

    def test_no_count_leaves_the_seats(self):
        seats = [{"harness": "codex"}, {"harness": "grok"}]
        self.assertIs(expand_count(seats, None), seats)

    def test_crew_count_mints_n_chairs(self):
        card = crew(self.root, [{"harness": "codex"}], count=3)
        self.assertTrue(card["ok"], card)
        self.assertEqual([s["title"] for s in card["seats"]], ["codex-1", "codex-2", "codex-3"])
        self.assertEqual(len({s["worktree"] for s in card["seats"]}), 3)

    def test_count_above_sixteen_refuses_and_writes_nothing(self):
        card = crew(self.root, [{"harness": "codex"}], count=17, runner=self.runner)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], CREW_COUNT_CAP)
        self.assertIn("capped at 16 per call; run crew again on the same thread for more", card["error"])
        self.assertEqual(work_seats(self.root), [])
        self.assertFalse(any(r.get("kind") == "join" for r in feed_since(self.root, EPOCH)))
        self.assertEqual(list(self.root.parent.glob(self.root.name + "-wt-*")), [])
        self.runner.assert_not_called()

    def test_count_zero_and_non_integers_refuse(self):
        for bad in (0, -1, True, "3", 2.0):
            card = crew(self.root, [{"harness": "codex"}], count=bad)
            self.assertFalse(card["ok"], bad)
        self.assertEqual(work_seats(self.root), [])

    def test_count_with_two_seats_refuses(self):
        card = crew(self.root, [{"harness": "codex"}, {"harness": "grok"}], count=2)
        self.assertFalse(card["ok"])
        self.assertIn("exactly one seat", card["error"])
        self.assertEqual(work_seats(self.root), [])

    def test_cli_usage_errors_exit_2_before_any_write(self):
        for argv in (["--seat", "codex", "--seat", "grok", "--count", "2"], ["--seat", "codex", "--count", "17"]):
            out = io.StringIO()
            with mock.patch("convoy.cli.crew") as fn, redirect_stdout(out):
                rc = main(["--root", str(self.root), "crew", *argv])
            self.assertEqual(rc, 2, argv)
            fn.assert_not_called()
            self.assertFalse(json.loads(out.getvalue())["ok"])
        self.assertIn("capped at 16", out.getvalue())

    def test_cli_count_reaches_crew_expanded(self):
        with mock.patch("convoy.cli.crew", return_value={"ok": True}) as fn, \
                mock.patch("convoy.cli.resolve_launcher", return_value=seated_launcher(self.root)), \
                redirect_stdout(io.StringIO()):
            main(["--root", str(self.root), "crew", "--seat", "codex,title=w", "--count", "2"])
        self.assertEqual([s["title"] for s in fn.call_args[0][1]], ["w-1", "w-2"])


class BriefGoesThroughSend(Base):
    def _ack(self, card, skip=()):
        tokens = {s["session_id"]: s["token"] for s in card["seats"]}
        state = {"done": False}

        def sleep(_s):
            if not state["done"]:
                for sid, tok in tokens.items():
                    if sid not in skip:
                        seated_ack(self.root, sid, tok)
                state["done"] = True
        return sleep

    def _crew_live(self, n, skip_last=False):
        """Run crew live; chairs ack on the first await sleep (all, or all but the last)."""
        holder = {}
        real_await = __import__("convoy.crew", fromlist=["await_seated"]).await_seated

        def await_hook(root, sids, **kw):
            if "card" not in holder or not kw.get("timeout"):
                return real_await(root, sids, **kw)   # the launch's own snapshot
            card = holder["card"]
            skip = {sids[-1]} if skip_last else set()
            kw["sleep"] = self._ack(card, skip)
            kw["clock"] = itertools.count(0, 100).__next__
            return real_await(root, sids, **kw)

        import convoy.crew as crew_mod
        orig_brief = crew_mod._brief

        def brief_hook(card, *a, **kw):
            holder["card"] = card
            return orig_brief(card, *a, **kw)

        with mock.patch.object(crew_mod, "_brief", side_effect=brief_hook), \
                mock.patch.object(crew_mod, "await_seated", side_effect=await_hook), \
                mock.patch.object(synapse, "send_one", wraps=synapse.send_one) as send:
            card = crew(self.root, [{"harness": "codex"}], count=n, runner=self.runner, allow_unverified_launch=True,
                        brief="Fix the flaky tests.", brief_timeout=300)
        return card, send

    def test_prefix_line(self):
        self.assertEqual(brief_prefix(2, 5, "t", "codex-1-t"),
                         "You are neuron 2 of 5 on thread t (crew codex-1-t). Coordinate through Convoy notes; "
                         "claim your share before starting.")

    def test_every_seated_neuron_gets_its_prefixed_copy_and_a_token(self):
        card, send = self._crew_live(3)
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["brief_sent"])
        rows = card["briefs"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(send.call_count, 3)
        cid = read_id(self.root)
        synapses = {r["token"]: r for r in feed_since(self.root, EPOCH) if r.get("kind") == "synapse" and r.get("token")}
        for i, (row, call) in enumerate(zip(rows, send.call_args_list), 1):
            self.assertEqual(set(row) - {"delivery"}, {"neuron_id", "session_id", "worktree", "send_token", "seated"})
            self.assertTrue(row["seated"])
            self.assertRegex(row["neuron_id"], r"^n[0-9a-f]{6}$")
            self.assertEqual(row["delivery"], "queued")
            # sent through the send path, to the chair by its id, with the prefix line first
            self.assertEqual(call.args[1], row["session_id"])
            body = call.args[2]
            self.assertTrue(body.startswith("You are neuron " + str(i) + " of 3 on thread crew-n (crew " +
                                            rows[0]["session_id"] + ")."), body)
            self.assertTrue(body.endswith("\nFix the flaky tests."))
            self.assertIs(call.kwargs["runner"], synapse.fake_runner)
            # one token per neuron, recorded exactly as `convoy send` records it
            self.assertIn(row["send_token"], synapses)
            self.assertEqual(synapses[row["send_token"]]["instance_id"], row["session_id"])
        self.assertEqual(len({r["send_token"] for r in rows}), 3)
        self.assertIsNotNone(cid)

    def test_an_unseated_neuron_gets_no_send_and_a_warning(self):
        card, send = self._crew_live(3, skip_last=True)
        self.assertFalse(card["ok"])
        self.assertTrue(card["launched"])
        last = card["briefs"][-1]
        self.assertFalse(last["seated"])
        self.assertIsNone(last["send_token"])
        self.assertEqual(send.call_count, 2)
        self.assertTrue(any(last["session_id"] in w and "brief not sent" in w for w in card["warnings"]))
        self.assertFalse(any(r.get("kind") == "synapse" and r.get("instance_id") == last["session_id"]
                             for r in feed_since(self.root, EPOCH)))

    def test_without_launch_the_briefs_are_planned_not_sent(self):
        with mock.patch.object(synapse, "send_one") as send:
            card = crew(self.root, [{"harness": "codex"}], count=2, brief="Do it.")
        self.assertTrue(card["ok"], card)
        send.assert_not_called()
        self.assertFalse(card["brief_sent"])
        self.assertTrue(card["briefs"][1]["brief"].startswith("You are neuron 2 of 2"))
        self.assertFalse(any(r.get("kind") == "synapse" for r in feed_since(self.root, EPOCH)))

    def test_cli_brief_reads_a_file(self):
        f = Path(tempfile.mkdtemp()) / "brief.md"
        f.write_text("\ufeffFrom a file.", encoding="utf-8")
        with mock.patch("convoy.cli.crew", return_value={"ok": True}) as fn, \
                mock.patch("convoy.cli.resolve_launcher", return_value=seated_launcher(self.root)), \
                redirect_stdout(io.StringIO()):
            main(["--root", str(self.root), "crew", "--seat", "codex", "--count", "2", "--brief", "@" + str(f),
                  "--brief-timeout", "12"])
        self.assertEqual(fn.call_args.kwargs["brief"], "From a file.")
        self.assertEqual(fn.call_args.kwargs["brief_timeout"], 12.0)


class TiledArgv(unittest.TestCase):
    def argv(self, n, **kw):
        return isolated_wt_argv("demo", _seats(n), wt=WT, **kw)

    def assert_common(self, argv):
        self.assertNotIn("--", argv)
        self.assertEqual(argv.count("-w"), 1)
        self.assertRegex(argv[2], r"^convoy-[0-9a-f]{8}$")
        self.assertNotIn("^;", argv)
        _live_argv(argv)   # the live gate accepts the tiled shape

    def test_one_and_two_and_four_keep_the_chain(self):
        self.assertEqual(_commands(self.argv(1)), ["new-tab"])
        self.assertEqual(_commands(self.argv(2)), ["new-tab", "split-pane -V"])
        four = self.argv(4)
        self.assertEqual(_commands(four), ["new-tab", "split-pane -V", "split-pane -H", "split-pane -H"])
        for a in (self.argv(1), self.argv(2), four):
            self.assert_common(a)
            self.assertNotIn("move-focus", a)

    def test_five_opens_a_second_tab(self):
        argv = self.argv(5)
        self.assert_common(argv)
        self.assertEqual(_commands(argv), ["new-tab", "split-pane -V", "move-focus left", "split-pane -H",
                                           "move-focus right", "split-pane -H", "new-tab"])

    def test_ten_is_three_tabs_of_four_four_two(self):
        argv = self.argv(10)
        self.assert_common(argv)
        tab = ["new-tab", "split-pane -V", "move-focus left", "split-pane -H", "move-focus right", "split-pane -H"]
        self.assertEqual(_commands(argv), tab + tab + ["new-tab", "split-pane -V"])
        self.assertEqual(argv.count("--title"), 10)

    def test_first_false_keeps_the_existing_split(self):
        argv = self.argv(5, first=False)
        self.assertEqual(_commands(argv)[:2], ["split-pane -V", "split-pane -V"])
        self.assertEqual(_commands(argv)[-1], "new-tab")

    def test_here_is_window_zero_up_to_four_and_refused_above(self):
        argv = self.argv(4, here=True)
        self.assertEqual(argv[1:5], ["-w", "0", "split-pane", "-V"])
        self.assertNotIn("new-tab", argv)
        with self.assertRaises(ValueError):
            _live_argv(argv)            # -w 0 only through the here gate
        _live_argv(argv, here=True)
        with self.assertRaises(ValueError) as e:
            self.argv(5, here=True)
        self.assertIn("--here takes at most 4", str(e.exception))
        for n in (1, 5, 10):
            self.assertNotEqual(self.argv(n)[2], "0")

    def test_move_focus_direction_is_not_read_as_a_program(self):
        from convoy.bringup import _pane_programs
        programs = _pane_programs(self.argv(5))
        self.assertNotIn("left", programs)
        self.assertNotIn("right", programs)


class CrewLaunchesTiledAndHereRefusesAboveFour(Base):
    def test_crew_of_five_is_one_runner_call_with_two_tabs(self):
        card = crew(self.root, [{"harness": "codex"}], count=5, runner=self.runner, allow_unverified_launch=True)
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.runner.call_count, 1)
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(argv.count("new-tab"), 2)
        self.assertEqual(argv.count("move-focus"), 2)
        self.assertNotIn("--", argv)

    def test_crew_dry_run_shows_the_planned_argv(self):
        card = crew(self.root, [{"harness": "codex"}], count=10)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["planned_argv"].count("new-tab"), 3)
        self.runner.assert_not_called()

    def test_here_with_more_than_four_refuses_before_any_write(self):
        card = crew(self.root, [{"harness": "codex"}], count=5, here=True, runner=self.runner)
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], CREW_HERE_CAP)
        self.assertEqual(work_seats(self.root), [])
        self.runner.assert_not_called()

    def test_here_with_four_splits_window_zero(self):
        card = crew(self.root, [{"harness": "codex"}], count=4, here=True, runner=self.runner,
                    allow_unverified_launch=True)
        self.assertTrue(card["ok"], card)
        argv = [str(a) for a in self.runner.call_args[0][0]]
        self.assertEqual(argv[1:5], ["-w", "0", "split-pane", "-V"])

    def test_cli_here_picks_the_here_runner(self):
        from convoy.bringup import live_here_runner
        with mock.patch("convoy.cli.crew", return_value={"ok": False}) as fn, \
                mock.patch("convoy.cli.resolve_launcher", return_value=seated_launcher(self.root)), \
                redirect_stdout(io.StringIO()):
            main(["--root", str(self.root), "crew", "--seat", "codex", "--count", "2", "--here", "--launch"])
        self.assertIs(fn.call_args.kwargs["runner"], live_here_runner)
        self.assertTrue(fn.call_args.kwargs["here"])


class TmuxTiles(unittest.TestCase):
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp())
        p = mock.patch("convoy.bringup.shutil.which", return_value="/usr/local/bin/codex")
        p.start()
        self.addCleanup(p.stop)
        self.seat = {"to": "codex", "session_id": "c1", "worktree": str(self.wt), "boot_prompt": "hello"}

    def test_a_split_of_the_callers_pane_is_followed_by_select_layout_tiled(self):
        cap = terminal_capability(env={"TMUX": "/tmp/t,1,0", "TMUX_PANE": "%9"}, which=lambda n: "/usr/bin/tmux",
                                  platform_name="posix")
        argv = active_pane_argv(self.seat, cap)
        self.assertEqual(argv[1:4], ["split-window", "-t", "%9"])
        self.assertEqual(argv[-5:], [";", "select-layout", "-t", "%9", "tiled"])

    def test_a_split_of_the_detached_session_tiles_and_a_new_session_does_not(self):
        cap = {"can_detach": True, "adapter": "tmux-detached", "executable": "/usr/bin/tmux", "target": "convoy-0a1b2c3d",
               "first": False}
        argv = active_pane_argv(self.seat, cap)
        self.assertEqual(argv[-5:], [";", "select-layout", "-t", "=convoy-0a1b2c3d:", "tiled"])
        argv = active_pane_argv(self.seat, {**cap, "first": True})
        self.assertEqual(argv[1], "new-session")
        self.assertNotIn("select-layout", argv)


class CanaryFirst(Base):
    """A crew of several launches its first neuron alone, waits for it to seat, then the rest."""

    def _acker(self, only=None):
        done = set()

        def sleep(_s):
            for r in feed_since(self.root, EPOCH):
                sid = r.get("instance_id")
                if r.get("kind") == "join" and str(sid).startswith("codex-") and sid not in done and \
                        (only is None or sid == only):
                    seated_ack(self.root, sid, r["token"])
                    done.add(sid)
        return sleep

    def _crew(self, n, sleep, **kw):
        return crew(self.root, [{"harness": "codex"}], count=n, runner=self.runner, allow_unverified_launch=True,
                    canary=True, clock=itertools.count(0, 50).__next__, sleep=sleep, **kw)

    def argvs(self):
        return [[str(a) for a in c[0][0]] for c in self.runner.call_args_list]

    def test_the_canary_seats_then_the_rest_launch_continuing_its_layout(self):
        card = self._crew(3, self._acker())
        self.assertTrue(card["ok"], card)
        self.assertTrue(card["canary"]["ok"])
        self.assertEqual(card["canary"]["session_id"], card["seats"][0]["session_id"])
        first, rest = self.argvs()
        self.assertEqual(first.count("--title"), 1)
        self.assertEqual(first[3], "new-tab")
        self.assertEqual(rest.count("--title"), 2)
        self.assertEqual(rest[1:5], [first[1], first[2], "split-pane", "-V"])   # same window, pane 2
        self.assertEqual(_commands(rest), ["split-pane -V", "split-pane -H"])
        self.assertEqual([w["session_id"] for w in card["windows"]], [s["session_id"] for s in card["seats"]])
        for a in (first, rest):
            self.assertNotIn("--", a)

    def test_a_tiled_crew_continues_the_2x2_from_the_canary(self):
        card = self._crew(6, self._acker())
        self.assertTrue(card["ok"], card)
        _, rest = self.argvs()
        self.assertEqual(_commands(rest), ["split-pane -V", "move-focus left", "split-pane -H", "move-focus right",
                                           "split-pane -H", "new-tab", "split-pane -V"])
        _live_argv(rest)

    def test_a_canary_that_never_seats_stops_the_rest(self):
        card = self._crew(3, lambda _s: None)
        self.assertFalse(card["ok"])
        self.assertEqual(self.runner.call_count, 1)
        canary, *rest = card["seats"]
        self.assertNotIn("reason", canary)
        for s in rest:
            self.assertEqual((s["launched"], s["reason"]), (False, "canary_failed"))
        self.assertEqual([r["session_id"] for r in card["not_launched"]], [s["session_id"] for s in rest])
        self.assertTrue(any("not seated within 120" in w for w in card["warnings"]), card["warnings"])
        self.assertEqual({r["verb"] for r in card["recovery"]}, {"launch --seat " + s["session_id"] for s in rest})
        self.assertEqual(len(work_seats(self.root)), 3, "the other chairs stay joined")

    def test_a_canary_whose_harness_exits_stops_the_rest_with_its_error(self):
        from convoy.layer import hook

        def sleep(_s):
            sid = [r["instance_id"] for r in feed_since(self.root, EPOCH)
                   if r.get("kind") == "join" and str(r.get("instance_id")).startswith("codex-")][0]
            hook(self.root, "pane", "chair " + sid + " exited 1", instance_id=sid,
                 extra={"chair": sid, "exit": 1, "stderr_tail": "unknown model gpt-9"})
        card = self._crew(3, sleep)
        self.assertFalse(card["ok"])
        self.assertEqual(self.runner.call_count, 1)
        self.assertLess(card["canary"]["waited_s"], 120)
        self.assertTrue(any("harness exited 1: unknown model gpt-9" in w for w in card["warnings"]), card["warnings"])
        self.assertTrue(all(s.get("reason") == "canary_failed" for s in card["seats"][1:]))

    def test_a_failed_canary_sends_no_brief(self):
        with mock.patch.object(synapse, "send_one") as send:
            card = self._crew(2, lambda _s: None, brief="Go.", brief_timeout=300)
        send.assert_not_called()
        self.assertFalse(card["ok"])
        self.assertTrue(any("brief not sent" in w for w in card["warnings"]))

    def test_no_canary_launches_all_at_once(self):
        card = crew(self.root, [{"harness": "codex"}], count=3, runner=self.runner, allow_unverified_launch=True,
                    canary=False)
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.runner.call_count, 1)
        self.assertEqual(self.argvs()[0].count("--title"), 3)
        self.assertNotIn("canary", card)

    def test_one_neuron_has_no_canary_step(self):
        card = self._crew(1, mock.Mock(side_effect=AssertionError("no wait")))
        self.assertTrue(card["ok"], card)
        self.assertEqual(self.runner.call_count, 1)
        self.assertNotIn("canary", card)

    def test_cli_canary_is_on_by_default_and_no_canary_opts_out(self):
        for extra, want in (([], True), (["--no-canary"], False)):
            with mock.patch("convoy.cli.crew", return_value={"ok": False}) as fn, \
                    mock.patch("convoy.cli.resolve_launcher", return_value=seated_launcher(self.root)), \
                    redirect_stdout(io.StringIO()):
                main(["--root", str(self.root), "crew", "--seat", "codex", "--count", "2", "--launch",
                      "--canary-timeout", "30", *extra])
            self.assertIs(fn.call_args.kwargs["canary"], want)
            self.assertEqual(fn.call_args.kwargs["canary_timeout"], 30.0)


class McpCrewTakesCountAndBrief(unittest.TestCase):
    def setUp(self):
        self.root = _git_repo()
        ensure_id(self.root)
        bind(self.root, "crew-mcp")

    def test_schema_and_plumbing(self):
        from convoy import mcp_http
        tool = next(t for t in mcp_http.TOOLS if t["name"] == "crew")
        props = tool["inputSchema"]["properties"]
        self.assertEqual(props["count"]["type"], "integer")
        self.assertEqual(props["count"]["maximum"], 16)
        self.assertEqual(props["brief"]["type"], "string")
        with mock.patch.object(mcp_http, "crew_chairs", return_value={"ok": True}) as fn, \
                mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True), \
                mock.patch.object(mcp_http, "_launch_launcher", return_value=seated_launcher(self.root)):
            mcp_http.call_tool(self.root, "crew", {"seats": [{"harness": "codex"}], "count": 3, "brief": "Go."})
        self.assertEqual(fn.call_args.kwargs["count"], 3)
        self.assertEqual(fn.call_args.kwargs["brief"], "Go.")
        self.assertFalse(fn.call_args.kwargs["brief_local_writer"])
        self.assertIs(fn.call_args.kwargs["canary"], True)
        self.assertEqual(props["canary"]["type"], "boolean")
        with mock.patch.object(mcp_http, "crew_chairs", return_value={"ok": True}) as fn, \
                mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True), \
                mock.patch.object(mcp_http, "_launch_launcher", return_value=seated_launcher(self.root)):
            mcp_http.call_tool(self.root, "crew", {"seats": [{"harness": "codex"}], "count": 2, "canary": False})
            self.assertIs(fn.call_args.kwargs["canary"], False)
            card = mcp_http.call_tool(self.root, "crew", {"seats": [{"harness": "codex"}], "canary": "yes"})
            self.assertFalse(card["ok"])

    def test_the_cap_is_the_same_code(self):
        from convoy import mcp_http
        with mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True), \
                mock.patch.object(mcp_http, "_launch_launcher", return_value=seated_launcher(self.root)):
            card = mcp_http.call_tool(self.root, "crew", {"seats": [{"harness": "codex"}], "count": 17})
        self.assertFalse(card["ok"])
        self.assertEqual(card["error"], CREW_COUNT_CAP)
        self.assertEqual(work_seats(self.root), [])


if __name__ == "__main__":
    unittest.main()
