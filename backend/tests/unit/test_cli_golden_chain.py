"""T13 循环②：CLI 黄金链——与 Web 同 service/同 worker/同验证门的完整工作流。

真实 PDF 解析（demo 教材）→ 计划 → 教师确认 → 候选生成（Fake provider 走
真实装配路径）→ 审阅 → 提交 → 确定性 reorder → 恢复 → 导出落盘。
模型提案为 scripted（单元背书）；真实模型黄金链归 T14/码道实测。
"""

import io
import json
import sqlite3
from pathlib import Path

import pytest

from courseware_core.cli import main
from courseware_core.llm.adapter import TypedCompletion, Usage
from courseware_core.models import (
    ContentProposal,
    PlanProposal,
    SemanticVerdicts,
    VisibleTextAudit,
)

DEMO_PDF = Path(__file__).resolve().parents[3] / "demo-data" / "inputs" / \
    "01_stm32_interrupt_notes.pdf"

QUOTE1 = "中断"


class ScriptedProvider:
    """按 stage 消费脚本队列；与 contract StageProvider 同形（测试资产）。"""

    def __init__(self):
        self._queues: dict[str, list] = {}
        self.calls: list[str] = []

    def queue(self, stage, values):
        self._queues[stage] = list(values)

    def complete_json(self, stage, schema_name, messages, context):
        self.calls.append(stage)
        context.budget.consume(1)
        queue = self._queues.get(stage)
        if not queue:
            raise AssertionError(f"no scripted response for stage={stage}")
        return TypedCompletion(
            value=queue.pop(0), usage=Usage(10, 5, 15),
            provider_request_id=f"fake-{len(self.calls)}", attempts=1,
        )


def run_cli(argv, *, provider=None, env=None):
    out = io.StringIO()
    rc = main(argv, env=env or {}, provider=provider, stdout=out)
    return rc, json.loads(out.getvalue())


def _payload(envelope):
    assert envelope["ok"], envelope
    return envelope["payload"]


@pytest.fixture()
def data_dir(tmp_path):
    return tmp_path / "skill-demo"


