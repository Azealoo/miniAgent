"""
RAG mode configuration.

GET /api/config/rag-mode
PUT /api/config/rag-mode   body: {"enabled": true/false}
GET /api/config/production-hardening
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel

from access_control import require_admin_access
import config as cfg

router = APIRouter()


@router.get("/config/rag-mode")
def get_rag_mode(request: Request):
    require_admin_access(request)
    return {"rag_mode": cfg.get_rag_mode()}


@router.get("/config/production-hardening")
def get_production_hardening(request: Request):
    require_admin_access(request)
    return cfg.get_production_hardening_policy().model_dump(mode="json")


class RagModeRequest(BaseModel):
    enabled: bool


@router.put("/config/rag-mode")
def set_rag_mode(body: RagModeRequest, request: Request):
    require_admin_access(request)
    cfg.set_rag_mode(body.enabled)
    return {"rag_mode": body.enabled}
