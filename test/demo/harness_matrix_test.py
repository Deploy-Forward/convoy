"""Independent launch-eligibility and limit contracts. All identities and stores here are synthetic."""
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import harness_contract
from convoy.bringup import bring_up
from convoy.convoy import bind, ensure_id
from convoy.crew import crew
from convoy.lifecycle import join
from convoy.graph_html import resume_neuron
from convoy.relaunch import relaunch
from convoy.targeted_launch import launch_seat


class HarnessMatrix(unittest.TestCase):
    def eligible_fixture(self, harness):
        root = Path(self.tmp.name) / (self._testMethodName + harness)
        root.mkdir()
        ensure_id(root)
        bind(root, "synthetic-eligible")
        sid = "synthetic-" + harness
        join(root, harness, session_id=sid, worktree=str(self.worktree))
        return root, sid

    def fake_panes(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("convoy.bringup.ensure_first_run", return_value={"ok": True}))
        stack.enter_context(mock.patch("convoy.bringup._window_for", return_value={"ok": True}))
        stack.enter_context(mock.patch("convoy.bringup._prepare_wt_seat", side_effect=lambda s: s))
        stack.enter_context(mock.patch("convoy.bringup._resolve_wt_bin", return_value="synthetic-wt"))
        stack.enter_context(mock.patch("convoy.bringup.isolated_wt_argv", return_value=["synthetic-host"]))

    def test_default_bring_up_for_claude_and_codex(self):
        self.fake_panes()
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                root, _ = self.eligible_fixture(harness)
                runner = mock.Mock(return_value={"ok": True})
                self.assertTrue(bring_up(root, runner=runner)["ok"])
                runner.assert_called_once()

    def test_default_crew_for_claude_and_codex(self):
        self.fake_panes()
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                root, _ = self.eligible_fixture(harness)
                runner = mock.Mock(return_value={"ok": True})
                new_worktree = root / "synthetic-new-worktree"
                new_worktree.mkdir()
                minted = {"ok": True, "worktrees": [{"name": "synthetic-new", "path": str(new_worktree)}]}
                with mock.patch("convoy.crew.mint_worktrees", return_value=minted):
                    card = crew(root, [{"harness": harness, "title": "synthetic-new"}], runner=runner)
                self.assertTrue(card["ok"], card)
                runner.assert_called_once()

    def test_default_relaunch_for_claude_and_codex(self):
        self.fake_panes()
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                root, _ = self.eligible_fixture(harness)
                runner = mock.Mock(return_value={"ok": True})
                card = relaunch(root, runner=runner, alive=lambda *_: False, timeout=0)
                self.assertTrue(card["launched"], card)
                runner.assert_called_once()

    def test_default_resume_go_for_claude_and_codex(self):
        from convoy.convoy import update_seat
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                root, sid = self.eligible_fixture(harness)
                update_seat(root, sid, resume="synthetic-native-id", resume_for=harness)
                spawn = mock.Mock(return_value=12345)
                with mock.patch("convoy.graph_html.resume_argv", return_value=["synthetic-harness"]):
                    card = resume_neuron(root, sid, go=True, spawn=spawn, liveness=lambda *_: False)
                self.assertTrue(card["spawned"], card)
                spawn.assert_called_once()

    def test_default_widget_relaunch_for_claude_and_codex(self):
        from convoy.widget_web import WidgetApi
        self.fake_panes()
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                root, sid = self.eligible_fixture(harness)
                api = WidgetApi([root], probe_fn=lambda _: {})
                api.archive(str(root), sid, archived=True)
                with mock.patch("convoy.bringup.live_runner", return_value={"ok": True}) as runner:
                    card = api.relaunch_seat(str(root), sid)
                self.assertTrue(card["launched"], card)
                runner.assert_called_once()

    def test_headless_live_send_refuses_ineligible_before_native_runner(self):
        from convoy import synapse
        with mock.patch.object(synapse, "native_runner", return_value={"ok": True}) as runner:
            card = synapse.send_one(self.root, "pi", "synthetic body", runner=runner,
                                    worktree=str(self.worktree), probe_fn=lambda _: {})
        self.assertFalse(card["ok"], card)
        self.assertIn("pi", card["error"])
        self.assertIn("unverified launch eligibility", card["error"])
        runner.assert_not_called()

    def test_headless_live_send_override_and_eligible_default(self):
        from convoy import synapse
        for harness, extra in (("pi", {"allow_unverified_launch": True}), ("codex", {})):
            with self.subTest(harness=harness), mock.patch.object(synapse, "native_runner", return_value={"ok": True}) as runner:
                card = synapse.send_one(self.root, harness, "synthetic body", runner=runner,
                                        worktree=str(self.worktree), probe_fn=lambda _: {}, **extra)
                self.assertTrue(card["ok"], card)
                runner.assert_called_once()

    def test_existing_ineligible_chair_live_send_is_queue_not_launch(self):
        from convoy import synapse
        with mock.patch.object(synapse, "native_runner") as runner:
            card = synapse.send_one(self.root, self.sid, "synthetic body", runner=runner,
                                    probe_fn=lambda _: {}, allow_interactive_resume=False)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "queued")
        runner.assert_not_called()

    def test_live_send_cli_forwards_default_and_explicit_override(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        for extra, expected in (([], False), (["--allow-unverified-launch"], True)):
            with mock.patch("convoy.cli.send_one", return_value={"ok": True}) as send, redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(self.root), "send", "--to", "pi", "--live", "synthetic body", *extra]), 0)
            self.assertIs(send.call_args.kwargs["allow_unverified_launch"], expected)

    def test_live_send_mcp_forwards_and_rejects_non_boolean_overrides(self):
        from convoy import mcp_http, synapse
        with mock.patch("convoy.mcp_http._write_tools_enabled", return_value=True), \
             mock.patch.object(synapse, "native_runner", return_value={"ok": True}) as runner, \
             mock.patch.object(mcp_http, "native_runner", runner), \
             mock.patch.object(synapse, "probe", return_value={}):
            # Both modules share the same injected native-runner seam.
            for override in (False, "true", 1, None):
                card = mcp_http.call_tool(self.root, "send", {"to": "pi", "body": "synthetic body", "live": True,
                                                           "worktree": str(self.worktree), "allow_unverified_launch": override})
                self.assertFalse(card["ok"], card)
                self.assertIn("unverified" if override is False else "boolean", card["error"])
            runner.assert_not_called()
            card = mcp_http.call_tool(self.root, "send", {"to": "pi", "body": "synthetic body", "live": True,
                                                        "worktree": str(self.worktree), "allow_unverified_launch": True})
            self.assertTrue(card["ok"], card)
            runner.assert_called_once()

    def test_default_cli_launch_overrides_are_false(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        cases = (
            ("bring-up", [], "bring_up"),
            ("open", [], "bring_up"),
            ("crew", ["--seat", "codex", "--launch", "--no-widget"], "crew"),
            ("relaunch", [], "relaunch"),
            ("resume", ["--neuron", "synthetic-codex", "--go"], "resume_neuron"),
        )
        for verb, args, target in cases:
            with self.subTest(verb=verb), mock.patch("convoy.cli." + target, return_value={"ok": True}) as call, redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(self.root), verb, *args]), 0)
                self.assertIs(call.call_args.kwargs["allow_unverified_launch"], False)

    def test_default_mcp_launch_overrides_are_false(self):
        from convoy import mcp_http
        cases = (
            ("bring_up", {"dry_run": False}, "bring_up"),
            ("open", {"dry_run": False}, "bring_up"),
            ("crew", {"seats": [{"harness": "codex"}], "launch": True}, "crew_chairs"),
            ("resume", {"neuron": "synthetic-codex", "go": True}, "resume_neuron"),
        )
        # There is no MCP relaunch verb; open uses the existing bring_up rail.
        self.assertNotIn("relaunch", {t["name"] for t in mcp_http.TOOLS})
        with mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True):
            for verb, args, target in cases:
                with self.subTest(verb=verb), mock.patch.object(mcp_http, target, return_value={"ok": True}) as call:
                    self.assertTrue(mcp_http.call_tool(self.root, verb, args)["ok"])
                    self.assertIs(call.call_args.kwargs["allow_unverified_launch"], False)

    def test_mcp_queued_send_rejects_non_boolean_override_before_queue(self):
        from convoy import mcp_http, synapse
        with mock.patch.object(mcp_http, "_write_tools_enabled", return_value=True), \
             mock.patch.object(synapse, "probe", return_value={}), \
             mock.patch.object(synapse, "deliver_to_live_seat", return_value={"ok": True, "delivery": "queued"}) as deliver:
            for live in (False, True):
                for override in ("yes", 1, None):
                    with self.subTest(live=live, override=override):
                        card = mcp_http.call_tool(self.root, "send", {"to": self.sid, "body": "synthetic body",
                                                                  "live": live, "allow_unverified_launch": override})
                        self.assertFalse(card["ok"], card)
                        self.assertIn("boolean", card["error"])
            deliver.assert_not_called()

    def test_new_headless_eligibility_precedes_limited_usage_probe(self):
        from convoy import synapse
        root, _ = self.eligible_fixture("codex")
        probe = mock.Mock(return_value={"limited": True, "usage_remaining": 0})
        with mock.patch.object(synapse, "native_runner") as runner, mock.patch.object(synapse, "hook") as hook:
            card = synapse.send_one(root, "grok", "synthetic body", runner=runner,
                                    worktree=str(self.worktree), probe_fn=probe, allow_interactive_resume=False)
        self.assertFalse(card["ok"], card)
        self.assertIn("unverified launch eligibility", card["error"])
        self.assertNotIn("ask", card)
        probe.assert_not_called()
        runner.assert_not_called()
        hook.assert_not_called()

    def test_new_unverified_send_checks_eligibility_before_branch_sibling(self):
        from convoy import synapse
        probe = mock.Mock(return_value={})
        with mock.patch.object(synapse, "native_runner") as runner, \
             mock.patch.object(synapse, "pack", return_value={"branch": "synthetic-branch"}), \
             mock.patch.object(synapse, "live_on_branch", return_value=[{"session_id": "synthetic-sibling"}]) as siblings:
            card = synapse.send_one(self.root, "pi", "synthetic body", runner=runner, probe_fn=probe)
            self.assertIn("unverified launch eligibility", card["error"])
            probe.assert_not_called()
            siblings.assert_not_called()
            card = synapse.send_one(self.root, "pi", "synthetic body", runner=runner, probe_fn=probe,
                                    allow_unverified_launch=True)
            self.assertIn("two agents on one branch", card["error"])
            siblings.assert_called_once_with(self.root, "synthetic-branch")
            runner.assert_not_called()

    def test_unregistered_resume_checks_eligibility_before_limited_usage(self):
        from convoy import synapse
        for interactive in (False, True):
            with self.subTest(interactive=interactive), mock.patch.object(synapse, "native_runner") as runner, \
                 mock.patch.object(synapse, "hook") as hook:
                probe = mock.Mock(return_value={"limited": True, "usage_remaining": 0})
                card = synapse.send_one(self.root, "pi", "synthetic body", runner=runner, probe_fn=probe,
                                        resume="synthetic-unregistered", allow_interactive_resume=interactive)
                self.assertIn("unverified launch eligibility", card["error"])
                self.assertNotIn("ask", card)
                probe.assert_not_called()
                runner.assert_not_called()
                hook.assert_not_called()

    def test_registered_resume_keeps_existing_unverified_chair_queue(self):
        from convoy import synapse
        from convoy.registry import register
        register(self.root, self.sid, "grok", extra={"resume": "synthetic-linked", "worktree": str(self.worktree)})
        with mock.patch.object(synapse, "native_runner") as runner:
            card = synapse.send_one(self.root, "grok", "synthetic body", runner=runner, probe_fn=lambda _: {},
                                    resume="synthetic-linked", allow_interactive_resume=False)
        self.assertTrue(card["ok"], card)
        self.assertEqual(card["delivery"], "queued")
        runner.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "thread"
        self.root.mkdir()
        self.worktree = Path(self.tmp.name) / "worktree"
        self.worktree.mkdir()
        ensure_id(self.root)
        bind(self.root, "synthetic-matrix")
        self.sid = "synthetic-neuron"
        join(self.root, "grok", session_id=self.sid, worktree=str(self.worktree))

    def test_every_harness_has_explicit_limit_coverage_and_evidence(self):
        for row in harness_contract.harness_entries():
            with self.subTest(harness=row["id"]):
                for field in ("limit", "launch_eligibility"):
                    cell = row.get(field)
                    self.assertIsInstance(cell, dict)
                    self.assertIn(cell["state"], ("verified", "unverified"))
                    self.assertTrue(cell["evidence"])

    def test_targeted_launch_refuses_by_name_before_preparation_or_spawn(self):
        runner = mock.Mock()
        with mock.patch("convoy.targeted_launch.ensure_first_run") as prepare:
            card = launch_seat(self.root, self.sid, runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("grok", card["error"])
        self.assertIn("unverified launch eligibility", card["error"])
        self.assertIn("--allow-unverified-launch", card["error"])
        runner.assert_not_called()
        prepare.assert_not_called()

    def test_bulk_launch_refuses_before_first_run_or_spawn(self):
        runner = mock.Mock()
        with mock.patch("convoy.bringup.ensure_first_run") as prepare:
            card = bring_up(self.root, runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("grok", card["error"])
        runner.assert_not_called()
        prepare.assert_not_called()

    def test_crew_refuses_before_minting_or_joining(self):
        runner = mock.Mock()
        with mock.patch("convoy.crew.mint_worktrees") as mint:
            card = crew(self.root, [{"harness": "grok", "title": "synthetic-new"}], runner=runner)
        self.assertFalse(card["ok"])
        self.assertIn("grok", card["error"])
        self.assertIn("unverified launch eligibility", card["error"])
        mint.assert_not_called()
        runner.assert_not_called()

    def test_takeover_refuses_before_eviction_or_rearming(self):
        with mock.patch("convoy.relaunch._evict") as evict, mock.patch("convoy.relaunch.update_seat") as update:
            card = relaunch(self.root, runner=mock.Mock(), take_over=True)
        self.assertFalse(card["ok"])
        self.assertIn("unverified launch eligibility", card["error"])
        evict.assert_not_called()
        update.assert_not_called()

    def test_gate_fails_closed_and_requires_a_boolean_override(self):
        gate = getattr(harness_contract, "validate_launch_eligibility", None)
        self.assertTrue(callable(gate), "missing canonical launch-eligibility gate")
        for harness in ("grok.exe", "unknown-synthetic-harness"):
            with self.assertRaisesRegex(ValueError, "unverified launch eligibility"):
                gate(harness)
            with self.assertRaises(ValueError):
                gate(harness, allow_unverified_launch="false")
        gate("grok", allow_unverified_launch=True)

    def test_verified_requires_evidence_and_date(self):
        gate = getattr(harness_contract, "validate_launch_eligibility", None)
        self.assertTrue(callable(gate), "missing canonical launch-eligibility gate")
        for cell in ({"state": "verified"}, {"state": "verified", "evidence": "synthetic proof"},
                     {"state": "verified", "evidence": "synthetic proof", "verified_at": "not-a-date"}):
            with mock.patch.object(harness_contract, "harness_entries", return_value=[{"id": "codex", "launch_eligibility": cell}]):
                with self.assertRaisesRegex(ValueError, "unverified launch eligibility"):
                    gate("codex")
        cell = {"state": "verified", "evidence": "synthetic proof", "verified_at": "2026-10-01"}
        with mock.patch.object(harness_contract, "harness_entries", return_value=[{"id": "codex", "launch_eligibility": cell}]):
            gate("codex")

    def test_override_reaches_targeted_runner_but_is_not_persisted(self):
        from convoy.convoy import list_seats
        runner = mock.Mock(return_value={"ok": True, "pid": 12345})
        capability = {"can_split": True, "adapter": "synthetic", "target": "synthetic-pane"}
        with mock.patch("convoy.targeted_launch.terminal_capability", return_value=capability), \
             mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True}), \
             mock.patch("convoy.targeted_launch.pane_child_argv", return_value=["synthetic-harness"]), \
             mock.patch("convoy.targeted_launch.active_pane_argv", return_value=["synthetic-host"]):
            card = launch_seat(self.root, self.sid, runner=runner, allow_unverified_launch=True, trust_probe=lambda _: True)
        self.assertTrue(card["ok"], card)
        runner.assert_called_once_with(["synthetic-host"])
        self.assertNotIn("allow_unverified_launch", list_seats(self.root)[0])

    def test_resume_go_cannot_bypass_eligibility_gate(self):
        from convoy.convoy import update_seat
        update_seat(self.root, self.sid, resume="synthetic-native-id", resume_for="grok")
        spawn = mock.Mock(return_value=12345)
        with mock.patch("convoy.graph_html.resume_argv", return_value=["synthetic-harness"]):
            card = resume_neuron(self.root, self.sid, go=True, spawn=spawn, liveness=lambda *_: False)
            self.assertFalse(card["ok"])
            spawn.assert_not_called()
            card = resume_neuron(self.root, self.sid, go=True, spawn=spawn, liveness=lambda *_: False,
                                 allow_unverified_launch=True)
            self.assertTrue(card["spawned"])
        spawn.assert_called_once()

    def test_cli_override_is_forwarded_and_defaults_false(self):
        import io
        from contextlib import redirect_stdout
        from convoy.cli import main
        for extra, expected in (([], False), (["--allow-unverified-launch"], True)):
            with mock.patch("convoy.cli.launch_seat", return_value={"ok": True}) as launch, redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--root", str(self.root), "launch", "--seat", self.sid, *extra]), 0)
            self.assertIs(launch.call_args.kwargs["allow_unverified_launch"], expected)

    def test_proven_harnesses_launch_without_override_despite_unverified_limits(self):
        for harness in ("claude", "codex", "cursor-agent"):
            with self.subTest(harness=harness):
                worktree = Path(self.tmp.name) / harness
                worktree.mkdir()
                sid = "synthetic-" + harness
                join(self.root, harness, session_id=sid, worktree=str(worktree))
                runner = mock.Mock(return_value={"ok": True, "pid": 12345})
                capability = {"can_split": True, "adapter": "synthetic", "target": "synthetic-pane"}
                with mock.patch("convoy.targeted_launch.terminal_capability", return_value=capability), \
                     mock.patch("convoy.targeted_launch.ensure_first_run", return_value={"ok": True}), \
                     mock.patch("convoy.targeted_launch.pane_child_argv", return_value=["synthetic-harness"]), \
                     mock.patch("convoy.targeted_launch.active_pane_argv", return_value=["synthetic-host"]):
                    card = launch_seat(self.root, sid, runner=runner)
                self.assertTrue(card["ok"], card)
                runner.assert_called_once()
                self.assertEqual(harness_contract.limit_contract(harness)["state"], "unverified")

    def test_mcp_override_is_boolean_and_advertised_for_every_launch_tool(self):
        from convoy.mcp_http import TOOLS, call_tool
        for tool in TOOLS:
            if tool["name"] in {"launch", "crew", "bring_up", "open", "resume", "send"}:
                self.assertEqual(tool["inputSchema"]["properties"]["allow_unverified_launch"]["type"], "boolean")
        with mock.patch("convoy.mcp_http._write_tools_enabled", return_value=True):
            for override in ("true", 1, None):
                card = call_tool(self.root, "launch", {"seat": self.sid, "allow_unverified_launch": override})
                self.assertFalse(card["ok"])
                self.assertIn("boolean", card["error"])


if __name__ == "__main__":
    unittest.main()
