"""Convoy 1.3.2: the MCP HTTP server is loopback only.

A browser page on any site can make the browser POST to http://127.0.0.1:8788,
and a DNS name that resolves to 127.0.0.1 (DNS rebinding) makes that page
same-origin with the server. The MCP Streamable HTTP transport says a server
MUST validate Origin for exactly this reason. So the server accepts a request
only when its Host is a loopback name or address on the port it listens on, and
any Origin it carries is an http:// loopback origin on that same port. Anything
else is a 403 before a body is read. No response carries CORS headers.

There is also no hosted endpoint, no tunnel, and no process-wide write flag:
writes need a conductor bearer, full stop.
"""
import http.client
import io
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from convoy import bearer as _bearer
from convoy.convoy import bind, ensure_id, seat

REPO = Path(__file__).resolve().parents[2]
NULL_PROBE = {"usage_remaining": None, "limited": False, "raw": None}

# Host values a DNS-rebinding page (or a confused proxy) presents. None of them
# names this machine's loopback on the server's port.
REBINDING_HOSTS = (
    "attacker.example:{port}",
    "127.0.0.1.nip.io:{port}",
    "localhost.attacker.example:{port}",
    "127.0.0.1.attacker.example:{port}",
    "10.0.0.7:{port}",
    "0.0.0.0:{port}",
    "[::ffff:127.0.0.1]:{port}",
    "127.0.0.1:{other}",
    "localhost:{other}",
    "127.0.0.1",
    "localhost",
    "127.0.0.1:{port}@attacker.example",
    "",
)
FOREIGN_ORIGINS = (
    "https://attacker.example",
    "http://attacker.example:{port}",
    "http://127.0.0.1.nip.io:{port}",
    "http://127.0.0.1:{other}",
    "https://127.0.0.1:{port}",
    "http://localhost",
    "null",
    "file://",
)


def _request(port, method, path, *, host="127.0.0.1:{port}", headers=None, body=None, connect="127.0.0.1"):
    """One raw request with full control of Host (http.client would otherwise add its own)."""
    conn = http.client.HTTPConnection(connect, port, timeout=20)
    try:
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host is not None:
            conn.putheader("Host", host.format(port=port, other=port + 1))
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            conn.putheader(k, v.format(port=port, other=port + 1))
        conn.endheaders(data)
        r = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


def _ping():
    return {"jsonrpc": "2.0", "id": 1, "method": "ping"}


def _call(name, arguments=None):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}


class _Server(unittest.TestCase):
    bind_host = "127.0.0.1"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch("convoy.mcp_http.probe", lambda _h: dict(NULL_PROBE))
        p.start(); self.addCleanup(p.stop)
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "loop")
        seat(self.root, "claude", "c-loop", worktree=str(self.root))
        from convoy.mcp_http import make_server
        self.httpd = make_server(self.root, self.bind_host, 0)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def req(self, method, path, **kw):
        kw.setdefault("connect", self.bind_host)
        return _request(self.port, method, path, **kw)

    def _feed(self):
        p = self.root / ".convoy" / "feed.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


class HostValidation(_Server):
    def test_dns_rebinding_hosts_get_403_on_get_post_and_options(self):
        for host in REBINDING_HOSTS:
            for method, path, body in (("GET", "/", None), ("GET", "/mcp", None), ("POST", "/mcp", _ping()),
                                       ("OPTIONS", "/mcp", None), ("HEAD", "/", None)):
                st, headers, _ = self.req(method, path, host=host, body=body)
                self.assertEqual(st, 403, "%s %s Host=%r answered %s" % (method, path, host, st))
                self.assertNotIn("access-control-allow-origin", headers)

    def test_a_missing_host_header_is_refused(self):
        st, _, _ = self.req("POST", "/mcp", host=None, body=_ping())
        self.assertEqual(st, 403)

    def test_a_rebinding_host_cannot_write_even_with_a_valid_bearer(self):
        card = _bearer.mint(label="t")
        st, _, _ = self.req("POST", "/mcp", host="attacker.example:{port}", body=_call("stamp", {"summary": "rebound"}),
                            headers={"Authorization": "Bearer " + card["bearer"]})
        self.assertEqual(st, 403)
        self.assertFalse([x for x in self._feed() if x.get("kind") == "conductor"])

    def test_loopback_names_on_the_listening_port_are_accepted(self):
        for host in ("127.0.0.1:{port}", "localhost:{port}", "LOCALHOST:{port}", "[::1]:{port}"):
            st, _, body = self.req("POST", "/mcp", host=host, body=_ping())
            self.assertEqual(st, 200, host)
            self.assertEqual(json.loads(body)["result"], {}, host)


