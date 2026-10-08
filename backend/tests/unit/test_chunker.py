import hashlib

from courseware_core.materials.chunker import (
    CHUNK_MAX_CHARS,
    CHUNK_TARGET_MAX,
    split_page,
)
from courseware_core.materials.normalize import normalize_page_text
from courseware_core.materials.parser import parse_pdf
from courseware_core.models import DocumentChunk
from pathlib import Path

DEMO_INPUTS = Path(__file__).resolve().parents[3] / "demo-data" / "inputs"


def make_page(text: str):
    from courseware_core.materials.parser import ParsedPage

    return ParsedPage(pdf_page=1, text=normalize_page_text(text), warnings=())


def chunks_for(text: str) -> list[DocumentChunk]:
    page = make_page(text)
    return split_page(
        page,
        project_id="prj_t",
        document_id="doc_t",
        document_name="t.pdf",
        corpus_revision=1,
    )


def assert_offsets_selfconsistent(page_text: str, chunks: list[DocumentChunk]):
    page = normalize_page_text(page_text)
    for ch in chunks:
        assert page[ch.page_start : ch.page_end] == ch.text
        assert hashlib.sha256(ch.text.encode()).hexdigest() == ch.text_sha256
        assert ch.pdf_page == 1


def test_short_page_single_chunk():
    chunks = chunks_for("很短的一段中文教材内容。")
    assert len(chunks) == 1
    assert chunks[0].text == "很短的一段中文教材内容。"
    assert chunks[0].page_start == 0
    assert chunks[0].page_end == len(chunks[0].text)


def test_empty_page_no_chunks():
    assert chunks_for("   \n\n  ") == []


def test_long_paragraphs_split_within_limits():
    para = "中断是处理器暂停当前程序转去处理事件的机制。" * 60  # ~1080 chars
    text = "\n\n".join(f"段落{i}：{para}" for i in range(5))
    chunks = chunks_for(text)
    assert len(chunks) >= 5
    for ch in chunks:
        assert len(ch.text) <= CHUNK_MAX_CHARS
    assert_offsets_selfconsistent(text, chunks)


def test_chunk_sizes_near_target():
    para = "优先级分组决定抢占与子优先级的位数分配。" * 40  # ~840 chars per para
    text = "\n\n".join(para for _ in range(4))
    chunks = chunks_for(text)
    for ch in chunks:
        assert len(ch.text) <= CHUNK_TARGET_MAX + 300  # 目标带，允许句子级溢出到硬上限


def test_oversized_single_sentence_hard_cut():
    text = "字" * 2500
    chunks = chunks_for(text)
    assert all(len(ch.text) <= CHUNK_MAX_CHARS for ch in chunks)
    assert_offsets_selfconsistent(text, chunks)
    assert sum(len(ch.text) for ch in chunks) == 2500  # 零重叠：覆盖不重复


def test_no_overlap_between_chunks():
    para = "句子内容测试。" * 90
    text = "\n\n".join(f"第{i}段。{para}" for i in range(4))
    chunks = chunks_for(text)
    spans = sorted((ch.page_start, ch.page_end) for ch in chunks)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert e1 <= s2  # 页内互不重叠（P0 重叠=0，docs/04 上限100）


def test_real_notes_page_offsets_hold():
    doc = parse_pdf(DEMO_INPUTS / "01_stm32_interrupt_notes.pdf")
    page = doc.pages[0]
    chunks = split_page(
        page,
        project_id="prj_r",
        document_id="doc_r",
        document_name="01_stm32_interrupt_notes.pdf",
        corpus_revision=1,
    )
    assert chunks
    for ch in chunks:
        assert page.text[ch.page_start : ch.page_end] == ch.text
        assert ch.extractor_version
        assert ch.tokenizer_version


def test_chunk_ids_unique_and_metadata_bound():
    text = "\n\n".join("内容块。" * 200 for _ in range(3))
    chunks = chunks_for(text)
    ids = [ch.chunk_id for ch in chunks]
    assert len(ids) == len(set(ids))
    assert all(ch.project_id == "prj_t" and ch.document_id == "doc_t" for ch in chunks)
    assert all(ch.corpus_revision == 1 for ch in chunks)
