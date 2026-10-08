"""BM25 检索（docs/05 §2/§9）：存储查询必须带项目与 corpus_revision。

分数只用于相对排序，不是事实置信度；无结果返回空列表，
绝不插入默认教材内容。P0 每次查询从 chunks 表现建语料（演示规模），
索引缓存留给后续规模优化，不预建平行语义。
"""

import sqlite3
from dataclasses import dataclass

from rank_bm25 import BM25Plus

from .tokenizer import tokenize


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: str
    project_id: str
    document_id: str
    corpus_revision: int
    pdf_page: int
    page_start: int
    page_end: int
    text: str
    score: float


def search_chunks(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    corpus_revision: int,
    query: str,
    limit: int = 12,
) -> list[RankedChunk]:
    # 规模边界（review N5）：P0 每次查询全量读 chunks 现建索引，
    # 500k 字符上限（docs/11 §7）内可接受；更大规模需缓存/增量索引，进 T15 前评估。
    rows = conn.execute(
        "SELECT chunk_id, project_id, document_id, corpus_revision, pdf_page,"
        " page_start, page_end, text FROM chunks"
        " WHERE project_id = ? AND corpus_revision <= ?",
        (project_id, corpus_revision),
    ).fetchall()
    # corpus_revision 语义是"截至该 revision 的累积语料快照"（只增不减）：
    # 绑定 revision N 的检索必须可复现地看到 N 时刻的全部有效材料，
    # 而不是仅 N 时刻新增的材料。
    query_tokens = tokenize(query)
    if not rows or not query_tokens:
        return []

    corpus_tokens = [tokenize(row["text"]) for row in rows]
    # BM25Plus：小语料/单文档时 Okapi 的 idf 可为负导致全部过滤，
    # Plus 版本 idf 恒正，保证有词面命中就有分（docs/05 §9 相对排序）。
    bm25 = BM25Plus(corpus_tokens)
    scores = bm25.get_scores(query_tokens)

    scored: list[tuple[float, sqlite3.Row]] = []
    lowered_query = query.lower()
    query_terms = set(query_tokens)
    for index, (row, base_score) in enumerate(zip(rows, scores)):
        text = row["text"]
        # 词面交集门槛（review B1）：BM25Plus 常数项 delta 让所有片段都拿正分，
        # 与查询零交集的无关片段必须显式排除，否则候选被污染、覆盖判定失真。
        if not (query_terms & set(corpus_tokens[index])):
            continue
        score = float(base_score)
        # 精确词命中加成：完整查询短语与 ASCII 标识符按子串精确命中加权，
        # 弥补分词相似度排序对"原话出现"的欠敏感（docs/05 §9）。
        if lowered_query and lowered_query in text.lower():
            score += 1.0
        for token in query_tokens:
            if token.isascii() and token in text.lower():
                score += 0.5
        scored.append((score, row))

    scored.sort(key=lambda item: -item[0])
    return [
        RankedChunk(
            chunk_id=row["chunk_id"],
            project_id=row["project_id"],
            document_id=row["document_id"],
            corpus_revision=row["corpus_revision"],
            pdf_page=row["pdf_page"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            text=row["text"],
            score=score,
        )
        for score, row in scored[:limit]
    ]
