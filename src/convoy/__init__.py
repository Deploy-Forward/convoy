from .index import home_dir as _home_dir

# Every Convoy import passes here. In a direct unittest discovery without
# PYTHONPATH, package-level test guards may never load; establish an isolated
# home before modules with their own home accessors can read or write it.
_home_dir()

from .layer import feed_path, feed_since, hook
from .context import pack, stdin_for
from .registry import lookup, parse_session_id, register
