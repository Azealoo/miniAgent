"""
RAG mode configuration.

GET /api/config/rag-mode
PUT /api/config/rag-mode   body: {"enabled": true/false}
"""
from fastapi import APIRouter
from pydantic import BaseModel

import config as cfg

router = APIRouter()


@router.get("/config/rag-mode")
def get_rag_mode():
    return {"rag_mode": cfg.get_rag_mode()}


class RagModeRequest(BaseModel):
    enabled: bool


@router.put("/config/rag-mode")
def set_rag_mode(body: RagModeRequest):
    cfg.set_rag_mode(body.enabled)
    return {"rag_mode": body.enabled}
