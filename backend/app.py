"""
miniOpenClaw backend entry point.

Run with:
    cd backend
    uvicorn app:app --port 8002 --host 0.0.0.0 --reload
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure backend/ is on the Python path when run via uvicorn
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()  # Load .env before any other imports that read env vars

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).parent


# ------------------------------------------------------------------ #
# Lifespan                                                             #
# ------------------------------------------------------------------ #


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Configure LlamaIndex embedding model ──────────────────────
    try:
        from llama_index.core import Settings
        from llama_index.embeddings.openai import OpenAIEmbedding

        Settings.embed_model = OpenAIEmbedding(
            model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            api_base=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        Settings.llm = None  # Let LangChain manage the LLM
    except Exception as exc:
        print(f"[WARNING] LlamaIndex embedding setup failed: {exc}")

    # ── 1. Scan skills → generate SKILLS_SNAPSHOT.md ──────────────
    from tools.skills_scanner import scan_skills

    scan_skills(BASE_DIR)
    print("[startup] Skills scanned → SKILLS_SNAPSHOT.md generated")

    # ── 2. Initialise AgentManager ─────────────────────────────────
    from graph.agent import agent_manager

    agent_manager.initialize(BASE_DIR)
    print("[startup] AgentManager initialised")

    # ── 3. Build MEMORY.md vector index ───────────────────────────
    try:
        agent_manager.memory_indexer.rebuild_index()
        print("[startup] Memory index built")
    except Exception as exc:
        print(f"[WARNING] Memory index build failed (non-fatal): {exc}")

    yield
    # (shutdown cleanup goes here if needed)


# ------------------------------------------------------------------ #
# App                                                                  #
# ------------------------------------------------------------------ #

app = FastAPI(
    title="miniOpenClaw",
    description="Lightweight, transparent AI Agent system",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ───────────────────────────────────────────────
from api.chat import router as chat_router
from api.compress import router as compress_router
from api.config_api import router as config_router
from api.files import router as files_router
from api.sessions import router as sessions_router
from api.tokens import router as tokens_router

app.include_router(chat_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(tokens_router, prefix="/api")
app.include_router(compress_router, prefix="/api")
app.include_router(config_router, prefix="/api")


@app.get("/")
def health():
    return {"status": "ok", "service": "miniOpenClaw"}
