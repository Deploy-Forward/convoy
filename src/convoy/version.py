"""Which Convoy is running: its version, the executable, the source it imported, and whether
that source is an editable install. `convoy --version` prints version_card(); the MCP server's
version starts from package_version().
"""
from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path
from urllib.parse import unquote, urlparse

DIST = "convoy"
_PKG = Path(__file__).resolve().parent


def _checkout_pyproject() -> Path | None:
    """pyproject.toml of the source checkout this package was imported from (src layout), or None
    when the package is installed somewhere else (site-packages)."""
    candidate = _PKG.parents[1] / "pyproject.toml"
    if not candidate.is_file():
        return None
    try:
        import tomllib
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return candidate if (data.get("project") or {}).get("name") == DIST else None


def in_checkout() -> bool:
    return _checkout_pyproject() is not None


def package_version() -> str:
    """The version of the Convoy that is running. Imported from a source checkout, that
    checkout's pyproject.toml is the package metadata: an editable install's recorded metadata is
    frozen at install time and goes stale on the next bump. Installed, it is the distribution's
    metadata. "unknown" when neither can be read, never an invented number."""
    pyproject = _checkout_pyproject()
    if pyproject is not None:
        import tomllib
        version = (tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project") or {}).get("version")
        if isinstance(version, str) and version:
            return version
    try:
        return metadata.version(DIST)
    except metadata.PackageNotFoundError:
        return "unknown"


def _editable() -> bool:
    """True when the installed distribution is an editable install of the very source running."""
    try:
        raw = metadata.distribution(DIST).read_text("direct_url.json")
    except metadata.PackageNotFoundError:
        return False
    try:
        info = json.loads(raw or "{}")
    except ValueError:
        return False
    if not (info.get("dir_info") or {}).get("editable"):
        return False
    url = urlparse(str(info.get("url") or ""))
    path = unquote(url.path)
    if len(path) > 2 and path[0] == "/" and path[2] == ":":   # file:///C:/...
        path = path[1:]
    try:
        return _PKG.is_relative_to(Path(path).resolve())
    except (OSError, ValueError):
        return False


def _executable() -> str:
    """The program that ran: the console script for `convoy`, the interpreter for
    `python -m convoy`."""
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.suffix.lower() != ".py":
        for candidate in (argv0, argv0.with_name(argv0.name + ".exe")):
            if candidate.is_file():
                return str(candidate.resolve())
    return str(Path(sys.executable).resolve()) if sys.executable else str(argv0 or "")


def version_card() -> dict:
    import convoy
    return {
        "version": package_version(),
        "executable": _executable(),
        "source": str(Path(convoy.__file__).resolve()),
        "editable": _editable(),
    }
