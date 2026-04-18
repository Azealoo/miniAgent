"""Session subsystem: typed content blocks, disk I/O, and archive lifecycle.

The public ``SessionManager`` and related identifiers are re-exported here so
callers can migrate from ``graph.session_manager`` to ``graph.session`` over
time. ``graph.session_manager`` remains as a thin facade for one release
cycle.
"""

from graph.session.session_archive import SessionManager
from graph.session.session_schema import SESSION_SCHEMA_VERSION, _validate_session_id

__all__ = ["SessionManager", "SESSION_SCHEMA_VERSION", "_validate_session_id"]
