"""Public-tree gate: nothing this repository publishes may carry a private
name, a real home directory, a real e-mail address, a vendor session id, a
Convoy thread, resume, bearer or neuron id, or a link to a conversation.

A rule in a document does not hold; this test does. It reads every file git
tracks (binary files excepted), so a new directory is covered the day it is
added, and it checks file names as well as file contents.

Private names are matched as hashed tokens so the denylist itself publishes
nothing. Generic shapes (home directories, e-mails, UUIDs, Convoy ids) are
matched directly. Placeholders are allowed: `C:\\Users\\<user>` or
`C:\\Users\\dev`, `*@example.test`, `*@convoy.test`, and the handful of
obviously synthetic ids the tests use, listed by value below.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve()
# Only used when git is not available (an unpacked archive): what a walk skips.
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "_keep_roots"}

# sha256 of each lowercase token that must not appear as a word, a hyphen
# piece or a run of hyphen pieces (client and project names, private checkout
# and host names, a personal mailbox, a colleague's first name). Hashed so
# this file publishes none of them.
PRIVATE_TOKEN_HASHES = {
    "5455f46c18ee89085db9a4e117b2385d706686365fcb70f3efc55573ff8708e4",
    "5a27d277352587f6b0f5eb5fd15a90843659ebadd7d463d826e56d0b441e4d9e",
    "6c3426e72dbaa6c57cd227660c906fabe9e69f3f34ca1b2f428fb126afe55750",
    "7cf1a6c9edefa9856a2cd638095c0dd22ecaff52dcc9d488fcf5ecdbb9a4ff65",
    "9d53ebf70ebaf39bd654d8c654c423b7760998a1fb1ad946ac0a94071c3dd973",
    "ae91d279770045247fb6fe6ac59bfef0bcdae686d2bd4f291b4d11805365407b",
    "c4acd9eb8ceeb3033f183f2b6d42b05a212116db765170259cf86d090b81554a",
    "c9149c3fd2e620617b64342e4b97eb0b6fce01448fc68e722f2d3dee8e5c8a41",
    "cebc4f33ebc5633cb386db2be51e6e0281c2239ae1879a74a4c04ff5683880ff",
    "e44839ea5f6d97917095ac3108b2e76d69c15d9e97ca24bd9ceca50eb278a249",
    "f0ef475450b8b96fd3cc2c487957d0317e07d28a08ab5ec90a313692582c7d8c",
    "1063854bbf5155bcf9fe8cf9b578d0e33f20823f6703aee5463bc88a41f8f9a4",
    "077af94d250e2377251877f9bd197c0025ccfeae58462afc7e9456ccbc346610",
    "14a145de224bfce394f8c84469b2f90ad85fc672c14a9dd21760d68227cf2564",
    "ea51e93d00f43687c4541b6e7f099654ed3ab06f3560b44321c8dea6183cc97d",
}

HOME_DIR = re.compile(r"(?i)[a-z]:\\{1,2}Users\\{1,2}([A-Za-z0-9_.-]+)")
HOME_DIR_POSIX = re.compile(r"(?:/Users|/home)/([A-Za-z0-9_.-]+)")
ALLOWED_HOME = {"<user>", "dev", "user", "you", "public", "default", "demo", "x", "m"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[a-z]{2,})")
ALLOWED_EMAIL_DOMAINS = {"example.test", "convoy.test", "example.com", "users.noreply.github.com", "anthropic.com", "github.com"}
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# The id shapes Convoy mints: a thread id is cvy_ + 22 url-safe characters,
# a resume key cvr_ + 16 hex, a bearer cvb_ + 43 url-safe characters, a
# neuron id n + 6 hex. Anything that long is treated as real.
THREAD_ID = re.compile(r"\bcvy_[A-Za-z0-9_-]{20,}")
RESUME_KEY = re.compile(r"\bcvr_[0-9a-f]{12,}")
BEARER = re.compile(r"\bcvb_[A-Za-z0-9_-]{20,}")
NEURON_ID = re.compile(r"(?<![A-Za-z0-9_])n[0-9a-f]{6}(?![A-Za-z0-9_])")
# A commit trailer or a link that names one conversation. Case-sensitive on
# purpose: a placeholder such as `<dry-claude-session>` is not a trailer.
CONVERSATION = re.compile(r"Claude-Session|claude\.ai/code/session_")
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Obviously synthetic ids the tests and docs use. Every other value of these
# shapes fails the gate; a new fixture adds its value here, visibly.
SYNTHETIC_UUIDS = {
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-4000-8000-000000000001",
    "00000000-0000-4000-8000-000000000002",
    "11111111-1111-1111-1111-111111111111",
    "11111111-1111-4111-8111-111111111111",
    "11111111-2222-3333-4444-555555555555",
    "22222222-2222-2222-2222-222222222222",
    "22222222-2222-4222-8222-222222222222",
}
SYNTHETIC_CONVOY_IDS: set[str] = set()
SYNTHETIC_NEURON_IDS = {"n000000"}


def _sha(token: str) -> str:
    return hashlib.sha256(token.lower().encode("utf-8")).hexdigest()


def _tracked() -> list[str] | None:
    """Every path git tracks, relative to ROOT, or None when git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _walk() -> list[str]:
    found = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            found.append(Path(base, name).relative_to(ROOT).as_posix())
    return found


