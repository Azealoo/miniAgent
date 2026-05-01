"""Backward-compatible facade for the ``graph.session`` package.

The session implementation has moved into ``graph.session`` (split across
``session_schema``, ``session_normalizer``, ``session_store``, and
``session_archive``). Existing callers can keep importing from
``graph.session_manager``; this shim re-exports the public names until
migration completes — plan to remove it after one release cycle.
"""

from graph.session import (
    FrozenSessionPrefix,
    SESSION_SCHEMA_VERSION,
    SessionCorruptError,
    SessionManager,
    _validate_session_id,
)

__all__ = [
    "FrozenSessionPrefix",
    "SessionManager",
    "SESSION_SCHEMA_VERSION",
    "SessionCorruptError",
    "_validate_session_id",
]
