"""T12 loop④：编辑模型意图路径单元测试（先红后绿）。

Fake provider 走与真实 adapter 相同的 complete_json(stage, schema_name, ...)
协议；本测试只背书状态机与门逻辑——真实模型行为属 T14 黄金链，NOT_RUN。
"""

import copy
import hashlib

import pytest

from courseware_core.errors import (
    EditUnsupported,
    InsufficientEvidence,
    JobCancelled,
    ModelOutputInvalid,
    ModelProtocolError,
)
from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import (
    DeckSpec,
    EditDecision,
    EditProposal,
    EditProposalOutcome,
    EditUnsupportedOutcome,
    SemanticVerdicts,
)
from courseware_core.services.edit_service import EditService
from courseware_core.storage.job_repository import JobRepository
from courseware_core.storage.version_repository import VersionRepository

T0 = "2026-09-19T00:00:00+00:00"
GOAL_TEXT = "NVIC 分组决定抢占与子优先级位数"
CHUNK1_TEXT = (
    "NVIC 中断控制器通过优先级分组管理抢占。分组决定抢占与子优先级位数。"
    "AIRCR 寄存器写入密码后生效。"
)


class ScriptedProvider:
    def __init__(self, by_stage: dict):
        self._by_stage = {k: list(v) for k, v in by_stage.items()}
        self.calls: list[dict] = []

    def complete_json(self, stage, schema_name, messages, context):
        self.calls.append({"stage": stage, "schema_name": schema_name,
                           "messages": messages})
        context.budget.consume(1)
        queue = self._by_stage.get(stage)
        assert queue, f"no scripted response for stage={stage}"
        value = queue.pop(0)
        if callable(value):
            # 回调注入副作用（如置取消位），模拟"最后一次模型调用完成之后、
            # 候选写库之前"才发生的状态变化（与 test_generate_service 同协议）。
            value = value(context)
        return TypedCompletion(
            value=value, usage=Usage(10, 5, 15),
            provider_request_id=f"fake-{len(self.calls)}", attempts=1,
        )

    def stages(self) -> list[str]:
        return [c["stage"] for c in self.calls]


def _insert(conn, sql, *args):
    with conn:
        conn.execute(sql, args)


def seed_project(conn, *, current_version=0):
    course = (
        '{"topic": "STM32 中断", "audience": "大二",'
        ' "duration_minutes": 45, "goals": ["理解 NVIC"], "target_slides": 8}'
    )
    _insert(
        conn,
        "INSERT INTO projects (id, course_json, current_version, corpus_revision,"
        " active_job_id, consent_to_cloud_processing, created_at, updated_at)"
        " VALUES ('prj1', ?, ?, 1, NULL, 1, ?, ?)",
        course, current_version, T0, T0,
    )