def _paths() -> list[str]:
    tracked = _tracked()
    return sorted(tracked if tracked is not None else _walk())


def _files():
    """(relative path, text) for every tracked text file except this one."""
    for rel in _paths():
        p = ROOT / rel
        if not p.is_file() or p.resolve() == SELF:
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        yield rel, raw.decode("utf-8", errors="replace")


def _lines():
    for rel, text in _files():
        for i, line in enumerate(text.splitlines(), 1):
            yield rel, i, line


def _runs(token: str):
    """The token, and every run of its hyphen pieces: 'a-b-c' gives a, b, c,
    a-b, b-c and a-b-c, so a two-piece name inside a longer token still hits."""
    pieces = token.split("-")
    for start in range(len(pieces)):
        for end in range(start + 1, len(pieces) + 1):
            yield "-".join(pieces[start:end])


def _private_hit(text: str, hashes: set[str]) -> bool:
    for tok in TOKEN.findall(text.lower()):
        if any(_sha(run) in hashes for run in _runs(tok)):
            return True
    return False


def _id_findings(line: str) -> list[str]:
    bad = []
    for m in UUID.finditer(line):
        if m.group(0).lower() not in SYNTHETIC_UUIDS:
            bad.append("uuid " + m.group(0)[:8] + "...")
    for rx, what in ((THREAD_ID, "thread id"), (RESUME_KEY, "resume key"), (BEARER, "bearer")):
        for m in rx.finditer(line):
            if m.group(0) not in SYNTHETIC_CONVOY_IDS:
                bad.append(what + " " + m.group(0)[:8] + "...")
    for m in NEURON_ID.finditer(line):
        if m.group(0) not in SYNTHETIC_NEURON_IDS:
            bad.append("neuron id " + m.group(0))
    return bad


class PublicTreeCarriesNoPrivateNames(unittest.TestCase):
    def test_the_scan_covers_every_tracked_text_file(self):
        # A scope that silently narrows is the failure this file exists to
        # prevent, so the scope is asserted, not assumed.
        scanned = {rel for rel, _ in _files()}
        self.assertGreater(len(scanned), 150, "the tracked-file list came back nearly empty")
        for must in ("README.md", "SPEC.md", "SECURITY_GATES.md", "pyproject.toml", ".gitignore"):
            self.assertIn(must, scanned, must)
        for prefix in ("scripts/", "test/fakes/", "docs/", "src/"):
            self.assertTrue(any(rel.startswith(prefix) for rel in scanned), prefix)

    def test_the_detectors_fire_on_synthetic_bad_input(self):
        # Built at run time so no literal real-looking value sits in this file.
        uuid = "-".join(["1a2b3c4d", "5e6f", "7a8b", "9c0d", "1e2f3a4b5c6d"])
        self.assertTrue(_id_findings("resume " + uuid))
        self.assertTrue(_id_findings("cvy_" + "Ab9-" * 6))
        self.assertTrue(_id_findings("cvr_" + "0123456789abcdef"))
        self.assertTrue(_id_findings("cvb_" + "x" * 43))
        self.assertTrue(_id_findings("send --id n" + "1a2b3c"))
        self.assertFalse(_id_findings("no ids here, and " + "n000000" + " is synthetic"))
        probe = {_sha("zq-probe")}
        self.assertTrue(_private_hit("path/to/zq-probe-2/file", probe))
        self.assertTrue(_private_hit("a zq-probe here", probe))
        self.assertFalse(_private_hit("zqprobe is one word", probe))
        self.assertTrue(CONVERSATION.search("Claude" + "-Session: x"))
        self.assertFalse(CONVERSATION.search("<dry-claude-session>"))

    def test_no_home_directory_of_a_real_user(self):
        bad = []
        for rel, i, line in _lines():
            for rx in (HOME_DIR, HOME_DIR_POSIX):
                for m in rx.finditer(line):
                    if m.group(1).lower() not in ALLOWED_HOME:
                        bad.append(f"{rel}:{i}: home directory of {m.group(1)!r}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_real_email_addresses(self):
        bad = []
        for rel, i, line in _lines():
            if "@unittest" in line or "@mock" in line or "@property" in line:
                continue
            for m in EMAIL.finditer(line):
                domain = m.group(1).lower()
                if domain not in ALLOWED_EMAIL_DOMAINS and not domain.endswith(".test"):
                    bad.append(f"{rel}:{i}: email at {domain}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_vendor_session_ids_or_convoy_ids_anywhere(self):
        bad = []
        for rel, i, line in _lines():
            for finding in _id_findings(line):
                bad.append(f"{rel}:{i}: {finding}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_private_names_by_hashed_token(self):
        bad = []
        for rel in _paths():
            if _private_hit(rel, PRIVATE_TOKEN_HASHES):
                bad.append(f"{rel}: private name in the path (hash match)")
        for rel, i, line in _lines():
            if _private_hit(line, PRIVATE_TOKEN_HASHES):
                bad.append(f"{rel}:{i}: private name (hash match)")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_conversation_links_or_session_trailers(self):
        bad = [f"{rel}:{i}: conversation link or session trailer"
               for rel, i, line in _lines() if CONVERSATION.search(line)]
        self.assertEqual(bad, [], "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
