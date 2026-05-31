"""DashScope text embeddings for Milvus."""

from __future__ import annotations

import os
import re

import httpx

from app.core.config_loader import load_config

_ENV = re.compile(r"\$\{([^}]+)\}")


def _api_key(cfg: dict) -> str:
    raw = str(cfg.get("api_key", "${DASHSCOPE_API_KEY}"))
    m = _ENV.search(raw)
    env_name = m.group(1) if m else "DASHSCOPE_API_KEY"
    key = os.getenv(env_name, "")
    if not key:
        raise ValueError(f"{env_name} not set in .env")
    return key


def _embedding_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/services/embeddings/text-embedding/text-embedding"


def embed_texts(texts: list[str], *, text_type: str = "document") -> list[list[float]]:
    if not texts:
        return []
    cfg = load_config("milvus")
    dim = int(cfg.get("dimension", 1024))
    body = {
        "model": cfg.get("embedding_model", "text-embedding-v3"),
        "input": {"texts": texts},
        "parameters": {
            "dimension": dim,
            "text_type": text_type,
        },
    }
    url = _embedding_url(cfg.get("embedding_base_url", "https://dashscope.aliyuncs.com/api/v1"))
    headers = {
        "Authorization": f"Bearer {_api_key(cfg)}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code"):
            raise RuntimeError(data.get("message", data))
        output = data.get("output", {})
        embeddings = output.get("embeddings") or []
        vectors: list[list[float]] = []
        for item in sorted(embeddings, key=lambda x: x.get("text_index", 0)):
            vectors.append(item["embedding"])
        if len(vectors) != len(texts):
            raise RuntimeError(f"Embedding count mismatch: {len(vectors)} vs {len(texts)}")
        return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text], text_type="query")[0]