class OriginValidation(_Server):
    def test_a_foreign_origin_gets_403_on_get_post_and_options(self):
        for origin in FOREIGN_ORIGINS:
            for method, path, body in (("POST", "/mcp", _ping()), ("GET", "/", None), ("OPTIONS", "/mcp", None)):
                st, headers, _ = self.req(method, path, body=body, headers={"Origin": origin})
                self.assertEqual(st, 403, "%s %s Origin=%r answered %s" % (method, path, origin, st))
                self.assertNotIn("access-control-allow-origin", headers)

    def test_a_foreign_origin_write_writes_nothing(self):
        card = _bearer.mint(label="t")
        st, _, _ = self.req("POST", "/mcp", body=_call("stamp", {"summary": "cross-site"}),
                            headers={"Origin": "https://attacker.example", "Authorization": "Bearer " + card["bearer"]})
        self.assertEqual(st, 403)
        self.assertFalse([x for x in self._feed() if x.get("kind") == "conductor"])

    def test_a_missing_origin_from_a_loopback_host_is_allowed(self):
        st, _, body = self.req("POST", "/mcp", body=_ping())
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["result"], {})

    def test_a_loopback_origin_on_the_same_port_is_allowed(self):
        for origin in ("http://127.0.0.1:{port}", "http://localhost:{port}", "http://[::1]:{port}"):
            st, _, _ = self.req("POST", "/mcp", body=_ping(), headers={"Origin": origin})
            self.assertEqual(st, 200, origin)


class NoCors(_Server):
    def test_no_response_carries_cors_headers(self):
        cases = [("POST", "/mcp", _ping(), {}), ("GET", "/", None, {}), ("GET", "/mcp", None, {}),
                 ("GET", "/nope", None, {}), ("OPTIONS", "/mcp", None, {}),
                 ("OPTIONS", "/mcp", None, {"Origin": "http://127.0.0.1:{port}", "Access-Control-Request-Method": "POST"}),
                 ("POST", "/mcp", _ping(), {"Origin": "https://attacker.example"})]
        for method, path, body, headers in cases:
            st, got, _ = self.req(method, path, body=body, headers=headers)
            for h in got:
                self.assertFalse(h.startswith("access-control-"), "%s %s -> %s carries %s" % (method, path, st, h))


class GetSurface(_Server):
    def test_get_root_from_loopback_is_a_minimal_page_without_assets(self):
        from convoy import version
        st, headers, body = self.req("GET", "/")
        self.assertEqual(st, 200)
        self.assertTrue(headers.get("content-type", "").startswith("text/"))
        text = body.decode("utf-8")
        self.assertIn("Convoy MCP v" + version.package_version() + " on this machine", text)
        self.assertIn("POST JSON-RPC to /mcp", text)
        self.assertRegex(text, r"Threads: \d+")
        self.assertNotIn("convoy.bot", text.lower())
        self.assertNotIn("<link", text.lower())
        self.assertNotIn("<script src", text.lower())

    def test_a_proxied_get_is_404_everywhere(self):
        for proxy in ({"Cf-Connecting-Ip": "198.51.100.4"}, {"X-Forwarded-For": "198.51.100.4"},
                      {"Forwarded": "for=198.51.100.4"}, {"X-Real-Ip": "198.51.100.4"}):
            for path in ("/", "/mcp", "/styles.css", "/favicon.svg", "/og.png"):
                st, _, body = self.req("GET", path, headers=proxy)
                self.assertEqual(st, 404, "%s via %s answered %s" % (path, proxy, st))
                self.assertNotIn(b"Threads:", body)

    def test_get_mcp_stays_405_and_the_old_site_assets_are_gone(self):
        st, headers, _ = self.req("GET", "/mcp")
        self.assertEqual(st, 405)
        self.assertEqual(headers.get("allow"), "POST, OPTIONS")
        for path in ("/styles.css", "/app.js", "/og.png", "/favicon.svg", "/fonts/work-sans-latin.woff2", "/mcp.html"):
            st, _, _ = self.req("GET", path)
            self.assertEqual(st, 404, path)


