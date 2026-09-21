"""T12 loop③：EditService 受理门与确定性 reorder 执行单元测试（先红后绿）。"""

import copy

import pytest

from courseware_core.errors import (
    ConsentRequired,
    CorpusChanged,
    EditUnsupported,
    ProjectBusy,
    ProjectNotFound,
    VersionConflict,
)
from courseware_core.models import DeckSpec, EditRequest
from courseware_core.services.edit_service import EditService
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.version_repository import VersionRepository

COURSE = {
    "topic": "STM32 中断机制",
    "audience": "大二学生",
    "duration_minutes": 45,
    "goals": ["理解 NVIC"],
    "target_slides": 8,
}
CLAIM = {
    "id": "clm_c1",
    "text": "NVIC 分组决定抢占与子优先级位数。",
    "kind": "direct",
    "evidence_refs": [
        {"chunk_id": "chk_1", "document_id": "doc_1", "pdf_page": 1,
         "start": 0, "end": 10, "quote": "分组决定…"}
    ],
}


def deck(version: int = 1, project_id: str = "prj_001") -> DeckSpec:
    return DeckSpec(
        schema_version="1.0.0",
        project_id=project_id,
        version=version,
        corpus_revision=1,
        course=COURSE,
        claims=[copy.deepcopy(CLAIM)],
        slides=[
            {
                "id": f"s{i}",
                "title": f"页{i}",
                "layout": "concept",
                "blocks": [
                    {"type": "teaching", "text": f"内容{i}"},
                    {"type": "fact", "claim_id": "clm_c1"},
                ],
            }
            for i in (1, 2, 3)
        ],
    )


def edit_request(instruction: str, targets: list[str], base: int = 1, corpus: int = 1) -> EditRequest:
    return EditRequest(
        instruction=instruction,
        target_slide_ids=targets,
        base_version=base,
        corpus_revision=corpus,
    )


@pytest.fixture()
def seeded(conn, insert_project):
    insert_project("prj_001", current_version=0, corpus_revision=1)
    VersionRepository(conn).commit_version(
        "prj_001", deck(1), expected_base_version=0, expected_corpus_revision=1
    )
    return conn


def make_service(conn):
    return EditService(conn)


class TestAcceptanceGates:
    def test_unknown_project_raises(self, conn):
        with pytest.raises(ProjectNotFound):
            EditService(conn).create_edit_job(
                "prj_missing", edit_request("把第3页移到最前", ["s3"])
            )

    def test_consent_required(self, conn, insert_project):
        insert_project("prj_002", current_version=0, corpus_revision=1)
        VersionRepository(conn).commit_version(
            "prj_002", deck(1, project_id="prj_002"),
            expected_base_version=0, expected_corpus_revision=1,
        )
        with conn:
            conn.execute(
                "UPDATE projects SET consent_to_cloud_processing = 0 WHERE id = 'prj_002'"
            )
        with pytest.raises(ConsentRequired):
            EditService(conn).create_edit_job(
                "prj_002", edit_request("精简", ["s1"])
            )

    def test_deterministic_reorder_allowed_without_consent(self, conn, insert_project):
        # 排序不耗模型、不外发内容（PRD:19）：consent=0 不得挡确定性路径。
        insert_project("prj_003", current_version=0, corpus_revision=1)
        VersionRepository(conn).commit_version(
            "prj_003", deck(1, project_id="prj_003"),
            expected_base_version=0, expected_corpus_revision=1,
        )
        with conn:
            conn.execute(
                "UPDATE projects SET consent_to_cloud_processing = 0 WHERE id = 'prj_003'"
            )
        accepted = EditService(conn).create_edit_job(
            "prj_003",
            edit_request(
                '{"action": "reorder", "slide_ids": ["s3", "s1", "s2"]}',
                ["s1", "s2", "s3"],
            ),
        )
        params = JobRepository(conn).get_params(accepted.job_id)
        assert params["mode"] == "deterministic"

    def test_project_without_deck_rejected_by_base_floor(self, conn, insert_project):
        # base_version>=1 是契约下限：从未生成的项目（current=0）任何合法
        # EditRequest 的 base 都与之冲突，受理期显式拒绝而非 404 猜版本。
        insert_project("prj_empty", current_version=0, corpus_revision=1)
        with pytest.raises(VersionConflict):
            EditService(conn).create_edit_job(
                "prj_empty", edit_request("精简", ["s1"], base=1)
            )

    def test_stale_base_raises_version_conflict(self, seeded):
        with pytest.raises(VersionConflict):
            EditService(seeded).create_edit_job(
                "prj_001", edit_request("精简", ["s1"], base=2)
            )

    def test_corpus_mismatch_raises(self, seeded, conn):
        with conn:
            conn.execute(
                "UPDATE projects SET corpus_revision = 2 WHERE id = 'prj_001'"
            )
        with pytest.raises(CorpusChanged):
            EditService(conn).create_edit_job(
                "prj_001", edit_request("精简", ["s1"], corpus=1)
            )

    def test_unknown_target_slide_raises_edit_unsupported(self, seeded):
        with pytest.raises(EditUnsupported):
            EditService(seeded).create_edit_job(
                "prj_001", edit_request("精简这一页", ["s9"])
            )

    def test_active_job_raises_project_busy(self, seeded, conn):
        with conn:
            conn.execute(
                "UPDATE projects SET active_job_id = 'job_other' WHERE id = 'prj_001'"
            )
        with pytest.raises(ProjectBusy):
            EditService(conn).create_edit_job("prj_001", edit_request("精简", ["s1"]))

    def test_free_text_instruction_creates_model_mode_job(self, seeded):
        accepted = EditService(seeded).create_edit_job(
            "prj_001", edit_request("把第二页精简成三点", ["s2"])
        )
        assert accepted.job_id.startswith("job_")
        job = JobRepository(seeded).get(accepted.job_id)
        assert job.kind == "edit"
        assert job.status == "queued"
        assert job.base_version == 1
        assert job.corpus_revision == 1
        params = JobRepository(seeded).get_params(accepted.job_id)
        assert params["mode"] == "model"
        assert params["instruction"] == "把第二页精简成三点"
        assert params["target_slide_ids"] == ["s2"]

    def test_structured_reorder_creates_deterministic_job(self, seeded):
        instruction = '{"action": "reorder", "slide_ids": ["s3", "s1", "s2"]}'
        accepted = EditService(seeded).create_edit_job(
            "prj_001", edit_request(instruction, ["s1", "s2", "s3"])
        )
        params = JobRepository(seeded).get_params(accepted.job_id)
        assert params["mode"] == "deterministic"
        assert params["operations"][0]["op"] == "reorder_slides"
        assert params["operations"][0]["slide_ids"] == ["s3", "s1", "s2"]

    def test_structured_reorder_partial_permutation_rejected(self, seeded):
        instruction = '{"action": "reorder", "slide_ids": ["s3", "s1"]}'
        with pytest.raises(EditUnsupported):
            EditService(seeded).create_edit_job(
                "prj_001", edit_request(instruction, ["s1", "s2", "s3"])
            )

    def test_structured_unknown_action_rejected(self, seeded):
        instruction = '{"action": "delete_slide", "slide_ids": ["s1"]}'
        with pytest.raises(EditUnsupported):
            EditService(seeded).create_edit_job(
                "prj_001", edit_request(instruction, ["s1"])
            )

    def test_structured_malformed_json_falls_to_model_path(self, seeded):
        accepted = EditService(seeded).create_edit_job(
            "prj_001", edit_request('{"action": "reorder"', ["s1"])
        )
        params = JobRepository(seeded).get_params(accepted.job_id)
        assert params["mode"] == "model"


