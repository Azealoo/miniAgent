"""
Debug endpoints for operational introspection.

GET /api/debug/failed-distillations — session ids whose post-session
distillation raised. The list is in-memory only (process-local) and is
cleared on restart. Intended for manual inspection during development;
persistence / retry is out of scope.
"""
from fastapi import APIRouter, Request

from access_control import require_inspection_access

router = APIRouter()


@router.get("/debug/failed-distillations")
def list_failed_distillations(request: Request = None):
    require_inspection_access(request)
    from runtime.memory_distillation import get_failed_distillations

    session_ids = get_failed_distillations()
    return {
        "session_ids": session_ids,
        "count": len(session_ids),
    }
