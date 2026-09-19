import copy

import pytest

from courseware_core.errors import CorpusChanged, DeckNotFound, VersionConflict
from courseware_core.models import DeckSpec
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
SLIDE = {
    "id": "sld_001",
    "title": "NVIC 优先级分组",
    "layout": "concept",
    "blocks": [{"type": "teaching", "text": "分组决定抢占与子优先级位数。"}],
}
DECK_BASE = {
    "schema_version": "1.0.0",
    "project_id": "prj_001",
    "version": 1,
    "corpus_revision": 1,
    "course": COURSE,
    "claims": [],
    "slides": [SLIDE],
}


def deck(version: int = 1, **overrides) -> DeckSpec:
    payload = copy.deepcopy(DECK_BASE)
    payload.update(overrides)
    return DeckSpec(**payload)


@pytest.fixture()
def repo(conn, insert_project):
    insert_project("prj_001", current_version=0, corpus_revision=1)
    return VersionRepository(conn)


def test_commit_first_version_is_server_authoritative(repo, project_columns):
    result = repo.commit_version(
        "prj_001", deck(version=99), expected_base_version=0, expected_corpus_revision=1
    )
    assert result.version == 1
    assert result.parent_version == 0
    assert result.restored_from is None
    assert result.content_sha256 and len(result.content_sha256) == 64
    stored = repo.get_deck("prj_001", 1)
    assert stored is not None and stored.version == 1
    assert project_columns("prj_001")["current_version"] == 1


def test_commit_second_version_links_parent(repo):
    repo.commit_version("prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1)
    v2 = repo.commit_version(
        "prj_001", deck(2), expected_base_version=1, expected_corpus_revision=1
    )
    assert v2.version == 2
    assert v2.parent_version == 1


def test_wrong_expected_base_raises_version_conflict(repo, project_columns):
    repo.commit_version("prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1)
    with pytest.raises(VersionConflict):
        repo.commit_version(
            "prj_001", deck(2), expected_base_version=0, expected_corpus_revision=1
        )
    assert project_columns("prj_001")["current_version"] == 1


def test_wrong_expected_corpus_raises_corpus_changed(repo):
    with pytest.raises(CorpusChanged):
        repo.commit_version(
            "prj_001", deck(1), expected_base_version=0, expected_corpus_revision=7
        )


def test_restore_creates_new_version_from_target_content(repo):
    v1 = repo.commit_version(
        "prj_001", deck(1, slides=[{"id": "s1", "title": "A", "layout": "title", "blocks": [{"type": "teaching", "text": "one"}]}]),
        expected_base_version=0,
        expected_corpus_revision=1,
    )
    repo.commit_version(
        "prj_001", deck(2, slides=[{"id": "s1", "title": "B", "layout": "title", "blocks": [{"type": "teaching", "text": "two"}]}]),
        expected_base_version=1,
        expected_corpus_revision=1,
    )
    v3 = repo.restore("prj_001", target_version=1, expected_base_version=2, expected_corpus_revision=1)
    assert v3.version == 3
    assert v3.restored_from == 1
    assert v3.parent_version == 2
    assert semantic_hash(repo.get_deck("prj_001", 3)) == semantic_hash(repo.get_deck("prj_001", 1))
    assert v3.content_sha256 == v1.content_sha256


def test_restore_missing_target_raises(repo):
    repo.commit_version("prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1)
    with pytest.raises(DeckNotFound):
        repo.restore("prj_001", target_version=9, expected_base_version=1, expected_corpus_revision=1)


def test_get_version_missing_returns_none(repo):
    assert repo.get_version("prj_001", 1) is None


def test_semantic_hash_ignores_version_but_not_content():
    assert semantic_hash(deck(1)) == semantic_hash(deck(2))
    changed = deck(1, slides=[{"id": "s1", "title": "改", "layout": "title", "blocks": [{"type": "teaching", "text": "x"}]}])
    assert semantic_hash(deck(1)) != semantic_hash(changed)


def test_restore_across_corpus_rejected(repo, conn):
    """N12 固化：目标版本 corpus 与当前 revision 不一致时 restore 必须拒绝。"""
    repo.commit_version("prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1)
    with conn:
        conn.execute("UPDATE projects SET corpus_revision = 2 WHERE id = 'prj_001'")
    with pytest.raises(CorpusChanged):
        repo.restore(
            "prj_001", target_version=1, expected_base_version=1, expected_corpus_revision=2
        )


def test_concurrent_commit_same_base_maps_to_version_conflict(tmp_path):
    """N2 回归：并发同 base 提交只能 1 成功，其余为 VersionConflict（不得冒泡原始 IntegrityError）。"""
    import threading

    from courseware_core.storage.database import connect as _connect
    from courseware_core.storage.database import init_db as _init_db

    db = tmp_path / "ver.db"
    seed = _connect(db)
    _init_db(seed)
    with seed:
        seed.execute(
            "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
            " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
            " VALUES ('prj_001', '{}', 0, 1, NULL, 1, '2026-09-19T00:00:00+00:00',"
            " '2026-09-19T00:00:00+00:00')"
        )
    seed.close()

    barrier = threading.Barrier(4)
    outcomes: list = []

    def commit():
        conn = _connect(db)
        try:
            barrier.wait()
            VersionRepository(conn).commit_version(
                "prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1
            )
            outcomes.append("ok")
        except VersionConflict:
            outcomes.append("conflict")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(f"error:{type(exc).__name__}")
        finally:
            conn.close()

    threads = [threading.Thread(target=commit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count("ok") == 1
    assert set(outcomes) == {"ok", "conflict"}
