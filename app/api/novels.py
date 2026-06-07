"""Novel-level metadata and knowledge graph API."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.schemas import NovelMetaResponse
from app.services import knowledge_graph, novel_meta

router = APIRouter()


@router.get("/{novel_name}/meta", response_model=NovelMetaResponse)
def get_novel_meta(novel_name: str) -> NovelMetaResponse:
    data = novel_meta.get_novel_meta_response(novel_name)
    return NovelMetaResponse(**data)


@router.get("/{novel_name}/graph")
def get_novel_graph(novel_name: str) -> dict:
    """Return full knowledge graph snapshot (Neo4j or JSON fallback)."""
    return knowledge_graph.get_graph_snapshot(novel_name)


@router.get("/{novel_name}/graph/characters/{char_id}/relations")
def get_character_relations(novel_name: str, char_id: str) -> dict:
    relations = knowledge_graph.get_character_relations_json(novel_name, char_id)
    return {"novel_name": novel_name, "character_id": char_id, "relations": relations}


@router.post("/{novel_name}/graph/backfill")
def backfill_novel_graph(novel_name: str) -> dict:
    """Rebuild graph from existing episode scenes.json files."""
    count = knowledge_graph.backfill_novel(novel_name)
    return {"novel_name": novel_name, "episodes_backfilled": count}
