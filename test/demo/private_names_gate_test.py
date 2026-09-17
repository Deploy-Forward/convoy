"""Public-tree gate: no private names, home paths, real emails, vendor session
ids or live thread ids in anything this repository publishes.

Found 2026-09-17 by an audit of the public repo: two code comments cited a
private client repository by name, five docs carried the operator's home
directory, two handoffs carried a live thread id and a private checkout name,
an audit table carried two vendor session ids. None is a credential; all are
names that do not belong in a public tree. A rule in a document does not hold;
this test does.

Private names are matched as hashed tokens so the denylist itself publishes
nothing. Generic shapes (home directories, emails, UUIDs, thread ids) are
matched directly. Placeholders are allowed: `C:\\Users\\<user>` or `C:\\Users\\dev`,
`*@example.test`, `*@convoy.test`, the all-zero UUID.
"""
from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ("src", "docs", "test", "plugin", "plugins", "skills")
ROOT_FILES = ("README.md", "SPEC.md", "CANON.md", "CONTRIBUTING.md", "SECURITY.md", "wrangler.jsonc", "workers-site.mjs")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".jsonc", ".mjs", ".js", ".html", ".css", ".toml", ".yaml", ".yml", ".ps1", ".cmd", ".sh"}
SELF = Path(__file__).resolve()

# sha256 of each lowercase token that must not appear as a word or hyphen-piece
# (client and project names, a private checkout name, a personal mailbox, a
# colleague's first name). Hashed so this file publishes none of them.
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
}


def _sha(token: str) -> str:
    return hashlib.sha256(token.lower().encode("utf-8")).hexdigest()


HOME_DIR = re.compile(r"(?i)[a-z]:\\{1,2}Users\\{1,2}([A-Za-z0-9_.-]+)")
HOME_DIR_POSIX = re.compile(r"(?:/Users|/home)/([A-Za-z0-9_.-]+)")
ALLOWED_HOME = {"<user>", "dev", "user", "you", "public", "default", "demo", "x", "m"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[a-z]{2,})")
ALLOWED_EMAIL_DOMAINS = {"example.test", "convoy.test", "example.com", "users.noreply.github.com", "anthropic.com", "github.com"}
UUID = re.compile(r"\b([0-9a-f]{8})-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
THREAD_ID = re.compile(r"\bcvy_[A-Za-z0-9]{20,}\b")
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES and "__pycache__" not in p.parts and p.resolve() != SELF:
                yield p
    for name in ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            yield p


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


class PublicTreeCarriesNoPrivateNames(unittest.TestCase):
    def test_no_home_directory_of_a_real_user(self):
        bad = []
        for p in _files():
            for i, line in enumerate(_read(p).splitlines(), 1):
                for rx in (HOME_DIR, HOME_DIR_POSIX):
                    for m in rx.finditer(line):
                        if m.group(1).lower() not in ALLOWED_HOME:
                            bad.append(f"{p.relative_to(ROOT)}:{i}: home directory of {m.group(1)!r}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_real_email_addresses(self):
        bad = []
        for p in _files():
            for i, line in enumerate(_read(p).splitlines(), 1):
                if "@unittest" in line or "@mock" in line or "@property" in line:
                    continue
                for m in EMAIL.finditer(line):
                    domain = m.group(1).lower()
                    if domain not in ALLOWED_EMAIL_DOMAINS and not domain.endswith(".test"):
                        bad.append(f"{p.relative_to(ROOT)}:{i}: email at {domain}")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_docs_carry_no_vendor_session_ids_or_live_thread_ids(self):
        bad = []
        for p in _files():
            if "docs" not in p.relative_to(ROOT).parts:
                continue
            for i, line in enumerate(_read(p).splitlines(), 1):
                for m in UUID.finditer(line):
                    if m.group(1) != "00000000":
                        bad.append(f"{p.relative_to(ROOT)}:{i}: uuid {m.group(1)}…")
                if THREAD_ID.search(line):
                    bad.append(f"{p.relative_to(ROOT)}:{i}: live thread id")
        self.assertEqual(bad, [], "\n".join(bad))

    def test_no_private_names_by_hashed_token(self):
        bad = []
        for p in _files():
            for i, line in enumerate(_read(p).splitlines(), 1):
                low = line.lower()
                for tok in TOKEN.findall(low):
                    pieces = {tok, *tok.split("-")}
                    if any(_sha(x) in PRIVATE_TOKEN_HASHES for x in pieces):
                        bad.append(f"{p.relative_to(ROOT)}:{i}: private name (hash match)")
                        break
        self.assertEqual(bad, [], "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