class Ipv6Loopback(_Server):
    bind_host = "::1"

    def setUp(self):
        try:
            s = socket.socket(socket.AF_INET6); s.bind(("::1", 0)); s.close()
        except OSError:
            self.skipTest("no IPv6 loopback on this machine")
        super().setUp()

    def test_an_ipv6_loopback_server_accepts_its_own_host_and_origin(self):
        st, _, body = self.req("POST", "/mcp", host="[::1]:{port}", body=_ping(),
                               headers={"Origin": "http://[::1]:{port}"})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["result"], {})

    def test_an_ipv6_loopback_server_refuses_a_rebinding_host(self):
        st, _, _ = self.req("POST", "/mcp", host="attacker.example:{port}", body=_ping())
        self.assertEqual(st, 403)

    def test_an_ipv6_loopback_peer_is_local(self):
        st, _, body = self.req("POST", "/mcp", host="[::1]:{port}", body=_call("threads"))
        self.assertEqual(st, 200)
        card = json.loads(body)["result"]["structuredContent"]
        self.assertIn("threads", card, "a ::1 peer is the machine's own, not an anonymous public caller")


class WritesNeedABearer(_Server):
    def test_the_removed_flag_opens_nothing(self):
        with mock.patch.dict(os.environ, {"CONVOY_MCP_WRITE_TOOLS": "1"}):
            st, _, body = self.req("POST", "/mcp", body=_call("stamp", {"summary": "flagged"}))
            self.assertEqual(st, 200)
            self.assertTrue(json.loads(body)["result"]["isError"])
            self.assertFalse([x for x in self._feed() if x.get("kind") == "conductor"])
            st, _, body = self.req("POST", "/mcp", body={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            names = {t["name"] for t in json.loads(body)["result"]["tools"]}
            self.assertNotIn("stamp", names)
            st, _, body = self.req("POST", "/mcp", body=_call("roster"))
            self.assertEqual(json.loads(body)["result"]["structuredContent"]["conductor"]["write_gate"], "closed")

    def test_the_gate_text_names_the_bearer_and_not_the_flag(self):
        st, _, body = self.req("POST", "/mcp", body=_call("stamp", {"summary": "x"}))
        err = json.loads(body)["result"]["structuredContent"]["error"]
        self.assertIn("convoy conductor mint", err)
        self.assertNotIn("CONVOY_MCP_WRITE_TOOLS", err)

    def test_a_bearer_on_a_loopback_host_still_writes(self):
        card = _bearer.mint(label="t")
        for host in ("127.0.0.1:{port}", "localhost:{port}"):
            st, _, body = self.req("POST", "/mcp", host=host, body=_call("stamp", {"summary": "local " + host}),
                                   headers={"Authorization": "Bearer " + card["bearer"]})
            self.assertEqual(st, 200)
            self.assertFalse(json.loads(body)["result"]["isError"], body)
        rows = [x for x in self._feed() if x.get("kind") == "conductor"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["principal"], {"bearer": card["id"]})

    def test_local_read_tools_still_work(self):
        for name in ("threads", "feed", "neurons", "glance", "card", "choices"):
            st, _, body = self.req("POST", "/mcp", body=_call(name, {"thread": "loop"}))
            self.assertEqual(st, 200, name)
            self.assertNotIn("error", json.loads(body), name)

    def test_no_source_reads_the_flag(self):
        hits = [p.name for p in (REPO / "src" / "convoy").rglob("*.py")
                if "CONVOY_MCP_WRITE_TOOLS" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [])


class TunnelAndSiteRemoved(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        env.start(); self.addCleanup(env.stop)
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "rm")

    def test_the_tunnel_runner_and_the_site_package_are_gone(self):
        import importlib.util
        self.assertIsNone(importlib.util.find_spec("convoy.tunnel_run"))
        self.assertIsNone(importlib.util.find_spec("convoy.site"))
        for rel in ("src/convoy/tunnel_run.py", "src/convoy/site", "wrangler.jsonc", "workers-site.mjs",
                    "docs/deploy-convoy-bot-mcp.md"):
            self.assertFalse((REPO / rel).exists(), rel)

    def test_package_data_ships_the_widget_page_not_the_site(self):
        import tomllib
        data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        pkg = data["tool"]["setuptools"]["package-data"]["convoy"]
        self.assertNotIn("site/**", pkg)
        self.assertIn("widget_page/**", pkg)

    def test_the_widget_serves_its_page_and_fonts_from_widget_page(self):
        from convoy import widget_web
        page = REPO / "src" / "convoy" / "widget_page"
        self.assertEqual(Path(widget_web.PAGE).resolve(), page.resolve())
        for route in ("/assets/fonts/work-sans-latin.woff2", "/assets/fonts/jetbrains-mono-latin.woff2"):
            path, _ = widget_web.ASSETS[route]
            self.assertTrue(Path(path).resolve().is_relative_to(page.resolve()), route)
            self.assertTrue(Path(path).is_file(), route)
        for name in ("index.html", "widget.js", "favicon.svg", "fonts/OFL-work-sans.txt", "fonts/OFL-jetbrains-mono.txt"):
            self.assertTrue((page / name).is_file(), name)

    def test_local_install_plans_no_tunnel_task(self):
        from convoy.local_install import install_local
        try:
            from test.demo.local_install_test import FakeRunner
        except ModuleNotFoundError:
            from local_install_test import FakeRunner
        card = install_local(self.root, runner=FakeRunner(), windows=True)
        self.assertTrue(card["ok"], card)
        self.assertEqual([p["name"] for p in card["plan"]], ["origin", "console-script"])
        blob = json.dumps(card).lower()
        for word in ("tunnel", "cloudflared", "token"):
            self.assertNotIn(word, blob)

    def test_the_cli_refuses_the_removed_flags_and_names_the_replacement(self):
        from convoy.cli import main
        for flag in (["--token-file", "x.token"], ["--migrate-token"]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--root", str(self.root), "install", "--local", *flag])
            self.assertNotEqual(rc, 0, flag)
            card = json.loads(buf.getvalue())
            self.assertFalse(card["ok"])
            self.assertIn(flag[0], card["error"])
            self.assertIn("removed in Convoy 1.3.2", card["error"])
            self.assertIn("convoy mcp", card["error"])
            self.assertIn("http://127.0.0.1:8788/mcp", card["error"])

    def test_verify_reports_tunnel_leftovers_with_removal_commands_and_deletes_nothing(self):
        from convoy.local_install import install_local
        try:
            from test.demo.local_install_test import FakeRunner
        except ModuleNotFoundError:
            from local_install_test import FakeRunner
        tunnel = self.home / "tunnel"; tunnel.mkdir()
        for name in ("run.token", "Run-ConvoyBotTunnel.ps1", "cloudflared.log"):
            (tunnel / name).write_bytes(b"TUNNEL-BYTES-7f3a\n")

        class Runner(FakeRunner):
            def __call__(self, script):
                if "ConvoyBotTunnel" in script and "Get-ScheduledTask" in script:
                    self.scripts.append(script)
                    return {"ok": True, "stdout": json.dumps({"TaskName": "ConvoyBotTunnel", "State": "Disabled"}), "stderr": ""}
                return super().__call__(script)

        r = Runner()
        card = install_local(self.root, runner=r, verify_only=True, windows=True)
        left = card["leftovers"]
        names = {x["name"] for x in left}
        self.assertEqual(names, {"ConvoyBotTunnel", "run.token", "Run-ConvoyBotTunnel.ps1", "cloudflared.log"})
        for x in left:
            self.assertTrue(x["remove"], x)
        task = next(x for x in left if x["name"] == "ConvoyBotTunnel")
        self.assertIn("Unregister-ScheduledTask -TaskName ConvoyBotTunnel", task["remove"])
        for name in ("run.token", "Run-ConvoyBotTunnel.ps1", "cloudflared.log"):
            self.assertTrue((tunnel / name).is_file(), name + " must never be deleted by the verb")
        self.assertNotIn("TUNNEL-BYTES-7f3a", json.dumps(card), "a leftover file's bytes are never read into the card")
        for s in r.scripts:
            self.assertNotIn("Unregister-ScheduledTask", s, "the verb reports; it never unregisters")
            self.assertNotIn("Remove-Item", s)

    def test_verify_with_no_leftovers_reports_an_empty_list(self):
        from convoy.local_install import install_local
        try:
            from test.demo.local_install_test import FakeRunner
        except ModuleNotFoundError:
            from local_install_test import FakeRunner
        card = install_local(self.root, runner=FakeRunner(), verify_only=True, windows=True)
        self.assertEqual(card["leftovers"], [])


class BuiltWheel(unittest.TestCase):
    def test_the_wheel_has_no_site_package_and_carries_the_widget_page(self):
        import shutil
        import subprocess
        import zipfile
        import importlib.util
        if importlib.util.find_spec("setuptools") is None:
            self.skipTest("setuptools is not installed; the wheel cannot be built offline")
        work = Path(tempfile.mkdtemp())
        src = work / "src"
        shutil.copytree(REPO / "src" / "convoy", src / "convoy",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(REPO / name, work / name)
        out = work / "dist"
        r = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                            "--no-index", "-q", "-w", str(out), str(work)],
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        wheels = list(out.glob("convoy-*.whl"))
        self.assertEqual(len(wheels), 1, wheels)
        names = zipfile.ZipFile(wheels[0]).namelist()
        self.assertFalse([n for n in names if n.startswith("convoy/site/")])
        self.assertFalse([n for n in names if n.startswith("convoy/tunnel_run")])
        for want in ("convoy/widget_page/index.html", "convoy/widget_page/widget.js",
                     "convoy/widget_page/favicon.svg", "convoy/widget_page/fonts/work-sans-latin.woff2",
                     "convoy/widget_page/fonts/OFL-work-sans.txt"):
            self.assertIn(want, names)


def _lan_ip():
    """This machine's non-loopback IPv4 address, or None when it has none."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))   # TEST-NET-1: nothing is sent
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


class NonLoopbackPeer(unittest.TestCase):
    """Host can be forged by any non-browser client, so loopback-only must also
    mean a loopback peer, and the server must refuse to bind anything else."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"CONVOY_HOME": str(self.home)})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch("convoy.mcp_http.probe", lambda _h: dict(NULL_PROBE))
        p.start(); self.addCleanup(p.stop)
        self.root = Path(tempfile.mkdtemp()); ensure_id(self.root); bind(self.root, "loop")

    def _wildcard_server(self):
        # Built directly: make_server itself refuses a wildcard bind.
        from convoy.mcp_http import McpHTTPServer
        httpd = McpHTTPServer(("0.0.0.0", 0), self.root)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return httpd.server_address[1]

    def test_a_non_loopback_peer_with_a_forged_loopback_host_gets_403_on_every_method(self):
        port = self._wildcard_server()
        with mock.patch("convoy.mcp_http.McpHandler._peer", return_value="192.0.2.10"):
            for method, path, body in (("POST", "/mcp", _ping()), ("POST", "/mcp", _call("threads")),
                                       ("GET", "/", None), ("GET", "/mcp", None), ("OPTIONS", "/mcp", None)):
                st, headers, _ = _request(port, method, path, body=body)
                self.assertEqual(st, 403, "%s %s from a LAN peer answered %s" % (method, path, st))
                self.assertNotIn("access-control-allow-origin", headers)

    def test_a_real_lan_connection_with_a_forged_loopback_host_gets_403(self):
        ip = _lan_ip()
        if ip is None:
            self.skipTest("no non-loopback IPv4 address on this machine")
        port = self._wildcard_server()
        try:
            st, _, _ = _request(port, "POST", "/mcp", body=_call("threads"), connect=ip)
        except OSError as exc:
            self.skipTest("cannot reach this machine's own LAN address: " + type(exc).__name__)
        self.assertEqual(st, 403)

    def test_the_same_server_still_answers_a_loopback_peer(self):
        port = self._wildcard_server()
        st, _, body = _request(port, "POST", "/mcp", body=_ping())
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["result"], {})

    def test_make_server_refuses_a_non_loopback_host(self):
        from convoy.mcp_http import make_server
        for host in ("0.0.0.0", "::", "[::]", "10.0.0.7", "192.0.2.10", "example.com", ""):
            with self.assertRaises(ValueError, msg=host):
                srv = make_server(self.root, host, 0)
                srv.server_close()

    def test_make_server_refuses_loopback_spellings_beyond_the_three_names(self):
        from convoy.mcp_http import make_server
        for host in ("127.0.0.2", "127.1.2.3", "::ffff:127.0.0.1", "LOCALHOST.", "0:0:0:0:0:0:0:1"):
            with self.assertRaises(ValueError, msg=host):
                srv = make_server(self.root, host, 0)
                srv.server_close()

    def test_make_server_accepts_the_loopback_hosts(self):
        from convoy.mcp_http import make_server
        for host in ("127.0.0.1", "localhost"):
            srv = make_server(self.root, host, 0)
            srv.server_close()

    def test_the_cli_refuses_a_non_loopback_host_without_serving(self):
        from convoy.cli import main
        err = io.StringIO()
        with mock.patch("convoy.mcp_http.McpHTTPServer.serve_forever") as forever, \
             mock.patch("sys.stderr", err):
            rc = main(["mcp", "--host", "0.0.0.0", "--port", "0"])
        self.assertNotEqual(rc, 0)
        self.assertFalse(forever.called)
        self.assertIn("loopback", err.getvalue())


class StrictHost(_Server):
    def test_a_port_with_a_leading_zero_is_refused(self):
        st, _, _ = self.req("POST", "/mcp", host="127.0.0.1:0{port}", body=_ping())
        self.assertEqual(st, 403)

    def test_an_absolute_form_request_target_is_refused(self):
        # RFC 9112 prefers the authority in an absolute-form target over Host.
        for method in ("GET", "POST", "OPTIONS"):
            st, _, _ = self.req(method, "http://evil.example/mcp", body=_ping() if method == "POST" else None)
            self.assertEqual(st, 403, method)
        st, _, _ = self.req("OPTIONS", "*")
        self.assertEqual(st, 403)

    def test_two_host_headers_are_refused(self):
        st, _, _ = self.req("POST", "/mcp", body=_ping(), headers={"Host": "127.0.0.1:{port}"})
        self.assertEqual(st, 403)

    def test_a_refused_request_that_stalls_its_body_still_gets_its_403_promptly(self):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=4)
        try:
            s.sendall(("POST /mcp HTTP/1.1\r\nHost: attacker.example:%d\r\nContent-Type: text/plain\r\n"
                       "Content-Length: 1000000\r\n\r\n" % self.port).encode("ascii"))
            got = s.recv(64)
        finally:
            s.close()
        self.assertTrue(got.startswith(b"HTTP/1.0 403") or got.startswith(b"HTTP/1.1 403"), got)


def _second_bind_succeeds(host, port, family=socket.AF_INET):
    """Can another local process bind host:port while the server holds it?"""
    s = socket.socket(family, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Hardening(_Server):
    """Cheap hardening on top of the loopback gate: nosniff on every response,
    a 403 (not 501) for a method with no handler, and a listening port no other
    local process can bind on Windows."""

    def test_every_response_says_nosniff(self):
        cases = [("POST", "/mcp", _ping(), {}, "127.0.0.1:{port}"), ("GET", "/", None, {}, "127.0.0.1:{port}"),
                 ("GET", "/nope", None, {}, "127.0.0.1:{port}"), ("OPTIONS", "/mcp", None, {}, "127.0.0.1:{port}"),
                 ("GET", "/", None, {}, "attacker.example:{port}")]
        for method, path, body, headers, host in cases:
            st, got, _ = self.req(method, path, body=body, headers=headers, host=host)
            self.assertEqual(got.get("x-content-type-options"), "nosniff", "%s %s %s -> %s" % (method, path, host, st))

    def test_a_method_with_no_handler_is_403_off_loopback_and_405_on_it(self):
        for method in ("PUT", "DELETE", "PATCH", "TRACE", "FOO"):
            st, _, _ = self.req(method, "/mcp", host="attacker.example:{port}")
            self.assertEqual(st, 403, method)
            st, got, _ = self.req(method, "/mcp")
            self.assertEqual(st, 405, method)
            self.assertEqual(got.get("allow"), "POST, OPTIONS", method)

    def test_a_non_loopback_peer_gets_403_on_a_method_with_no_handler(self):
        with mock.patch("convoy.mcp_http.McpHandler._peer", return_value="192.0.2.10"):
            st, _, _ = self.req("DELETE", "/mcp")
        self.assertEqual(st, 403)

    @unittest.skipUnless(os.name == "nt", "SO_EXCLUSIVEADDRUSE is Windows only")
    def test_no_other_local_socket_can_bind_the_listening_port(self):
        self.assertFalse(_second_bind_succeeds("127.0.0.1", self.port))


if __name__ == "__main__":
    unittest.main()
