"""Opt-in vendor harness install. BYO CLI. Never a wrap. Never an invented affiliate URL."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import urlparse

from .bringup import ensure_interactive_path

Installer = Callable[[str], dict[str, Any]]

HARNESSES: dict[str, dict[str, str]] = {
    "grok": {
        "page": "https://x.ai/cli",
        "host": "x.ai",
        "posix_url": "https://x.ai/cli/install.sh",
        "posix_cmd": "curl -fsSL https://x.ai/cli/install.sh | bash",
        "windows_url": "https://x.ai/cli/install.ps1",
        "windows_cmd": "irm https://x.ai/cli/install.ps1 | iex",
    },
    "claude": {
        "page": "https://code.claude.com/docs/en/install",
        "host": "claude.ai",
        "posix_url": "https://claude.ai/install.sh",
        "posix_cmd": "curl -fsSL https://claude.ai/install.sh | bash",
        "windows_url": "https://claude.ai/install.ps1",
        "windows_cmd": "irm https://claude.ai/install.ps1 | iex",
    },
    "codex": {
        "page": "https://github.com/OpenAI/codex",
        "host": "chatgpt.com",
        "posix_url": "https://chatgpt.com/codex/install.sh",
        "posix_cmd": "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
    },
    "cursor-agent": {
        "page": "https://cursor.com/docs/cli/installation",
        "host": "cursor.com",
        "posix_url": "https://cursor.com/install",
        "posix_cmd": "curl https://cursor.com/install -fsS | bash",
        "windows_url": "https://cursor.com/install?win32=true",
        "windows_cmd": "irm 'https://cursor.com/install?win32=true' | iex",
    },
    "agy": {
        "page": "https://www.antigravity.google/docs/cli/install/",
        "host": "antigravity.google",
        "posix_url": "https://antigravity.google/cli/install.sh",
        "posix_cmd": "curl -fsSL https://antigravity.google/cli/install.sh | bash",
        "windows_url": "https://antigravity.google/cli/install.ps1",
        "windows_cmd": "irm https://antigravity.google/cli/install.ps1 | iex",
    },
}

ALLOWED_HOSTS = frozenset(row["host"] for row in HARNESSES.values())

_REFUSE = frozenset({
    "gemini",
    "gemini-cli",
    "grok-cli",
    "ultracode-shim",
    "ola-brain",
    "claude-grok",
    "claude-grok-4-6",
})


def _host_ok(url: str, host: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("https",):
        return False
    return parsed.hostname == host and host in ALLOWED_HOSTS


def _which(to: str) -> str | None:
    name = "agent" if to == "cursor-agent" else to
    found = shutil.which(name)
    if found:
        return found
    if to == "cursor-agent":
        return shutil.which("cursor-agent")
    if os.name == "nt":
        return shutil.which(name + ".exe")
    return None


def vendor_card(to: str, *, windows: bool | None = None) -> dict[str, Any]:
    key = str(to or "").strip().lower()
    if key in _REFUSE or key not in HARNESSES:
        return {
            "ok": False,
            "to": key or None,
            "ran": False,
            "error": "refuse unknown or wrapped harness",
        }
    spec = HARNESSES[key]
    win = os.name == "nt" if windows is None else bool(windows)
    url_key = "windows_url" if win else "posix_url"
    cmd_key = "windows_cmd" if win else "posix_cmd"
    url = spec.get(url_key) or spec.get("posix_url")
    cmd = spec.get(cmd_key) or spec.get("posix_cmd")
    if not url or not _host_ok(url, spec["host"]):
        return {
            "ok": False,
            "to": key,
            "ran": False,
            "page": spec["page"],
            "error": "refuse non-vendor host",
        }
    present = _which(key)
    return {
        "ok": True,
        "to": key,
        "page": spec["page"],
        "host": spec["host"],
        "url": url,
        "command": cmd,
        "present": present is not None,
        "bin": present,
        "ran": False,
        "affiliate": None,
    }


def default_installer(url: str) -> dict[str, Any]:
    """Fetch the vendor script over https and run it with bash/sh. URL must already be host-ok."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        return {"ok": False, "error": "refuse non-vendor host", "url": url}
    curl = subprocess.run(
        ["curl", "-fsSL", url],
        check=False,
        capture_output=True,
    )
    if curl.returncode != 0:
        err = (curl.stderr or b"").decode("utf-8", "replace")
        return {"ok": False, "error": "curl failed", "detail": err, "url": url}
    shell = "sh" if "/codex/" in parsed.path else "bash"
    run = subprocess.run(
        [shell, "-s"],
        input=curl.stdout,
        check=False,
        capture_output=True,
    )
    if run.returncode != 0:
        err = (run.stderr or b"").decode("utf-8", "replace")
        return {"ok": False, "error": "installer failed", "detail": err, "url": url}
    return {"ok": True, "url": url}


def install(
    to: str,
    *,
    dry_run: bool = True,
    opt_in: bool = False,
    installer: Installer | None = None,
    windows: bool | None = None,
) -> dict[str, Any]:
    """Show or run the vendor installer. dry_run defaults true. Live needs opt_in.

    Does not log the user in. Does not invent an affiliate URL.
    After a live install, writes the interactive bash PATH block.
    """
    card = vendor_card(to, windows=windows)
    card["dry_run"] = bool(dry_run)
    card["opt_in"] = bool(opt_in)
    if not card.get("ok"):
        return card
    if dry_run:
        return card
    if not opt_in:
        card["ok"] = False
        card["error"] = "opt_in required"
        return card
    run = (installer or default_installer)(str(card["url"]))
    card["install"] = {k: run.get(k) for k in ("ok", "error", "url") if k in run}
    if not run.get("ok"):
        card["ok"] = False
        card["error"] = str(run.get("error") or "installer failed")
        return card
    path_card = ensure_interactive_path()
    card["path"] = path_card
    card["ran"] = True
    present = _which(str(card["to"]))
    card["present"] = present is not None
    card["bin"] = present
    return card