def seed_chunks(conn):
    _insert(
        conn,
        "INSERT INTO materials (id, project_id, original_name, sha256, status,"
        " pdf_pages, usable_pages, corpus_revision, warnings_json, error_code,"
        " file_path, file_size, job_id, created_at, updated_at)"
        " VALUES ('mat1','prj1','x.pdf',?,'ready',1,1,1,'[]',NULL,'x.pdf',100,NULL,?,?)",
        "a" * 64, T0, T0,
    )
    sha = hashlib.sha256(CHUNK1_TEXT.encode()).hexdigest()
    _insert(
        conn,
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES (?, 'prj1','mat1',1,1,0,?,?,?,"
        " 'pypdf-5.9.0-nfc-v1','jieba-0.42.1+ascii-v1')",
        "chk1", len(CHUNK1_TEXT), CHUNK1_TEXT, sha,
    )


EXISTING_CLAIM = {
    "id": "clm_c1",
    "text": GOAL_TEXT + "。",
    "kind": "direct",
    "evidence_refs": [
        {"chunk_id": "chk1", "document_id": "mat1", "pdf_page": 1,
         "start": 0, "end": len(GOAL_TEXT), "quote": GOAL_TEXT}
    ],
}


def seed_deck(conn):
    deck = DeckSpec(
        schema_version="1.0.0",
        project_id="prj1",
        version=1,
        corpus_revision=1,
        course={
            "topic": "STM32 中断", "audience": "大二", "duration_minutes": 45,
            "goals": ["理解 NVIC"], "target_slides": 8,
        },
        claims=[copy.deepcopy(EXISTING_CLAIM)],
        slides=[
            {
                "id": "s1", "title": "分组总览", "layout": "concept",
                "blocks": [
                    {"type": "teaching", "text": "先看分组。"},
                    {"type": "fact", "claim_id": "clm_c1"},
                ],
            },
            {
                "id": "s2", "title": "AIRCR 配置", "layout": "concept",
                "blocks": [{"type": "teaching", "text": "旧表述。"}],
            },
            {
                "id": "s3", "title": "小结", "layout": "title",
                "blocks": [{"type": "teaching", "text": "收尾。"}],
            },
        ],
    )
    VersionRepository(conn).commit_version(
        "prj1", deck, expected_base_version=0, expected_corpus_revision=1
    )
    return deck


@pytest.fixture()
def env(conn):
    seed_project(conn)
    seed_chunks(conn)
    deck = seed_deck(conn)
    return conn, deck


def new_claim_proposal(cid: str = "clm_t1", quote: str = "AIRCR 寄存器写入密码后生效。"):
    return {
        "id": cid,
        "text": "AIRCR 需先写密码再配置。",
        "kind": "direct",
        "evidence_refs": [{"chunk_id": "chk1", "quote": quote}],
    }


def replace_proposal(claim_proposals: list[dict], target: str = "s2",
                     missing: list | None = None) -> EditProposal:
    return EditProposal(
        operations=[
            {
                "op": "replace_slide",
                "target_slide_id": target,
                "slide": {
                    "id": target,
                    "title": "AIRCR 配置",
                    "layout": "concept",
                    "blocks": [
                        {"type": "teaching", "text": "先写密码，再设分组。"},
                        {"type": "fact", "claim_id": claim_proposals[0]["id"]},
                    ],
                },
            }
        ],
        claims=claim_proposals,
        summary="重述第二页并补充 AIRCR 密码步骤。",
        missing_evidence=missing or [],
    )


def proposal_decision(proposal: EditProposal) -> EditDecision:
    return EditProposalOutcome(decision="proposal", proposal=proposal)


def supported_verdicts(cid: str) -> SemanticVerdicts:
    return SemanticVerdicts(
        checks=[{"claim_id": cid, "status": "supported", "reason": "原文直接支持。"}],
        unbound_assertions=[],
    )


def start_edit(conn, instruction="把第二页重述，补充 AIRCR 密码步骤。", targets=None):
    from courseware_core.models import EditRequest

    service = EditService(conn)
    accepted = service.create_edit_job(
        "prj1",
        EditRequest(
            instruction=instruction,
            target_slide_ids=targets or ["s2"],
            base_version=1,
            corpus_revision=1,
        ),
    )
    job = JobRepository(conn).get(accepted.job_id)
    claim_running(conn, accepted.job_id)
    return service, job


def claim_running(conn, job_id: str) -> None:
    """模拟 worker.claim_next 的领取跃迁：handler 写库门按 DB 实况复查
    status=running，单测直接调 handle_* 时必须先落领取态。"""
    with conn:
        cur = conn.execute(
            "UPDATE jobs SET status = 'running' WHERE id = ? AND status = 'queued'",
            (job_id,),
        )
        assert cur.rowcount == 1


class TestModelHappyPath:
    def test_replace_produces_ready_edit_candidate(self, env):
        conn, deck = env
        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(replace_proposal([new_claim_proposal()]))],
            "verify_claims": [supported_verdicts("clm_t1")],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job(
            "prj1",
            _request("把第二页重述，补充 AIRCR 密码步骤。"),
        )
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.kind == "edit"
        assert change.status == "ready"
        assert change.validation.can_commit is True
        assert change.validation.model_id == "fake-model"
        assert change.validation.prompt_version.startswith("edit-")
        # 非目标页逐字节不变（s1/s3 原样）。
        before = {s.id: s.model_dump(mode="json") for s in deck.slides}
        after = {s.id: s.model_dump(mode="json") for s in change.candidate.slides}
        assert after["s1"] == before["s1"]
        assert after["s3"] == before["s3"]
        # claim 集合保留 + 新 claim 入集。
        assert {"clm_c1", "clm_t1"} <= {c.id for c in change.candidate.claims}
        assert change.affected_slide_ids == ["s2"]
        assert provider.stages() == ["edit_propose", "verify_claims"]
        # 新 claim 的 evidence span 是服务器权威字段（locator 解析产物）。
        added = next(c for c in change.candidate.claims if c.id == "clm_t1")
        assert added.evidence_refs[0].document_id == "mat1"
        assert added.evidence_refs[0].pdf_page == 1

    def test_no_new_claims_skips_verify_call(self, env):
        conn, _ = env
        proposal = EditProposal(
            operations=[
                {
                    "op": "replace_slide",
                    "target_slide_id": "s2",
                    "slide": {
                        "id": "s2", "title": "AIRCR 配置", "layout": "concept",
                        "blocks": [{"type": "teaching", "text": "纯教学表述，无新事实。"}],
                    },
                }
            ],
            claims=[],
            summary="重述第二页（无新增事实）。",
            missing_evidence=[],
        )
        provider = ScriptedProvider({"edit_propose": [proposal_decision(proposal)]})
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("把第二页说得更口语。"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "ready"
        assert provider.stages() == ["edit_propose"]  # 零新 claim 不调核验（T09 规则）


class TestOutcomeTaxonomy:
    def test_unsupported_decision_fails_job_with_edit_unsupported(self, env):
        conn, _ = env
        provider = ScriptedProvider({
            "edit_propose": [EditUnsupportedOutcome(
                decision="unsupported", reason="要求整册换题，超出局部编辑意图集。"
            )],
        })
        service = EditService(conn, provider=provider)
        accepted = service.create_edit_job("prj1", _request("把整个课件换成 FPGA 课题"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        with pytest.raises(EditUnsupported):
            service.handle_edit(job)

    def test_missing_evidence_blocks_job_not_failed(self, env):
        conn, _ = env
        proposal = replace_proposal([new_claim_proposal()])
        proposal = proposal.model_copy(
            update={"missing_evidence": ["教师要求的案例对比在现有资料中无对应章节"]}
        )
        provider = ScriptedProvider({"edit_propose": [proposal_decision(proposal)]})
        service = EditService(conn, provider=provider)
        accepted = service.create_edit_job("prj1", _request("加一个案例对比页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        with pytest.raises(InsufficientEvidence):
            service.handle_edit(job)
        # blocked 语义下不得留下可应用候选。
        rows = conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()
        assert rows["n"] == 0

    def test_unauthorized_target_is_model_output_invalid(self, env):
        conn, _ = env
        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(
                replace_proposal([new_claim_proposal()], target="s1")
            )],
        })
        service = EditService(conn, provider=provider)
        accepted = service.create_edit_job("prj1", _request(targets=["s2"]))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        with pytest.raises(ModelOutputInvalid):
            service.handle_edit(job)

    def test_provider_absent_raises_protocol_error(self, env):
        conn, _ = env
        service = EditService(conn)
        accepted = service.create_edit_job("prj1", _request("精简第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        with pytest.raises(ModelProtocolError):
            service.handle_edit(job)


class TestLocatorAndGates:
    def test_locator_failure_repairs_once_then_blocks(self, env):
        conn, _ = env
        bad = new_claim_proposal(quote="这段文字根本不在片段里。")
        provider = ScriptedProvider({
            "edit_propose": [
                proposal_decision(replace_proposal([bad])),
                proposal_decision(replace_proposal([bad])),  # 修复后仍失败
            ],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "blocked"
        assert change.validation.relations_valid is False
        assert provider.stages() == ["edit_propose", "edit_propose"]
        invalid = [c for c in change.validation.claim_checks if c.locator_status == "invalid"]
        assert [c.claim_id for c in invalid] == ["clm_t1"]

    def test_locator_failure_repaired_success_proceeds(self, env):
        conn, _ = env
        bad = new_claim_proposal(quote="不在片段里。")
        good = new_claim_proposal()
        provider = ScriptedProvider({
            "edit_propose": [
                proposal_decision(replace_proposal([bad])),
                proposal_decision(replace_proposal([good])),
            ],
            "verify_claims": [supported_verdicts("clm_t1")],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "ready"

    def test_unsupported_verdict_blocks_candidate(self, env):
        conn, _ = env
        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(replace_proposal([new_claim_proposal()]))],
            "verify_claims": [SemanticVerdicts(
                checks=[{"claim_id": "clm_t1", "status": "unsupported",
                         "reason": "片段未提及密码步骤。"}],
                unbound_assertions=[],
            )],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "blocked"
        assert change.validation.can_commit is False

    def test_missing_verdict_not_checked_not_green(self, env):
        conn, _ = env
        # 漏答语义=模型答复了别的 claim（对本批零覆盖）：Schema 要求
        # checks>=1，无法表达空答复；extra_ids 严格双射门整批 not_checked，
        # 与漏答同收口（T09 可信链规则）。
        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(replace_proposal([new_claim_proposal()]))],
            "verify_claims": [SemanticVerdicts(
                checks=[{"claim_id": "clm_other", "status": "supported",
                         "reason": "与本批无关的答复。"}],
                unbound_assertions=[],
            )],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "blocked"
        check = next(c for c in change.validation.claim_checks if c.claim_id == "clm_t1")
        assert check.semantic_status == "not_checked"

    def test_llm_calls_accumulated_on_job(self, env):
        conn, _ = env
        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(replace_proposal([new_claim_proposal()]))],
            "verify_claims": [supported_verdicts("clm_t1")],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        service.handle_edit(job)
        after = JobRepository(conn).get(accepted.job_id)
        assert after.llm_calls == 2

    def test_reused_existing_claim_not_misjudged_as_locator_failure(self, env):
        # N-2：模型按"未变可复用其 id"回写既有 claim 时，其证据 chunk 不在
        # 本批允许集合属正常——权威复用不得进 locator 失败队列假 blocked。
        conn, _ = env
        reused = {
            "id": "clm_c1",
            "text": GOAL_TEXT + "。",
            "kind": "direct",
            "evidence_refs": [{"chunk_id": "chk1", "quote": GOAL_TEXT}],
        }
        proposal = EditProposal(
            operations=[
                {
                    "op": "replace_slide",
                    "target_slide_id": "s2",
                    "slide": {
                        "id": "s2", "title": "AIRCR 配置", "layout": "concept",
                        "blocks": [
                            {"type": "teaching", "text": "分组是前提。"},
                            {"type": "fact", "claim_id": "clm_c1"},
                        ],
                    },
                }
            ],
            claims=[reused],
            summary="第二页改为引用既有 claim。",
            missing_evidence=[],
        )
        provider = ScriptedProvider({"edit_propose": [proposal_decision(proposal)]})
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("第二页改用既有结论"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert change.status == "ready"
        assert change.validation.claim_checks == []
        assert [c.id for c in change.candidate.claims] == ["clm_c1"]

    def test_model_reorder_reports_moved_slides_affected(self, env):
        # N-1：模型产出 reorder 只改顺序不改内容，affected 必须按位置比较
        # 报告移动页，不得恒为空误导教师审阅。
        conn, _ = env
        proposal = EditProposal(
            operations=[
                {"op": "reorder_slides", "slide_ids": ["s3", "s1", "s2"]}
            ],
            claims=[],
            summary="按教师要求把小结移到最前。",
            missing_evidence=[],
        )
        provider = ScriptedProvider({"edit_propose": [proposal_decision(proposal)]})
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job(
            "prj1", _request("把小结移到最前", targets=["s1", "s2", "s3"])
        )
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        ref = service.handle_edit(job)
        change = service.get_change("prj1", ref.id)
        assert [s.id for s in change.candidate.slides] == ["s3", "s1", "s2"]
        assert set(change.affected_slide_ids) == {"s1", "s2", "s3"}
        assert change.status == "ready"

    def test_cancel_after_last_call_does_not_write_ready_candidate(self, env):
        # B-1（Q08 同规则）：取消落在"最后一次核验完成→写库"窗口内时，
        # 不得留下可被 GET/commit 的 ready 孤儿候选。
        conn, _ = env

        def cancel_then(context=None, conn_ref=conn):
            with conn_ref:
                cur = conn_ref.execute(
                    "UPDATE jobs SET cancel_requested = 1 WHERE cancel_requested = 0"
                )
                assert cur.rowcount == 1
            return supported_verdicts("clm_t1")

        provider = ScriptedProvider({
            "edit_propose": [proposal_decision(replace_proposal([new_claim_proposal()]))],
            # 取消位恰好在"最后一次模型调用（verify）出队时"置位：
            # adapter 的 return 前守卫在 Fake 下不存在，写库前 DB 实况复查
            # （guard_writable）是拦下 ready 孤儿候选的最后一道门。
            "verify_claims": [cancel_then],
        })
        service = EditService(conn, provider=provider, model_id="fake-model")
        accepted = service.create_edit_job("prj1", _request("重述第二页"))
        job = JobRepository(conn).get(accepted.job_id)
        claim_running(conn, accepted.job_id)
        with pytest.raises(JobCancelled):
            service.handle_edit(job)
        rows = conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()
        assert rows["n"] == 0


def _request(instruction="重述第二页", targets=None, base=1, corpus=1):
    from courseware_core.models import EditRequest

    return EditRequest(
        instruction=instruction,
        target_slide_ids=targets or ["s2"],
        base_version=base,
        corpus_revision=corpus,
    )
