"""Milvus vector store for novel characters & locations (JSON fallback)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.config_loader import get_root, load_config
from app.core.paths import sanitize_novel_dir
from app.services import embeddings

logger = logging.getLogger(__name__)

_FALLBACK_NAME = "milvus_fallback.json"


def _cfg() -> dict:
    return load_config("milvus")


def is_enabled() -> bool:
    return bool(_cfg().get("enabled", False))


def _pk(novel_name: str, entity_type: str, entity_id: str) -> str:
    novel = sanitize_novel_dir(novel_name)
    return f"{novel}::{entity_type}::{entity_id}"


def _fallback_path() -> Path:
    app = load_config("app")
    return get_root() / app.get("data_root", "data") / _FALLBACK_NAME


def _load_fallback() -> dict[str, dict]:
    path = _fallback_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_fallback(data: dict[str, dict]) -> None:
    path = _fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class _MilvusBackend:
    def __init__(self) -> None:
        self._collection = None
        self._ready = False

    def _ensure(self) -> bool:
        if self._ready:
            return self._collection is not None
        cfg = _cfg()
        try:
            from pymilvus import (
                Collection,
                CollectionSchema,
                DataType,
                FieldSchema,
                connections,
                utility,
            )

            uri = cfg.get("uri", "http://127.0.0.1:19530")
            connections.connect(alias="default", uri=uri)
            name = cfg.get("collection", "aigc_novel_entities")
            dim = int(cfg.get("dimension", 1024))

            if not utility.has_collection(name):
                fields = [
                    FieldSchema(
                        name="pk",
                        dtype=DataType.VARCHAR,
                        is_primary=True,
                        max_length=256,
                    ),
                    FieldSchema(name="novel_name", dtype=DataType.VARCHAR, max_length=200),
                    FieldSchema(name="entity_type", dtype=DataType.VARCHAR, max_length=32),
                    FieldSchema(name="entity_id", dtype=DataType.VARCHAR, max_length=64),
                    FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=200),
                    FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
                    FieldSchema(name="ref_image", dtype=DataType.VARCHAR, max_length=512),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
                ]
                schema = CollectionSchema(fields, description="AIGC novel entities")
                self._collection = Collection(name, schema)
                index_params = {
                    "metric_type": "COSINE",
                    "index_type": "AUTOINDEX",
                    "params": {},
                }
                self._collection.create_index("embedding", index_params)
            else:
                self._collection = Collection(name)
            self._collection.load()
            self._ready = True
            logger.info("Milvus connected: %s", name)
            return True
        except Exception as e:
            logger.warning("Milvus unavailable, using JSON fallback: %s", e)
            self._collection = None
            self._ready = True
            return False

    def upsert(
        self,
        novel_name: str,
        entity_type: str,
        entity_id: str,
        name: str,
        description: str,
        ref_image: str | None,
        vector: list[float],
    ) -> None:
        if not self._ensure() or self._collection is None:
            return
        pk = _pk(novel_name, entity_type, entity_id)
        novel = sanitize_novel_dir(novel_name)
        self._collection.delete(expr=f'pk == "{pk}"')
        self._collection.insert(
            [
                [pk],
                [novel],
                [entity_type],
                [entity_id],
                [name[:200]],
                [description[:4096]],
                [(ref_image or "")[:512]],
                [vector],
            ]
        )
        self._collection.flush()

    def search(
        self,
        novel_name: str,
        query_vector: list[float],
        entity_type: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if not self._ensure() or self._collection is None:
            return []
        novel = sanitize_novel_dir(novel_name)
        expr = f'novel_name == "{novel}" && entity_type == "{entity_type}"'
        results = self._collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=top_k,
            expr=expr,
            output_fields=["entity_id", "name", "description", "ref_image"],
        )
        hits: list[dict[str, Any]] = []
        for group in results:
            for hit in group:
                hits.append(
                    {
                        "entity_id": hit.entity.get("entity_id"),
                        "name": hit.entity.get("name"),
                        "description": hit.entity.get("description"),
                        "ref_image": hit.entity.get("ref_image") or None,
                        "score": float(hit.score),
                    }
                )
        return hits


_backend: _MilvusBackend | None = None


def _get_backend() -> _MilvusBackend:
    global _backend
    if _backend is None:
        _backend = _MilvusBackend()
    return _backend


def upsert_entity(
    novel_name: str,
    entity_type: str,
    entity_id: str,
    name: str,
    description: str,
    ref_image: str | None = None,
) -> None:
    """Index character/location profile (Milvus + JSON fallback)."""
    if not description.strip():
        return
    text = f"{name}\n{description}"
    pk = _pk(novel_name, entity_type, entity_id)

    try:
        vector = embeddings.embed_texts([text], text_type="document")[0]
    except Exception as e:
        logger.warning("Embedding failed for %s: %s", pk, e)
        vector = []

    record = {
        "novel_name": sanitize_novel_dir(novel_name),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "name": name,
        "description": description,
        "ref_image": ref_image,
        "embedding": vector,
    }
    fb = _load_fallback()
    fb[pk] = record
    _save_fallback(fb)

    if not is_enabled() or not vector:
        return
    try:
        _get_backend().upsert(
            novel_name, entity_type, entity_id, name, description, ref_image, vector
        )
    except Exception as e:
        logger.warning("Milvus upsert failed for %s: %s", pk, e)


def ping() -> bool:
    """True if Milvus is enabled and reachable."""
    if not is_enabled():
        return False
    try:
        return _get_backend()._ensure()
    except Exception:
        return False


def search_entities(
    novel_name: str,
    query_text: str,
    entity_type: str,
    *,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    cfg = _cfg()
    k = top_k or int(cfg.get("search_top_k", 3))
    if not query_text.strip():
        return []

    try:
        qvec = embeddings.embed_query(query_text)
    except Exception as e:
        logger.warning("Query embedding failed: %s", e)
        qvec = []

    hits: list[dict[str, Any]] = []
    if is_enabled() and qvec:
        try:
            hits = _get_backend().search(novel_name, qvec, entity_type, k)
        except Exception as e:
            logger.warning("Milvus search failed: %s", e)

    if hits:
        return hits

    if not cfg.get("fallback_to_json", True) or not qvec:
        return _search_fallback_no_vector(novel_name, entity_type, query_text, k)

    return _search_fallback_vector(novel_name, entity_type, qvec, k)


def _search_fallback_vector(
    novel_name: str,
    entity_type: str,
    qvec: list[float],
    top_k: int,
) -> list[dict[str, Any]]:
    novel = sanitize_novel_dir(novel_name)
    scored: list[tuple[float, dict]] = []
    for rec in _load_fallback().values():
        if rec.get("novel_name") != novel or rec.get("entity_type") != entity_type:
            continue
        emb = rec.get("embedding") or []
        if not emb:
            continue
        scored.append((_cosine(qvec, emb), rec))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "entity_id": r["entity_id"],
            "name": r["name"],
            "description": r["description"],
            "ref_image": r.get("ref_image"),
            "score": s,
        }
        for s, r in scored[:top_k]
    ]


def _search_fallback_no_vector(
    novel_name: str,
    entity_type: str,
    query_text: str,
    top_k: int,
) -> list[dict[str, Any]]:
    novel = sanitize_novel_dir(novel_name)
    q = query_text.lower()
    out: list[dict[str, Any]] = []
    for rec in _load_fallback().values():
        if rec.get("novel_name") != novel or rec.get("entity_type") != entity_type:
            continue
        blob = f"{rec.get('name', '')} {rec.get('description', '')}".lower()
        if q in blob or rec.get("name", "").lower() in q:
            out.append(
                {
                    "entity_id": rec["entity_id"],
                    "name": rec["name"],
                    "description": rec["description"],
                    "ref_image": rec.get("ref_image"),
                    "score": 0.5,
                }
            )
    return out[:top_k]
