"""页内切块（docs/04 §17）：永不跨物理页，优先段落/句子边界。

目标 600—900 字符、硬上限 1200；重叠上限 100 但 P0 取 0（偏移自洽更易验证，
chunk.text 恒等于归一化页文本的连续子串）。短页不强行拼页。
"""

import hashlib
import secrets

from courseware_core.models import DocumentChunk

from .normalize import normalize_page_text
from .parser import EXTRACTOR_VERSION, ParsedPage

CHUNK_TARGET_MAX = 900
CHUNK_MAX_CHARS = 1200
# 硬换行（\n）不是句子边界：pypdf 抽取的正文存在句中断行（"重\n点"），
# 以 \n 断句会把词切碎，故句子终止符只取中英文句读。
_SENTENCE_ENDS = frozenset("。！？；!?;")
# 切块策略版本；T06 的分词索引另有自己的 tokenizer 版本，两者独立演进。
CHUNKER_TOKENIZER_VERSION = "chunker-v1"


def split_page(
    page: ParsedPage,
    *,
    project_id: str,
    document_id: str,
    document_name: str,
    corpus_revision: int,
) -> list[DocumentChunk]:
    text = normalize_page_text(page.text)
    if not text:
        return []

    spans: list[tuple[int, int]] = []
    cur_s: int | None = None
    cur_e: int | None = None

    def flush() -> None:
        nonlocal cur_s, cur_e
        if cur_s is not None and cur_e is not None:
            spans.append((cur_s, cur_e))
            cur_s = cur_e = None

    for ps, pe in _paragraph_spans(text):
        if pe - ps > CHUNK_MAX_CHARS:
            flush()
            spans.extend(_merge_sentence_spans(text, ps, pe))
        elif cur_s is None:
            cur_s, cur_e = ps, pe
        elif pe - cur_s <= CHUNK_TARGET_MAX:
            cur_e = pe
        else:
            flush()
            cur_s, cur_e = ps, pe
    flush()

    return [
        _make_chunk(
            text[s:e],
            page_start=s,
            page_end=e,
            project_id=project_id,
            document_id=document_id,
            document_name=document_name,
            corpus_revision=corpus_revision,
            pdf_page=page.pdf_page,
            printed_page_label=page.printed_page_label,
        )
        for s, e in spans
    ]


def _make_chunk(
    chunk_text: str,
    *,
    page_start: int,
    page_end: int,
    project_id: str,
    document_id: str,
    document_name: str,
    corpus_revision: int,
    pdf_page: int,
    printed_page_label: str | None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"chk_{secrets.token_hex(12)}",
        project_id=project_id,
        document_id=document_id,
        corpus_revision=corpus_revision,
        document_name=document_name,
        pdf_page=pdf_page,
        printed_page_label=printed_page_label,
        page_start=page_start,
        page_end=page_end,
        text=chunk_text,
        text_sha256=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        extractor_version=EXTRACTOR_VERSION,
        tokenizer_version=CHUNKER_TOKENIZER_VERSION,
    )


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """以空行（\\n\\n）分段，返回去段尾空白后的有效 span。"""
    spans: list[tuple[int, int]] = []
    n = len(text)
    i = 0
    while i < n:
        while i < n and text[i] == "\n":
            i += 1
        if i >= n:
            break
        j = text.find("\n\n", i)
        if j == -1:
            j = n
        k = j
        while k > i and text[k - 1] in " \t":
            k -= 1
        spans.append((i, k))
        i = j
    return spans


def _merge_sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """超长段落：先按句子切开，再贪心合并到目标带；单句超硬上限按字符强切。"""
    sentences: list[tuple[int, int]] = []
    s = start
    for i in range(start, end):
        if text[i] in _SENTENCE_ENDS:
            if i + 1 - s > CHUNK_MAX_CHARS:
                sentences.extend(_hard_cut(s, i + 1))
            else:
                sentences.append((s, i + 1))
            s = i + 1
    if s < end:
        if end - s > CHUNK_MAX_CHARS:
            sentences.extend(_hard_cut(s, end))
        else:
            sentences.append((s, end))

    merged: list[tuple[int, int]] = []
    cur_s: int | None = None
    cur_e: int | None = None
    for ss, se in sentences:
        if cur_s is None:
            cur_s, cur_e = ss, se
        elif se - cur_s <= CHUNK_TARGET_MAX:
            cur_e = se
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = ss, se
    if cur_s is not None:
        merged.append((cur_s, cur_e))
    return merged


def _hard_cut(start: int, end: int) -> list[tuple[int, int]]:
    return [
        (j, min(j + CHUNK_MAX_CHARS, end)) for j in range(start, end, CHUNK_MAX_CHARS)
    ]
