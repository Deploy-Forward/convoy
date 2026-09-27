"""resume_first: a neuron is resumable from its first launch, by construction.

Convoy used to wait to be told a session id. A first launch passed none, the
vendor invented one, and Convoy learned it only if something later captured
it - so a pane that died before that capture was unresumable. That is how a
relaunched seat came up with `resume: null`.

Where a harness documents a flag that DICTATES the id of a NEW conversation,
there is nothing to wait for: mint a uuid4, write it on the neuron row before
the body starts, and pass it on argv. Which harnesses those are is a fact
about their --help, so it lives in the harness contract with its evidence
string (`session_id_flag`), never in an `if` on a harness name here.

A harness without such a flag is not a failure and not a silence: the row
records `resume: None` with a `resume_reason` naming what is missing, so a
reader can tell "cannot" from "not yet".
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from .convoy import update_seat
from .harness_contract import canonical_harness_id, session_id_flag

NO_FLAG = "no flag to set a session id at launch; resume waits on a captured id"


def mint_session_id() -> str:
    return str(uuid.uuid4())


def ensure_session_id(root: Path, seat: dict[str, Any], *,
                      mint: Callable[[], Any] = uuid.uuid4) -> dict[str, Any]:
    """Give this neuron an id it can be resumed by, before its body starts.

    Returns the row as it now stands. Idempotent: a row that already carries
    a resume id keeps it, because the id names a conversation that exists.
    """
    session = str(seat.get("session_id") or "").strip()
    if not session:
        raise ValueError("refuse empty session_id")
    existing = seat.get("resume")
    if isinstance(existing, str) and existing.strip():
        return seat
    to = canonical_harness_id(seat.get("to"))
    if not session_id_flag(to):
        if seat.get("resume_reason") == NO_FLAG:
            return seat
        return update_seat(root, session, resume=None, resume_reason=NO_FLAG)
    # resume_minted is the provenance flag the argv builder reads: only an id
    # Convoy minted before the body started names a conversation that does not
    # exist yet, and only such an id may be DECLARED with the session-id flag.
    # A captured id names a conversation that already exists and is resumed.
    return update_seat(root, session, resume=str(mint()), resume_for=to,
                       resume_minted=True, resume_reason=None)
