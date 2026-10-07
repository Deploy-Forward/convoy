"""Step 3 of the grok-bot rebase (amendment move 2): identity on
the wire. A conductor bearer minted by `convoy conductor mint`, checked at the
origin on every write, `from` set from the bearer and never from an argument.
The global process flag that used to open writes is gone (Convoy 1.3.2):
without a bearer the write tools refuse and name the mint verb.
Tests written before the code."""
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from convoy.convoy import bind, ensure_id, seat


def _rpc(url, method, params=None, headers=None):
    body = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        body["params"] = params
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _payload(resp):
    return resp["result"]["structuredContent"]


class Mint(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)

    def test_mint_stores_only_a_hash_and_shows_the_bearer_once(self):
        from convoy import bearer
        card = bearer.mint(label="grok-bot connector")
        self.assertTrue(card["ok"]); self.assertEqual(card["conductor"], "grok-bot")
        tok = card["bearer"]
        self.assertTrue(tok.startswith("cvb_")); self.assertGreater(len(tok), 30)
        rows = [json.loads(x) for x in (self.home / "conductors.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertNotIn(tok, json.dumps(rows), "the bearer itself is never on disk")
        self.assertEqual(rows[0]["id"], card["id"]); self.assertEqual(rows[0]["label"], "grok-bot connector")
        self.assertEqual(bearer.check(tok), {"id": card["id"], "conductor": "grok-bot", "label": "grok-bot connector"})
        self.assertIsNone(bearer.check(tok[:-1] + "x")); self.assertIsNone(bearer.check("")); self.assertIsNone(bearer.check(None))
        listed = bearer.list_conductors()
        self.assertEqual([r["id"] for r in listed], [card["id"]])
        self.assertNotIn("sha256", json.dumps(listed), "the list never echoes the hash")

    def test_revoke_closes_the_bearer_and_is_visible_in_the_list(self):
        from convoy import bearer
        card = bearer.mint()
        self.assertTrue(bearer.revoke(card["id"])["ok"])
        self.assertIsNone(bearer.check(card["bearer"]))
        self.assertTrue(bearer.list_conductors()[0]["revoked"])
        self.assertFalse(bearer.revoke("nope")["ok"])

    def test_cli_mint_prints_the_card_once_and_never_logs_it(self):
        from convoy.cli import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["conductor", "mint", "--label", "t"])
        card = json.loads(buf.getvalue())
        self.assertEqual(rc, 0); self.assertIn("bearer", card)
        self.assertIn("Authorization: Bearer", card["next"])
        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            main(["conductor", "list"])
        self.assertNotIn(card["bearer"], buf2.getvalue())


class BearerAtTheOrigin(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)}); p.start(); self.addCleanup(p.stop)
        # The server reads usage through mcp_http.probe, and the real one runs
        # `claude -p /usage` on the operator's account. A null reading is enough here.
        p = mock.patch("convoy.mcp_http.probe", side_effect=lambda _h: {"usage_remaining": None, "limited": False, "raw": None})
        p.start(); self.addCleanup(p.stop)
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "cb")
        seat(self.root, "claude", "c-cb", worktree=str(self.root))
        from convoy.mcp_http import make_server
        self.httpd = make_server(self.root, "127.0.0.1", 0)
        self.url = "http://127.0.0.1:%d/mcp" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.shutdown)

    def _feed(self):
        p = self.root / ".convoy" / "feed.jsonl"
        if not p.is_file():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]

    def test_no_bearer_no_flag_means_writes_refuse_and_name_the_mint_verb(self):
        r = _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "forged"}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("convoy conductor mint", _payload(r)["error"])
        self.assertFalse(any(x["kind"] == "conductor" for x in self._feed()))
        listed = {t["name"] for t in _rpc(self.url, "tools/list")["result"]["tools"]}
        self.assertNotIn("stamp", listed, "with nothing minted the process cannot accept writes, so it lists none")

    def test_a_minted_bearer_opens_the_write_tools_for_its_holder_only(self):
        from convoy import bearer
        card = bearer.mint(label="conn")
        listed = {t["name"] for t in _rpc(self.url, "tools/list")["result"]["tools"]}
        self.assertIn("stamp", listed, "a minted bearer means this process accepts writes")
        good = {"Authorization": "Bearer " + card["bearer"]}
        r = _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "real"}}, headers=good)
        self.assertFalse(r["result"]["isError"], r)
        row = [x for x in self._feed() if x["kind"] == "conductor"][-1]
        self.assertEqual(row["from"], "grok-bot")
        self.assertEqual(row["principal"], {"bearer": card["id"]}, "a stamp can now be told from a forged one")
        self.assertNotIn(card["bearer"], json.dumps(self._feed()))
        r2 = _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "anon"}})
        self.assertTrue(r2["result"]["isError"], "anonymous callers still refuse")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "bad"}},
                 headers={"Authorization": "Bearer cvb_wrong"})
        self.assertEqual(cm.exception.code, 401)
        self.assertEqual(len([x for x in self._feed() if x["kind"] == "conductor"]), 1)

    def test_a_revoked_bearer_is_anonymous_again(self):
        from convoy import bearer
        card = bearer.mint(); bearer.revoke(card["id"])
        with self.assertRaises(urllib.error.HTTPError) as cm:
            _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "x"}},
                 headers={"Authorization": "Bearer " + card["bearer"]})
        self.assertEqual(cm.exception.code, 401)

    def test_roster_and_initialize_name_the_write_gate(self):
        from convoy import bearer
        self.assertEqual(_payload(_rpc(self.url, "tools/call", {"name": "roster"}))["conductor"]["write_gate"], "closed")
        bearer.mint()
        ros = _payload(_rpc(self.url, "tools/call", {"name": "roster"}))["conductor"]
        self.assertEqual(ros["write_gate"], "bearer"); self.assertEqual(ros["bearers"], 1)
        r = _rpc(self.url, "tools/call", {"name": "stamp", "arguments": {"summary": "no bearer"}})
        self.assertTrue(r["result"]["isError"], "a minted bearer elsewhere opens nothing for a caller without one")
        self.assertFalse([x for x in self._feed() if x["kind"] == "conductor"])
        init = _rpc(self.url, "initialize", {"protocolVersion": "2025-06-18"})["result"]["instructions"]
        self.assertIn("Bearer", init)

    def test_contract_text_moves_the_bearer_out_of_not_built_yet(self):
        from convoy.conductor import contract_text
        text = contract_text()
        nb = text[text.find("## Not built yet"):]
        nb = nb[:nb.find("## ", 5)]
        self.assertNotIn("bearer", nb.lower())
        self.assertIn("convoy conductor mint", text)


if __name__ == "__main__":
    unittest.main()