def _create_project(data_dir, goal: str) -> str:
    req = data_dir.parent / "project.json"
    req.write_text(json.dumps({
        "course": {"topic": "STM32 中断", "audience": "大二",
                   "duration_minutes": 45, "goals": [goal],
                   "target_slides": 4},
        "consent_to_cloud_processing": True,
    }, ensure_ascii=False), encoding="utf-8")
    rc, env = run_cli(["project", "create", "--request", str(req),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    return _payload(env)["id"]


def _chunks(data_dir) -> list[sqlite3.Row]:
    conn = sqlite3.connect(data_dir / "app.db")
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(
            "SELECT chunk_id, text FROM chunks ORDER BY chunk_id"))
    finally:
        conn.close()


def _plan_proposal(chunks) -> PlanProposal:
    return PlanProposal.model_validate({
        "slides": [
            {"id": "ps1", "title": "中断概念", "purpose": "讲解中断入口",
             "layout": "concept", "goal_indices": [0],
             "evidence_chunk_ids": [chunks[0]["chunk_id"]]},
            {"id": "ps2", "title": "NVIC 优先级", "purpose": "讲解分组配置",
             "layout": "concept", "goal_indices": [0],
             "evidence_chunk_ids": [chunks[0]["chunk_id"]]},
        ],
        "coverage_notes": [{"goal_index": 0,
                            "candidate_chunk_ids": [chunks[0]["chunk_id"]],
                            "note": "教材覆盖"}],
    })


def _content_proposal(chunks) -> ContentProposal:
    text = chunks[0]["text"]
    quote = text[:12]
    return ContentProposal.model_validate({
        "claims": [
            {"id": "clm1", "text": f"要点一：{quote}", "kind": "direct",
             "evidence_refs": [{"chunk_id": chunks[0]["chunk_id"],
                                "quote": quote}], "rationale": None},
            {"id": "clm2", "text": f"要点二：{text[12:24]}", "kind": "direct",
             "evidence_refs": [{"chunk_id": chunks[0]["chunk_id"],
                                "quote": text[12:24]}], "rationale": None},
        ],
        "slides": [
            {"id": "ps1", "title": "中断概念", "layout": "concept",
             "blocks": [{"type": "fact", "claim_id": "clm1"}]},
            {"id": "ps2", "title": "NVIC 优先级", "layout": "concept",
             "blocks": [{"type": "fact", "claim_id": "clm2"}]},
        ],
        "missing_evidence": [],
    })


def _verdicts() -> SemanticVerdicts:
    return SemanticVerdicts.model_validate({
        "checks": [
            {"claim_id": "clm1", "status": "supported", "reason": "原文支持。"},
            {"claim_id": "clm2", "status": "supported", "reason": "原文支持。"},
        ],
        "unbound_assertions": [],
    })


def _audit() -> VisibleTextAudit:
    return VisibleTextAudit.model_validate(
        {"audited_slide_ids": ["ps1", "ps2"], "unbound_assertions": []}
    )


def _commit(data_dir, project: str, change: str, base: int, corpus: int) -> dict:
    rc, env = run_cli(["change", "commit", "--project", project,
                       "--change", change, "--base-version", str(base),
                       "--corpus-revision", str(corpus),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    return _payload(env)


def test_golden_chain_full_workflow(data_dir):
    # 1. 真实 PDF 解析先行，goal 取教材真实内容（T06 grounding 纪律）
    from courseware_core.materials.parser import ParseLimits, parse_pdf
    doc = parse_pdf(DEMO_PDF, ParseLimits())
    goal = doc.pages[0].text[:15].strip() or doc.pages[1].text[:15].strip()
    project = _create_project(data_dir, goal)

    # 2. material add：真实解析 worker 路径
    rc, env = run_cli(["material", "add", "--project", project,
                       "--file", str(DEMO_PDF), "--data-dir", str(data_dir)])
    assert rc == 0, env
    job = _payload(env)["job"]
    assert job["status"] == "succeeded", job
    chunks = _chunks(data_dir)
    assert chunks, "真实解析必须产出 chunks"

    # duplicate：同内容重传零新 job
    rc, env = run_cli(["material", "add", "--project", project,
                       "--file", str(DEMO_PDF), "--data-dir", str(data_dir)])
    assert rc == 0, env
    assert _payload(env)["job"] is None
    assert _payload(env)["result"]["accepted"]["duplicate"] is True

    provider = ScriptedProvider()
    provider.queue("plan_course", [_plan_proposal(chunks)])

    # 3. plan create（项目 corpus_revision 真值驱动，不手填魔数）
    conn = sqlite3.connect(data_dir / "app.db")
    corpus = conn.execute(
        "SELECT corpus_revision FROM projects WHERE id=?", (project,)
    ).fetchone()[0]
    conn.close()
    rc, env = run_cli(["plan", "create", "--project", project,
                       "--corpus-revision", str(corpus),
                       "--data-dir", str(data_dir)], provider=provider)
    assert rc == 0, env
    payload = _payload(env)
    assert payload["job"]["status"] == "succeeded"
    plan = payload["result"]
    assert plan["status"] == "draft"

    # 4. plan confirm（缺省=按原样确认）
    rc, env = run_cli(["plan", "confirm", "--project", project,
                       "--plan", plan["id"], "--corpus-revision", str(corpus),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    assert _payload(env)["status"] == "confirmed"

    # 5. deck generate：真实 handler 装配（locator/verify/audit 全门通过）
    provider.queue("generate_content", [_content_proposal(chunks)])
    provider.queue("verify_claims", [_verdicts()])
    provider.queue("audit_visible_text", [_audit()])
    rc, env = run_cli(["deck", "generate", "--project", project,
                       "--plan", plan["id"], "--base-version", "0",
                       "--corpus-revision", str(corpus),
                       "--data-dir", str(data_dir)], provider=provider)
    assert rc == 0, env
    payload = _payload(env)
    assert payload["job"]["status"] == "succeeded"
    change = payload["result"]
    assert change["status"] == "ready", change["validation"]
    change_id = change["id"]

    # 6. change show 与 generate 结果一致（同一真源）
    rc, env = run_cli(["change", "show", "--project", project,
                       "--change", change_id, "--data-dir", str(data_dir)])
    assert rc == 0, env
    assert _payload(env)["id"] == change_id

    # 7. commit → v1
    v1 = _commit(data_dir, project, change_id, base=0, corpus=corpus)
    assert v1["version"] == 1

    # 8. 确定性 reorder → v2（零模型调用：provider 不再消费）
    rc, env = run_cli(["deck", "show", "--project", project, "--version", "1",
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    deck_ids = [s["id"] for s in _payload(env)["slides"]]
    reordered = list(reversed(deck_ids))
    edit_req = data_dir.parent / "edit.json"
    edit_req.write_text(json.dumps({
        "instruction": json.dumps({"action": "reorder", "slide_ids": reordered}),
        "target_slide_ids": deck_ids, "base_version": 1,
        "corpus_revision": corpus,
    }), encoding="utf-8")
    rc, env = run_cli(["deck", "edit", "--project", project,
                       "--request", str(edit_req), "--data-dir", str(data_dir)],
                      provider=provider)
    assert rc == 0, env
    payload = _payload(env)
    assert payload["job"]["status"] == "succeeded"
    edit_change = payload["result"]
    assert edit_change["kind"] == "edit"
    assert [s["id"] for s in edit_change["candidate"]["slides"]] == reordered
    v2 = _commit(data_dir, project, edit_change["id"], base=1, corpus=corpus)
    assert v2["version"] == 2

    # 9. restore v1 → v3（新版本，不覆盖历史）
    restore_req = data_dir.parent / "restore.json"
    restore_req.write_text(json.dumps({
        "target_version": 1, "base_version": 2,
        "corpus_revision": corpus, "acknowledged": True,
    }), encoding="utf-8")
    rc, env = run_cli(["deck", "restore", "--project", project,
                       "--request", str(restore_req),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    v3 = _payload(env)
    assert v3["version"] == 3 and v3["restored_from"] == 1

    # 10. export v3 → 文件落盘 + sha256 一致
    out_dir = data_dir.parent / "out"
    rc, env = run_cli(["deck", "export", "--project", project,
                       "--version", "3", "--out-dir", str(out_dir),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    payload = _payload(env)
    assert payload["job"]["status"] == "succeeded"
    files = payload["result"]["exported_files"]
    pptx = [f for f in files if f["path"].endswith(".pptx")]
    report = [f for f in files if f["path"].endswith(".json")]
    assert len(pptx) == 1 and len(report) == 1
    import hashlib
    data = Path(pptx[0]["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == pptx[0]["sha256"]
    assert data.startswith(b"PK")
    report_json = json.loads(Path(report[0]["path"]).read_text(encoding="utf-8"))
    assert report_json["version"] == 3
    assert report_json["project_id"] == project
    assert "claims" in report_json and "document_codes" in report_json


def test_golden_chain_model_path_blocked_surfaces_report(data_dir):
    """资料不足 blocked 链：goal 与教材无关 → exit 1 + INSUFFICIENT_EVIDENCE。"""
    project = _create_project(data_dir, "青霉素的发现历史与临床应用机制")
    rc, env = run_cli(["material", "add", "--project", project,
                       "--file", str(DEMO_PDF), "--data-dir", str(data_dir)])
    assert rc == 0, env
    # 全目标 unsupported：服务端受理前判定、零模型调用（provider 空队列=
    # 若被消费即 AssertionError，反向证明"资料不足不烧模型"）
    provider = ScriptedProvider()
    rc, env = run_cli(["plan", "create", "--project", project,
                       "--corpus-revision", "1", "--data-dir", str(data_dir)],
                      provider=provider)
    assert rc == 1, env
    assert env["ok"] is False
    assert env["payload"]["error"]["code"] == "INSUFFICIENT_EVIDENCE"
    assert provider.calls == []
