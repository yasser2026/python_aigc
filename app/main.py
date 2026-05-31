"""FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import portfolio, projects
from app.core.config_loader import get_root, load_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(get_root() / ".env")
    load_config("app", reload=True)
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