class TestDeterministicExecution:
    def _run_reorder(self, conn, order):
        service = EditService(conn)
        instruction = f'{{"action": "reorder", "slide_ids": {order}}}'
        accepted = service.create_edit_job(
            "prj_001", edit_request(instruction, ["s1", "s2", "s3"])
        )
        # 模拟 worker.claim_next 领取跃迁：写库门按 DB 实况复查 running。
        with conn:
            cur = conn.execute(
                "UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'queued'",
                (accepted.job_id,),
            )
            assert cur.rowcount == 1
        job = JobRepository(conn).get(accepted.job_id)
        return service, service.handle_edit(job)

    def test_handle_edit_produces_edit_candidate(self, seeded):
        service, ref = self._run_reorder(seeded, '["s3", "s1", "s2"]')
        assert ref.type == "change"
        change = service.get_change("prj_001", ref.id)
        assert change.kind == "edit"
        assert change.status == "ready"
        assert change.base_version == 1
        assert change.corpus_revision == 1
        assert [s.id for s in change.candidate.slides] == ["s3", "s1", "s2"]
        assert change.candidate.version == 2

    def test_non_target_content_unchanged(self, seeded):
        before = {s.id: s.model_dump(mode="json") for s in deck(1).slides}
        service, ref = self._run_reorder(seeded, '["s3", "s2", "s1"]')
        change = service.get_change("prj_001", ref.id)
        for s in change.candidate.slides:
            assert s.model_dump(mode="json") == before[s.id]

    def test_claim_set_preserved(self, seeded):
        service, ref = self._run_reorder(seeded, '["s2", "s1", "s3"]')
        change = service.get_change("prj_001", ref.id)
        assert [c.id for c in change.candidate.claims] == ["clm_c1"]

    def test_affected_ids_are_moved_slides(self, seeded):
        service, ref = self._run_reorder(seeded, '["s1", "s2", "s3"]')
        change = service.get_change("prj_001", ref.id)
        assert change.affected_slide_ids == []
        assert change.status == "ready"

    def test_validation_report_shape(self, seeded):
        service, ref = self._run_reorder(seeded, '["s3", "s1", "s2"]')
        change = service.get_change("prj_001", ref.id)
        report = change.validation
        assert report.schema_valid is True
        assert report.relations_valid is True
        assert report.layout_valid is True
        assert report.can_commit is True
        assert report.model_id is None
        assert report.claim_checks == []
        assert report.unbound_assertions == []

    def test_handle_edit_rejects_moved_project(self, seeded, conn):
        service = EditService(conn)
        accepted = service.create_edit_job(
            "prj_001",
            edit_request('{"action": "reorder", "slide_ids": ["s3", "s1", "s2"]}',
                         ["s1", "s2", "s3"]),
        )
        job = JobRepository(conn).get(accepted.job_id)
        VersionRepository(conn).commit_version(
            "prj_001", deck(2), expected_base_version=1, expected_corpus_revision=1
        )
        with pytest.raises(VersionConflict):
            service.handle_edit(job)
