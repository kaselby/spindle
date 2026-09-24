"""Who is acting: the session (and, optionally, the named agent) behind a `thread` command.

Spindle reads the identifiers hosts already provide, so no host has to learn
Spindle's conventions. The first source that has a value wins:

1. THREAD_SESSION / THREAD_AGENT: set by hand, for anything not listed below.
2. Agent runtimes that run the harness, which know more than the harness does
   (the named agent, not just this conversation). Kiln: KILN_AGENT_ID.
3. The harness session. SPINDLE_HARNESS_SESSION is set by Spindle's own plugins
   (pi and omp don't export their session id; Claude Code does, but the hook
   sets it too so that the innermost harness wins when one runs inside another).
   CLAUDE_CODE_SESSION_ID covers Claude Code sessions where the hook hasn't run.
4. user@host.

To support another host, add a source to HOSTS.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Mapping

Source = Callable[[Mapping[str, str]], "dict[str, str] | None"]


def _explicit(env: Mapping[str, str]) -> dict[str, str] | None:
    session = env.get("THREAD_SESSION")
    if not session:
        return None
    return {"session": session, "agent": env.get("THREAD_AGENT") or session}


def _kiln(env: Mapping[str, str]) -> dict[str, str] | None:
    # Kiln session ids are <agent>-<adjective>-<noun>, e.g. ayin-deep-reach.
    session = env.get("KILN_AGENT_ID")
    if not session:
        return None
    parts = session.rsplit("-", 2)
    return {"session": session, "agent": parts[0] if len(parts) == 3 else session}


def short_session(harness: str, session_id: str) -> str:
    """<harness>-<last 8 hex of the id>. The end, not the start: pi and omp use
    UUIDv7, which begins with a timestamp. The suffix also finds the transcript file."""
    return f"{harness}-{session_id.replace('-', '')[-8:]}"


def _harness(env: Mapping[str, str]) -> dict[str, str] | None:
    session = env.get("SPINDLE_HARNESS_SESSION")
    if not session and env.get("CLAUDE_CODE_SESSION_ID"):
        session = short_session("claude", env["CLAUDE_CODE_SESSION_ID"])
    return {"session": session, "agent": session} if session else None


def _fallback(env: Mapping[str, str]) -> dict[str, str]:
    session = f"{env.get('USER', 'user')}@{socket.gethostname()}"
    return {"session": session, "agent": session}


HOSTS: list[Source] = [_kiln]
SOURCES: list[Source] = [_explicit, *HOSTS, _harness]


def resolve(env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ if env is None else env
    for source in SOURCES:
        found = source(env)
        if found:
            return found
    return _fallback(env)
