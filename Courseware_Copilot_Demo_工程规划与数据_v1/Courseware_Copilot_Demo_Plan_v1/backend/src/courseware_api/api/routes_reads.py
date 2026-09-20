"""F00 读路由：正式 Deck 与证据原文（只读、零模型调用、response_model 契约化）。"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from courseware_api.dependencies import get_read_service
from courseware_core.models import DeckSpec, DocumentChunk
from courseware_core.services.read_service import ProjectReadService

router = APIRouter()


@router.get("/projects/{project_id}/deck", response_model=DeckSpec)
def get_deck(
    project_id: str,
    version: Optional[int] = Query(default=None),
    service: ProjectReadService = Depends(get_read_service),
) -> DeckSpec:
    return service.get_deck(project_id, version)


@router.get("/projects/{project_id}/evidence/{chunk_id}", response_model=DocumentChunk)
def get_evidence(
    project_id: str,
    chunk_id: str,
    corpus_revision: int = Query(..., minimum=1),
    service: ProjectReadService = Depends(get_read_service),
) -> DocumentChunk:
    return service.get_evidence(project_id, chunk_id, corpus_revision)
