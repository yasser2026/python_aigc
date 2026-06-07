"""FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import novels, portfolio, projects
from app.core.config_loader import get_root, load_config
from app.services import knowledge_graph, vector_store


def _print_startup_connectivity() -> None:
    """Print Milvus / Neo4j connectivity at startup (stdout)."""
    milvus_cfg = load_config("milvus")
    neo4j_cfg = load_config("neo4j")
    pipeline_cfg = load_config("pipeline")
    kg_pipeline = (pipeline_cfg.get("knowledge_graph") or {}).get("enabled", True)

    milvus_enabled = bool(milvus_cfg.get("enabled", False))
    if milvus_enabled:
        milvus_ok = vector_store.ping()
        fb = "JSON fallback" if milvus_cfg.get("fallback_to_json") else "no fallback"
        status = "连通" if milvus_ok else f"未连通 ({fb})"
        print(f"[startup] 向量库 Milvus: 已启用, {status}", flush=True)
    else:
        print("[startup] 向量库 Milvus: 未启用", flush=True)

    neo4j_enabled = bool(neo4j_cfg.get("enabled", False))
    if neo4j_enabled:
        neo4j_ok = knowledge_graph.ping_server()
        fb = "JSON fallback" if neo4j_cfg.get("fallback_to_json") else "no fallback"
        status = "连通" if neo4j_ok else f"未连通 ({fb})"
        pipeline_note = "" if kg_pipeline else ", 流水线未启用知识图谱"
        print(f"[startup] 知识图谱 Neo4j: 已启用, {status}{pipeline_note}", flush=True)
    else:
        print("[startup] 知识图谱 Neo4j: 未启用", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(get_root() / ".env")
    load_config("app", reload=True)
    _print_startup_connectivity()
    yield


app = FastAPI(
    title="Novel to Short Video",
    description="小说转短视频 AIGC 流水线",
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

app.include_router(projects.router, prefix="/projects", tags=["projects"])
app.include_router(novels.router, prefix="/novels", tags=["novels"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(projects.health_router, tags=["health"])


def run() -> None:
    cfg = load_config("app")
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=cfg.get("host", "0.0.0.0"),
        port=cfg.get("port", 8000),
        reload=False,
    )


if __name__ == "__main__":
    run()
