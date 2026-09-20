import hashlib

import pytest
from jsonschema import FormatChecker, validate as js_validate

import json
from pathlib import Path

from courseware_core.errors import DomainError
from courseware_core.evidence.locator import resolve_evidence
from courseware_core.models import EvidenceProposal

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"
DEFS = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]

T0 = "2026-09-19T00:00:00+00:00"
QUOTE = "NVIC 优先级分组决定了抢占与子优先级的位数分配。"
CHUNK_TEXT = f"前言铺垫。{QUOTE}后续内容。"


@pytest.fixture()
def seeded(conn, insert_project):
    insert_project("prj_a")
    insert_project("prj_b")
    conn.execute(
        "INSERT INTO materials (id, project_id, original_name, sha256, status,"
        " warnings_json, file_path, file_size, created_at, updated_at)"
        " VALUES ('doc_a1', 'prj_a', 'n.pdf', ?, 'ready', '[]', 'x.pdf', 1, ?, ?)",
        ("a" * 64, T0, T0),
    )
    conn.execute(
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES ('chk_1', 'prj_a', 'doc_a1', 3, 7, 0, ?, ?, ?, 'e1', 't1')",
        (len(CHUNK_TEXT), CHUNK_TEXT, hashlib.sha256(CHUNK_TEXT.encode()).hexdigest()),
    )
    conn.execute(
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES ('chk_dup', 'prj_a', 'doc_a1', 3, 8, 0, ?, ?, ?, 'e1', 't1')",
        (
            len(QUOTE + QUOTE),
            QUOTE + QUOTE,
            hashlib.sha256((QUOTE + QUOTE).encode()).hexdigest(),
        ),
    )
    conn.commit()
    return conn


def resolve(conn, chunk_id, quote, allowed=None):
    return resolve_evidence(
        conn,
        project_id="prj_a",
        corpus_revision=3,
        proposal=EvidenceProposal(chunk_id=chunk_id, quote=quote),
        allowed_chunk_ids=allowed if allowed is not None else {chunk_id},
    )


def test_chunk_not_in_allowed_batch_rejected(seeded):
    # AGENT_00-Q05：项目语料里存在但本批未提供给模型的 chunk 不得被引用——
    # "存在"不等于"可见"，防模型偷看没进 prompt 的资料。
    with pytest.raises(DomainError) as exc:
        resolve(seeded, "chk_1", QUOTE, allowed={"chk_unseen"})
    assert exc.value.code == "EVIDENCE_INVALID"
    assert "not provided" in exc.value.message


def test_server_fills_offsets_and_page(seeded):
    span = resolve(seeded, "chk_1", QUOTE)
    assert span.start == CHUNK_TEXT.index(QUOTE)
    assert span.end == span.start + len(QUOTE)
    assert span.pdf_page == 7
    assert span.document_id == "doc_a1"
    assert span.chunk_id == "chk_1"
    assert span.quote == QUOTE


def test_span_satisfies_contract(seeded):
    span = resolve(seeded, "chk_1", QUOTE)
    js_validate(
        span.model_dump(mode="json"),
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": "#/$defs/EvidenceSpan",
            "$defs": DEFS,
        },
        format_checker=FormatChecker(),
    )


def test_chunk_from_other_project_rejected(seeded):
    seeded.execute(
        "INSERT INTO materials (id, project_id, original_name, sha256, status,"
        " warnings_json, file_path, file_size, created_at, updated_at)"
        " VALUES ('doc_b1', 'prj_b', 'b.pdf', ?, 'ready', '[]', 'y.pdf', 1, ?, ?)",
        ("b" * 64, T0, T0),
    )
    seeded.execute(
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES ('chk_b', 'prj_b', 'doc_b1', 3, 1, 0, 5, ?, ?, 'e1', 't1')",
        ("别的项目", hashlib.sha256("别的项目".encode()).hexdigest()),
    )
    seeded.commit()
    with pytest.raises(DomainError) as exc:
        resolve(seeded, "chk_b", "别的项目")
    assert exc.value.code == "EVIDENCE_INVALID"


def test_chunk_from_other_revision_rejected(seeded):
    with pytest.raises(DomainError):
        resolve_evidence(
            seeded,
            project_id="prj_a",
            corpus_revision=2,
            proposal=EvidenceProposal(chunk_id="chk_1", quote=QUOTE),
            allowed_chunk_ids={"chk_1"},
        )


def test_quote_not_in_chunk_rejected(seeded):
    with pytest.raises(DomainError) as exc:
        resolve(seeded, "chk_1", "这段文字根本不存在于语料中。")
    assert exc.value.code == "EVIDENCE_INVALID"


def test_ambiguous_quote_rejected_not_first_match(seeded):
    """重复 quote 必须拒绝并要求补上下文，不随意匹配第一次（docs/04 §19）。"""
    with pytest.raises(DomainError) as exc:
        resolve(seeded, "chk_dup", QUOTE)
    assert exc.value.code == "EVIDENCE_INVALID"
    assert "ambiguous" in exc.value.message.lower()


def test_overlapping_duplicate_quote_is_ambiguous(seeded):
    """N2 回归：重叠出现（"aba" 在 "ababa"）必须按 2 次算歧义，
    不能用非重叠 str.count 漏判后随意取第一次。"""
    text = "ababa"
    seeded.execute(
        "INSERT INTO chunks (chunk_id, project_id, document_id, corpus_revision,"
        " pdf_page, page_start, page_end, text, text_sha256, extractor_version,"
        " tokenizer_version) VALUES ('chk_ov', 'prj_a', 'doc_a1', 3, 9, 0, 5, ?, ?, 'e1', 't1')",
        (text, "0" * 64),
    )
    seeded.commit()
    import pytest as _pt
    from courseware_core.errors import DomainError as _DE
    with _pt.raises(_DE) as exc:
        resolve(seeded, "chk_ov", "aba")
    assert "ambiguous" in exc.value.message.lower()


def test_cumulative_snapshot_allows_older_chunk(seeded):
    span = resolve_evidence(
        seeded,
        project_id="prj_a",
        corpus_revision=5,
        proposal=EvidenceProposal(chunk_id="chk_1", quote=QUOTE),
        allowed_chunk_ids={"chk_1"},
    )
    assert span.pdf_page == 7


def test_unknown_chunk_rejected(seeded):
    with pytest.raises(DomainError):
        resolve(seeded, "chk_missing", QUOTE)


def test_empty_quote_rejected_by_contract(seeded):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvidenceProposal(chunk_id="chk_1", quote="")
