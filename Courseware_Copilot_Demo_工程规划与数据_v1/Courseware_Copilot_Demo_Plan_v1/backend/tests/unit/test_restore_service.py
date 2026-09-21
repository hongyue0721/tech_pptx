"""T12 loop②：RestoreService 单元测试（先红后绿）。"""

import copy

import pytest

from courseware_core.errors import (
    CorpusChanged,
    DeckNotFound,
    ProjectBusy,
    ProjectNotFound,
    VersionConflict,
)
from courseware_core.models import DeckSpec, RestoreRequest
from courseware_core.services.restore_service import RestoreService
from courseware_core.storage.version_repository import (
    VersionRepository,
    semantic_hash,
)

COURSE = {
    "topic": "STM32 中断机制",
    "audience": "大二学生",
    "duration_minutes": 45,
    "goals": ["理解 NVIC"],
    "target_slides": 8,
}
DECK_BASE = {
    "schema_version": "1.0.0",
    "project_id": "prj_001",
    "version": 1,
    "corpus_revision": 1,
    "course": COURSE,
    "claims": [],
    "slides": [],
}


def deck(version: int, text: str, corpus_revision: int = 1) -> DeckSpec:
    payload = copy.deepcopy(DECK_BASE)
    payload.update(version=version, corpus_revision=corpus_revision)
    payload["slides"] = [
        {
            "id": "sld_001",
            "title": f"页 {text}",
            "layout": "title",
            "blocks": [{"type": "teaching", "text": text}],
        }
    ]
    return DeckSpec(**payload)


def restore_request(target: int, base: int, corpus: int = 1) -> RestoreRequest:
    return RestoreRequest(
        target_version=target,
        base_version=base,
        corpus_revision=corpus,
        acknowledged=True,
    )


@pytest.fixture()
def seeded(conn, insert_project):
    insert_project("prj_001", current_version=0, corpus_revision=1)
    versions = VersionRepository(conn)
    versions.commit_version(
        "prj_001", deck(1, "one"), expected_base_version=0, expected_corpus_revision=1
    )
    versions.commit_version(
        "prj_001", deck(2, "two"), expected_base_version=1, expected_corpus_revision=1
    )
    return versions


@pytest.fixture()
def service(conn):
    return RestoreService(conn)


def test_restore_happy_path_creates_new_version_from_target(
    service, seeded, project_columns
):
    result = service.restore("prj_001", restore_request(target=1, base=2))
    assert result.version == 3
    assert result.parent_version == 2
    assert result.restored_from == 1
    assert project_columns("prj_001")["current_version"] == 3
    restored = seeded.get_deck("prj_001", 3)
    assert semantic_hash(restored) == semantic_hash(seeded.get_deck("prj_001", 1))


def test_restore_keeps_history_versions_immutable(service, seeded):
    before_v2 = seeded.get_deck("prj_001", 2)
    service.restore("prj_001", restore_request(target=1, base=2))
    assert seeded.get_deck("prj_001", 2) == before_v2
    assert seeded.get_version("prj_001", 2).restored_from is None


def test_restore_unknown_project_raises(service):
    with pytest.raises(ProjectNotFound):
        service.restore("prj_missing", restore_request(target=1, base=1))


def test_restore_missing_target_raises(service, seeded):
    with pytest.raises(DeckNotFound):
        service.restore("prj_001", restore_request(target=9, base=2))


def test_restore_stale_base_raises_version_conflict(service, seeded, project_columns):
    with pytest.raises(VersionConflict):
        service.restore("prj_001", restore_request(target=1, base=1))
    assert project_columns("prj_001")["current_version"] == 2


def test_restore_across_corpus_rejected(service, seeded, conn):
    with conn:
        conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id = 'prj_001'")
    with pytest.raises(CorpusChanged):
        service.restore("prj_001", restore_request(target=1, base=2, corpus=2))


def test_restore_with_active_job_raises_project_busy(service, seeded, conn, project_columns):
    with conn:
        conn.execute(
            "UPDATE projects SET active_job_id = 'job_001' WHERE id = 'prj_001'"
        )
    with pytest.raises(ProjectBusy):
        service.restore("prj_001", restore_request(target=1, base=2))
    assert project_columns("prj_001")["current_version"] == 2
