"""EvidenceLocator：仅接受当前允许 chunk 集合内的提议（docs/18 接口契约）。

模型只提议 chunk_id + quote；document/page/偏移一律由服务端从存储记录解析填充，
不接受模型自填页码（docs/04 §19）。quote 必须是归一化 chunk 文本的唯一连续子串：
零次=不存在，多次=歧义（要求补上下文，不随意取第一次）。
"""

import sqlite3

from courseware_core.errors import DomainError
from courseware_core.models import EvidenceProposal, EvidenceSpan


def resolve_evidence(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    corpus_revision: int,
    proposal: EvidenceProposal,
) -> EvidenceSpan:
    row = conn.execute(
        "SELECT document_id, pdf_page, text FROM chunks"
        " WHERE chunk_id = ? AND project_id = ? AND corpus_revision <= ?",
        (proposal.chunk_id, project_id, corpus_revision),
    ).fetchone()
    # 允许集合 = 截至该 corpus_revision 的累积语料（与检索同一快照语义）。
    if row is None:
        raise DomainError(
            "EVIDENCE_INVALID",
            "chunk is not part of the current project corpus revision",
            {"chunk_id": proposal.chunk_id},
        )
    quote = proposal.quote
    occurrences = _count_occurrences(row["text"], quote)
    if occurrences == 0:
        raise DomainError(
            "EVIDENCE_INVALID",
            "quote is not an exact substring of the chunk text",
            {"chunk_id": proposal.chunk_id},
        )
    if occurrences > 1:
        raise DomainError(
            "EVIDENCE_INVALID",
            "ambiguous quote: appears multiple times in chunk, more context required",
            {"chunk_id": proposal.chunk_id, "occurrences": occurrences},
        )
    start = row["text"].index(quote)
    return EvidenceSpan(
        chunk_id=proposal.chunk_id,
        document_id=row["document_id"],
        pdf_page=row["pdf_page"],
        start=start,
        end=start + len(quote),
        quote=quote,
    )


def _count_occurrences(text: str, quote: str) -> int:
    """重叠出现按多次计（review N2）：str.count 非重叠会漏判
    "aba"∈"ababa" 这类歧义，漏判后取第一次违背 docs/04 §19。"""
    count = 0
    start = text.find(quote)
    while start != -1:
        count += 1
        start = text.find(quote, start + 1)
    return count
