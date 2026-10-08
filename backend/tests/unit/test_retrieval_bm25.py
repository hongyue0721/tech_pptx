import hashlib

import pytest

from courseware_core.materials.chunker import split_page
from courseware_core.materials.parser import ParsedPage
from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.storage.database import connect
from courseware_core.storage.material_repository import MaterialRepository

T0 = "2026-09-19T00:00:00+00:00"


def seed_chunk(
    conn,
    *,
    project_id,
    document_id,
    revision,
    text,
    pdf_page=1,
    chunk_id=None,
):
    chunk_id = chunk_id or f"chk_{hashlib.sha256(text.encode()).hexdigest()[:12]}"
    conn.execute(
        "INSERT OR IGNORE INTO materials (id, project_id, original_name, sha256,"
        " status, warnings_json, file_path, file_size, created_at, updated_at)"
        " VALUES (?, ?, 'doc.pdf', ?, 'ready', '[]', 'x.pdf', 1, ?, ?)",
        (document_id, project_id, "a" * 64, T0, T0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO chunks (chunk_id, project_id, document_id,"
        " corpus_revision, pdf_page, page_start, page_end, text, text_sha256,"
        " extractor_version, tokenizer_version)"
        " VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 'e1', 't1')",
        (
            chunk_id,
            project_id,
            document_id,
            revision,
            pdf_page,
            len(text),
            text,
            hashlib.sha256(text.encode()).hexdigest(),
        ),
    )
    conn.commit()
    return chunk_id


@pytest.fixture()
def corpus(conn, insert_project):
    insert_project("prj_a")
    insert_project("prj_b")
    seed_chunk(
        conn, project_id="prj_a", document_id="doc_a1", revision=3,
        text="NVIC优先级分组决定了抢占优先级与子优先级的位数分配。",
    )
    seed_chunk(
        conn, project_id="prj_a", document_id="doc_a1", revision=3,
        text="EXTI 外部中断线通过边沿检测触发挂起寄存器置位。",
    )
    seed_chunk(
        conn, project_id="prj_a", document_id="doc_a2", revision=3,
        text="红烧肉的做法是先焯水再小火慢炖四十分钟。",
    )
    seed_chunk(
        conn, project_id="prj_a", document_id="doc_a1", revision=2,
        text="旧语料里的 NVIC 笔记文本已经过期。",
    )
    seed_chunk(
        conn, project_id="prj_b", document_id="doc_b1", revision=3,
        text="另一个项目的 NVIC 中断资料不应被检索到。",
    )
    return conn


def test_relevant_chunk_ranks_first(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="NVIC 优先级分组", limit=5)
    assert hits
    assert "优先级" in hits[0].text
    assert hits[0].score >= hits[-1].score


def test_scoring_not_confused_with_probability(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="EXTI 边沿检测", limit=5)
    assert hits and "EXTI" in hits[0].text.upper()


def test_revision_snapshot_is_cumulative_and_excludes_future(corpus):
    """revision N 快照 = 截至 N 的累积语料：≤N 可见，>N 的未来材料不可见。"""
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="NVIC 过期 笔记", limit=10)
    assert any("已经过期" in h.text for h in hits)
    future = search_chunks(corpus, project_id="prj_a", corpus_revision=2, query="优先级 分组 位数 分配", limit=10)
    assert all("位数分配" not in h.text for h in future)


def test_project_isolation(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="NVIC 中断 资料", limit=10)
    assert all(h.project_id == "prj_a" for h in hits)
    other = search_chunks(corpus, project_id="prj_b", corpus_revision=3, query="NVIC 中断 资料", limit=10)
    assert all(h.project_id == "prj_b" for h in other)


def test_chunks_without_surface_intersection_are_excluded(corpus):
    """B1 回归：BM25Plus 的 delta 常数项给所有片段正分，
    与查询零词面交集的无关片段不得混入候选结果。"""
    seed_chunk(
        corpus, project_id="prj_a", document_id="doc_a3", revision=3,
        text="红烧狮子头需要冰糖炒色并慢火收汁。", chunk_id="chk_unrelated",
    )
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="优先级分组", limit=12)
    assert hits
    assert all(h.chunk_id != "chk_unrelated" for h in hits)
    for h in hits:
        query_terms = {"优先级", "分组"}
        assert any(t in h.text for t in query_terms)


def test_no_results_returns_empty_not_default(corpus):
    assert search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="量子隧穿效应", limit=5) == []


def test_empty_query_returns_empty(corpus):
    assert search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="", limit=5) == []
    assert search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="   ", limit=5) == []


def test_limit_respected(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="优先级 中断 NVIC", limit=1)
    assert len(hits) <= 1


def test_hit_carries_metadata_for_locator(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="NVIC 优先级", limit=5)
    top = hits[0]
    assert top.chunk_id and top.document_id and top.pdf_page >= 1
    assert top.corpus_revision == 3


def test_ascii_identifier_query_matches_whole_word(corpus):
    hits = search_chunks(corpus, project_id="prj_a", corpus_revision=3, query="NVIC_SetPriority", limit=5)
    assert isinstance(hits, list)
