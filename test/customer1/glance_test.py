import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.cli import main
from convoy.convoy import bind, ensure_id, seat
from convoy.layer import hook
from convoy.mcp_http import make_server


def _run(root: Path, *argv: str) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["--root", str(root), *argv])
    payload = json.loads(out.getvalue())
    return rc, payload


def _which_map(mapping: dict[str, str | None]):
    def fake_which(name: str) -> str | None:
        return mapping.get(str(name).lower())
    return fake_which


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _keys(item)


def _rpc(url: str, method: str, params=None, rpc_id=1):
    import urllib.request

    body = {"jsonrpc": "2.0", "method": method, "id": rpc_id}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


class Glance(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".ola").mkdir()
        (self.root / ".ola" / "brief.md").write_text("brief")
        self.cid = ensure_id(self.root)
        bind(self.root, "convoy")
        self.wt_g = Path(tempfile.mkdtemp())
        self.wt_c = Path(tempfile.mkdtemp())

    def test_glance_json_overall_keyed_honest_nulls_and_missing_harness(self):
        def fake_probe(to: str):
            if to == "grok":
                return {"usage_remaining": 0, "limited": False, "raw": None}
            if to == "claude":
                blob = "Current session: 12% used\nCurrent week (all models): 55% used"
                return {"usage_remaining": blob, "limited": False, "raw": blob}
            if to == "agy":
                return {"usage_remaining": None, "limited": False, "raw": None}
            return {"usage_remaining": None, "limited": False, "raw": None}

        mapping = {
            "grok": "/fake/grok",
            "claude": "/fake/claude",
            "codex": None,
            "cursor-agent": None,
            "agy": "/fake/agy",
        }
        with mock.patch("convoy.glance.probe", side_effect=fake_probe), mock.patch(
            "convoy.glance.shutil.which", side_effect=_which_map(mapping)
        ):
            rc, card = _run(self.root, "glance", "--json")
        self.assertEqual(rc, 0)
        overall = card["overall"]
        self.assertEqual(list(overall.keys()), ["grok", "claude", "codex", "cursor-agent", "agy"])
        self.assertIsNone(overall["grok"]["usage_remaining"])
        self.assertNotEqual(overall["grok"]["usage_remaining"], 0)
        self.assertIsNone(overall["claude"]["usage_remaining"])
        self.assertEqual(overall["claude"]["session_pct"], 12)
        self.assertEqual(overall["claude"]["week_pct"], 55)
        self.assertFalse(overall["codex"]["present"])
        self.assertEqual(overall["codex"]["badge"], "missing")
        self.assertIsNone(overall["codex"]["usage_remaining"])
        keys = list(_keys(card))
        self.assertFalse(any("dollar" in k.lower() for k in keys))
        self.assertFalse(any("usd" in k.lower() for k in keys))

    def test_by_thread_filters_convoy_id_only_and_omits_unknown_model(self):
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        seat(self.root, "claude", "sess-claude", worktree=str(self.wt_c), model="Fable 5")
        seats_path = self.root / ".convoy" / "seats.jsonl"
        with seats_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "convoy_id": "cvy_other",
                        "to": "codex",
                        "session_id": "sess-other",
                        "worktree": str(self.wt_c),
                        "model": "codex-latest",
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        hook(self.root, kind="synapse", summary="send grok", instance_id="sess-grok", extra={"to": "grok"})

        def fake_probe(_to: str):
            return {"usage_remaining": None, "limited": False, "raw": None}

        mapping = {h: f"/fake/{h}" for h in ("grok", "claude", "codex", "cursor-agent", "agy")}
        with mock.patch("convoy.glance.probe", side_effect=fake_probe), mock.patch(
            "convoy.glance.shutil.which", side_effect=_which_map(mapping)
        ):
            rc, card = _run(self.root, "glance", "--json", "--convoy-id", self.cid)
        self.assertEqual(rc, 0)
        by_thread = card["by_thread"]
        self.assertTrue(by_thread["ok"])
        self.assertEqual(by_thread["convoy_id"], self.cid)
        self.assertEqual(by_thread["seat_count"], 2)
        seats = by_thread["seats"]
        self.assertEqual({s["session_id"] for s in seats}, {"sess-grok", "sess-claude"})
        by_to = {s["to"]: s for s in seats}
        self.assertIn("last_synapse", by_to["grok"])
        self.assertNotIn("model", by_to["grok"])
        self.assertEqual(by_to["claude"]["model"], "Fable 5")
        self.assertNotIn("week_pct", by_to["claude"])

    def test_glance_thread_selector_returns_seats(self):
        seat(self.root, "grok", "sess-grok", worktree=str(self.wt_g))
        with mock.patch("convoy.glance.probe", return_value={"usage_remaining": None, "limited": False, "raw": None}), mock.patch(
            "convoy.glance.shutil.which", return_value="/fake/bin"
        ):
            rc, card = _run(self.root, "glance", "--json", "--thread", "convoy")
        self.assertEqual(rc, 0)
        self.assertTrue(card["by_thread"]["ok"])
        self.assertEqual(card["by_thread"]["thread"], "convoy")
        self.assertEqual(card["by_thread"]["seat_count"], 1)

    def test_mcp_tools_list_includes_glance(self):
        httpd = make_server(self.root, "127.0.0.1", 0)
        port = httpd.server_address[1]
        t = None
        try:
            import threading

            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            mcp = "http://127.0.0.1:%s/mcp" % port
            listed = _rpc(mcp, "tools/list")
            names = [tool["name"] for tool in listed["result"]["tools"]]
            self.assertIn("glance", names)
        finally:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
            if t is not None:
                t.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
