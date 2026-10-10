"""The report client: the only place Convoy speaks to the platform.

Convoy is open MIT and the platform is closed. This module is the seam: it
speaks the public OpenAPI and nothing else, over stdlib urllib, and it holds
no state a reader could mistake for a session.

Five guarantees:

1. Unpaired is OFF. With no origin.json the client does not exist, so a
   machine that never opted in cannot make a request by accident.
2. The credential is read at CALL time from the file origin.json names,
   with utf-8-sig (PowerShell 5.1 writes a BOM and the BOM becomes the first
   character of the Authorization header, failing as an opaque 403), asserted
   ASCII, and never echoed - not in a log line, not in an exception.
3. Every call sends a browser User-Agent. Cloudflare rejects the default
   Python-urllib agent with `error code: 1010` BEFORE the credential is read,
   which is indistinguishable from a bad credential unless you look.
4. So a 403 is triaged by its BODY: a WAF code is Transient, an auth body is
   Revoked. Reporting a WAF page as a revoked credential would have a paired
   machine unpair itself over a network hiccup.
5. Writes carry an Idempotency-Key and reads do not.
"""
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy.report import (  # noqa: E402
    USER_AGENT,
    ReportClient,
    Revoked,
    Transient,
    read_origin,
)

CREDENTIAL = "o_cred_abcdef0123456789"


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class Receiver:
    """Records requests; answers with whatever the test queued."""

    def __init__(self, *answers):
        self.requests = []
        self.answers = list(answers) or [FakeResponse()]

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        answer = self.answers[0] if len(self.answers) == 1 else self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class ReportClientContract(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="convoy-home-"))
        self.cred = self.home / "origin_credential.txt"
        self.cred.write_text(CREDENTIAL, encoding="utf-8")
        (self.home / "origin.json").write_text(json.dumps({
            "origin_id": "o_1234567890abcdef1234",
            "org_id": "org1",
            "user_id": "u1",
            "machine_id": "m1",
            "api_base": "https://example.invalid",
            "credential_path": str(self.cred),
            "paired_at": "2026-09-17T00:00:00.000000Z",
        }), encoding="utf-8")

    def _client(self, receiver):
        return ReportClient(read_origin(self.home), opener=receiver)

    def test_unpaired_origin_never_calls_out(self):
        empty = Path(tempfile.mkdtemp(prefix="convoy-unpaired-"))
        self.assertIsNone(read_origin(empty))
        receiver = Receiver()
        self.assertIsNone(ReportClient.from_home(empty, opener=receiver))
        self.assertEqual(receiver.requests, [], "an unpaired machine makes no request at all")

    def test_reads_speak_only_public_paths_with_a_browser_agent(self):
        receiver = Receiver(FakeResponse(200, b'{"links":[]}'))
        out = self._client(receiver).origin_queue()
        self.assertEqual(out["status"], 200)
        self.assertEqual(out["body"], {"links": []})
        request = receiver.requests[0]
        self.assertEqual(request.full_url, "https://example.invalid/api/org/worklanes/origin/queue")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertNotIn("python-urllib", (request.get_header("User-agent") or "").lower())
        self.assertEqual(request.get_header("Authorization"), "Bearer " + CREDENTIAL)
        self.assertIsNone(request.get_header("Idempotency-key"), "a read is not a write")

    def test_writes_carry_one_idempotency_key_each(self):
        receiver = Receiver(FakeResponse(200, b'{"outcome":"active"}'), FakeResponse(200, b'{}'),
                            FakeResponse(200, b'{}'))
        client = self._client(receiver)
        client.fulfil("card1", "link1", {"outcome": "active"})
        client.report("t_token", {"delivered": "delivered"})
        client.beat({"threads": []})
        paths = [r.selector for r in receiver.requests]
        self.assertEqual(paths, [
            "/api/org/worklanes/cards/card1/threads/link1/fulfil",
            "/api/org/worklanes/delegations/t_token/report",
            "/api/org/worklanes/origin/beat",
        ])
        keys = [r.get_header("Idempotency-key") for r in receiver.requests]
        self.assertTrue(all(keys), keys)
        self.assertEqual(len(set(keys)), 3, "one key per write, never one per process")
        self.assertEqual([r.get_method() for r in receiver.requests], ["POST", "POST", "POST"])

    def test_path_segments_are_escaped_never_concatenated_raw(self):
        receiver = Receiver(FakeResponse(200, b"{}"))
        self._client(receiver).fulfil("card/../../admin", "l 1", {})
        self.assertEqual(receiver.requests[0].selector,
                         "/api/org/worklanes/cards/card%2F..%2F..%2Fadmin/threads/l%201/fulfil")

    def test_answer_nudge_posts_the_origin_nudges_path_with_the_outcome(self):
        receiver = Receiver(FakeResponse(200, b"{}"))
        self._client(receiver).answer_nudge("n1", "unsupported", "no pane host on this machine")
        request = receiver.requests[0]
        self.assertEqual(request.selector, "/api/org/worklanes/origin/nudges/n1")
        self.assertEqual(request.get_method(), "POST")
        self.assertIsNotNone(request.get_header("Idempotency-key"), "a write")
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent, {"outcome": "unsupported", "reason": "no pane host on this machine"})

    def test_answer_nudge_omits_reason_when_none_given(self):
        receiver = Receiver(FakeResponse(200, b"{}"))
        self._client(receiver).answer_nudge("n1", "nudged")
        sent = json.loads(receiver.requests[0].data.decode("utf-8"))
        self.assertEqual(sent, {"outcome": "nudged"})

    def test_credential_never_appears_in_logs_or_exceptions(self):
        logged = []
        boom = urllib.error.HTTPError("https://example.invalid/x", 500, "Server Error", {},
                                      io.BytesIO(b"upstream exploded"))
        receiver = Receiver(boom)
        client = ReportClient(read_origin(self.home), opener=receiver, log=logged.append)
        with self.assertRaises(Transient) as caught:
            client.origin_queue()
        self.assertNotIn(CREDENTIAL, str(caught.exception))
        self.assertNotIn(CREDENTIAL, repr(caught.exception))
        self.assertTrue(logged, "the client must say what it did")
        self.assertNotIn(CREDENTIAL, "\n".join(logged))

    def test_403_with_waf_code_is_not_reported_as_auth_failure(self):
        waf = urllib.error.HTTPError("https://example.invalid/x", 403, "Forbidden", {},
                                     io.BytesIO(b"error code: 1010"))
        with self.assertRaises(Transient) as caught:
            self._client(Receiver(waf)).origin_queue()
        self.assertIn("1010", str(caught.exception))

        real = urllib.error.HTTPError("https://example.invalid/x", 403, "Forbidden", {},
                                      io.BytesIO(b'{"error":"origin_revoked"}'))
        with self.assertRaises(Revoked):
            self._client(Receiver(real)).origin_queue()

    def test_5xx_and_network_errors_are_transient_not_revoked(self):
        for failure in (urllib.error.HTTPError("https://example.invalid/x", 503, "busy", {}, io.BytesIO(b"")),
                        urllib.error.URLError("connection refused")):
            with self.assertRaises(Transient):
                self._client(Receiver(failure)).origin_queue()

    def test_credential_is_read_at_call_time_and_a_bom_is_stripped(self):
        receiver = Receiver(FakeResponse(), FakeResponse())
        client = self._client(receiver)
        client.origin_queue()
        # PowerShell 5.1 `-Encoding utf8` writes a BOM; utf-8-sig eats it.
        self.cred.write_bytes(b"\xef\xbb\xbfo_rotated_9876543210" + b"\r\n")
        client.origin_queue()
        self.assertEqual(receiver.requests[1].get_header("Authorization"), "Bearer o_rotated_9876543210")

    def test_a_non_ascii_credential_is_refused_without_echoing_it(self):
        self.cred.write_text("o_cred_ééé", encoding="utf-8")
        receiver = Receiver()
        with self.assertRaises(ValueError) as caught:
            self._client(receiver).origin_queue()
        self.assertNotIn("é", str(caught.exception))
        self.assertEqual(receiver.requests, [], "nothing goes out with a credential we cannot send")

    def test_client_imports_nothing_from_the_platform(self):
        import ast
        source = (Path(__file__).resolve().parents[2] / "src" / "convoy" / "report.py").read_text(encoding="utf-8")
        local = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom) and node.level:
                local.add(node.module or "")
        self.assertEqual(local, set(), "the report client is standalone stdlib; it imports no sibling")


if __name__ == "__main__":
    unittest.main()
