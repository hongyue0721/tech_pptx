"""T09 changes 表与 ChangeRepository 单测：候选整对象持久化与 CAS 状态迁移。"""

import sqlite3

import pytest

from courseware_core.models import CandidateChange
from courseware_core.storage.change_repository import ChangeRepository


def _candidate(**overrides) -> CandidateChange:
    payload = dict(CANDIDATE_FIXTURE)
    payload.update(overrides)
    return CandidateChange.model_validate(payload)


CANDIDATE_FIXTURE = {
    "id": "chg_001",
    "project_id": "prj_001",
    "base_version": 0,
    "corpus_revision": 1,
    "status": "ready",
    "kind": "generation",
    "affected_slide_ids": ["sld_001"],
    "summary": "首轮候选：1页2claims，全部核验通过。",
    "candidate": {
        "schema_version": "1.0.0",
        "project_id": "prj_001",
        "version": 1,
        "corpus_revision": 1,
        "course": {
            "topic": "STM32 中断机制",
            "audience": "大二电子信息专业学生",
            "duration_minutes": 45,
            "goals": ["理解 NVIC 优先级分组"],
            "target_slides": 8,
        },
        "claims": [
            {
                "id": "clm_001",
                "text": "NVIC 优先级分组决定抢占与子优先级的位数分配。",
                "kind": "direct",
                "evidence_refs": [
                    {
                        "chunk_id": "chk_001",
                        "document_id": "doc_001",
                        "pdf_page": 3,
                        "start": 10,
                        "end": 42,
                        "quote": "NVIC 优先级分组决定了抢占优先级与子优先级的位数分配。",
                    }
                ],
                "rationale": None,
            }
        ],
        "slides": [
            {
                "id": "sld_001",
                "title": "NVIC 优先级分组",
                "layout": "concept",
                "blocks": [{"type": "fact", "claim_id": "clm_001"}],
            }
        ],
    },
    "validation": {
        "schema_valid": True,
        "relations_valid": True,
        "layout_valid": True,
        "claim_checks": [
            {
                "claim_id": "clm_001",
                "locator_status": "located",
                "semantic_status": "supported",
                "reason": "引用原文直接支持。",
            }
        ],
        "warnings": [],
        "can_commit": True,
        "model_id": None,
        "prompt_version": "content-v1+verify-v1",
        "checked_at": "2026-09-20T12:00:00+00:00",
        "raw_result_sha256": None,
        "unbound_assertions": [],
    },
    "created_at": "2026-09-20T12:00:00+00:00",
}


@pytest.fixture()
def repo(conn, insert_project):
    insert_project("prj_001", corpus_revision=1)
    return ChangeRepository(conn)


class TestChangeRepository:
    def test_create_and_get_roundtrip(self, repo):
        candidate = _candidate()
        repo.create(candidate)
        got = repo.get("chg_001")
        assert got == candidate

    def test_get_unknown_returns_none(self, repo):
        assert repo.get("chg_missing") is None

    def test_invalid_status_rejected_by_check(self, repo):
        candidate = _candidate(status="ready")
        repo.create(candidate)
        with pytest.raises(sqlite3.IntegrityError):
            with repo._conn:  # noqa: SLF001 测试直改列验证 CHECK
                repo._conn.execute(
                    "UPDATE changes SET status='weird' WHERE id='chg_001'"
                )

    def test_mark_committed_cas_only_from_ready(self, repo):
        repo.create(_candidate())
        assert repo.mark_committed("chg_001") is True
        assert repo.get("chg_001").status == "committed"
        # 二次提交迁移（并发 commit 的输家）：CAS 失败返回 False，不覆盖。
        assert repo.mark_committed("chg_001") is False

    def test_mark_committed_unknown_returns_false(self, repo):
        assert repo.mark_committed("chg_missing") is False

    def test_project_delete_cascades_changes(self, repo, conn):
        repo.create(_candidate())
        with conn:
            conn.execute("DELETE FROM projects WHERE id='prj_001'")
        assert repo.get("chg_001") is None
