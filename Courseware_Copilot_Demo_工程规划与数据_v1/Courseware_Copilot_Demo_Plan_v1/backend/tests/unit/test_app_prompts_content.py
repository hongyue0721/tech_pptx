"""app-prompts/content.md 防退化断言（2026-09-20 真实模型首跑实锤）。

deepseek-flash 两次 generate 均输出 claims.kind='fact'（22 条 literal_error），
根因是 v1 prompt 只说"直接事实与有前提的推论分开"，未显式给出 kind 枚举字面值，
且 slides 中块类型名 fact 与 claim.kind 术语混用。修复=v2 显式枚举+术语区分。
本测试锁死该表述，防止 prompt 改版再次丢失契约字面量。
"""

from pathlib import Path

import pytest

from courseware_core.llm.prompts import load_system_prompt

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def content_prompt() -> tuple[str, str]:
    return load_system_prompt("content", REPO_ROOT / "app-prompts")


def test_content_prompt_version_bumped(content_prompt):
    version, _ = content_prompt
    assert version == "content-v4", (
        "kind 枚举（v2）、blocks 结构（v3）、schema 边界声明（v4）都必须升版本"
        "（R00-A：改 prompt 必须 bump，真实模型行为差异需版本可追溯）"
    )


def test_content_prompt_states_kind_enum_literals(content_prompt):
    _, body = content_prompt
    assert '"direct"' in body and '"derived"' in body, (
        "claims.kind 必须显式给出枚举字面值 direct/derived——"
        "真实模型会把 slides 块类型 fact 误填进 kind（2026-09-20 实锤）"
    )


def test_content_prompt_distinguishes_block_fact_from_claim_kind(content_prompt):
    _, body = content_prompt
    assert "kind" in body and "fact" in body, (
        "必须同时出现 claim.kind 与 slides fact 块，供术语区分表述生效"
    )
    assert "不是合法的kind取值" in body and "与claim的kind取值无关" in body, (
        "必须显式声明 slides 的 fact 是块类型而非 claim.kind 取值"
    )


def test_content_prompt_states_slide_blocks_structure(content_prompt):
    _, body = content_prompt
    # 2026-09-20 真实模型第二次实锤：无结构说明时模型把 fact/teaching 平铺成
    # slide 顶层数组字段（9 条 missing/extra_forbidden）。结构必须显式给出。
    assert '"blocks"' in body, "必须说明 slides 内容承载于 blocks 数组"
    assert '"claim_id"' in body, "必须给出 fact 块 {type,claim_id} 的字面形状"
    assert "title" in body and "concept" in body and "two_column" in body and "process_example" in body, (
        "必须列全 layout 枚举（title/concept/two_column/process_example）"
    )
    # v3 结构样例的全部契约字面量必须锁死：删掉任一结构键即红。
    for key in ('"claims"', '"slides"', '"missing_evidence"', '"rationale"',
                '"evidence_refs"', '"chunk_id"', '"quote"', '"layout"',
                '"assumptions"', '"text"', '"id"'):
        assert key in body, f"结构样例缺少契约字面键 {key}"
    assert '"type":"fact"' in body or '"type": "fact"' in body, (
        "fact 块判别式字面值必须出现"
    )
    # v4：schema 边界声明（ContentProposal max 16 slides / 96 claims；
    # ClaimProposal.evidence_refs min 1）不得静默丢失。
    for bound in ("16", "96"):
        assert bound in body, f"结构样例缺少 schema 边界 {bound}"


def test_verify_prompt_states_status_field_and_structure():
    # 2026-09-20 真实模型第三次实锤：verify 阶段模型输出 "verdict" 字段名，
    # schema 是 SemanticCheck.status（26 条 missing/extra_forbidden）。
    version, body = load_system_prompt("verify", REPO_ROOT / "app-prompts")
    assert version == "verify-v2", "补结构说明必须升版本（R00-A）"
    assert '"status"' in body, "checks 字段必须显式给出 status 字面值名"
    assert '"checks"' in body and '"claim_id"' in body and '"reason"' in body
    for enum_val in ('"supported"', '"partial"', '"unsupported"', '"conflict"'):
        assert enum_val in body, f"status 枚举字面值 {enum_val} 必须带引号锁死"
    assert '不存在"verdict"字段' in body, (
        "必须显式否定 verdict 字段名（2026-09-20 模型实锤输出 verdict）"
    )


def test_audit_prompt_states_output_structure():
    version, body = load_system_prompt("audit", REPO_ROOT / "app-prompts")
    assert version == "audit-v2", "补结构样例必须升版本（R00-A）"
    assert '"audited_slide_ids"' in body and '"unbound_assertions"' in body
    assert '"field_path"' in body and '"slide_id"' in body
