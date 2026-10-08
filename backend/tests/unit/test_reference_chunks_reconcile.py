"""reference_chunks.json 对账（测试侧 fixture 校验，不进运行路径，AGENTS.md §8）。

验证两件事：
1. 包内参考切块的 页码/偏移/hash 对锁定 pypdf 5.9.0 + 固定归一化仍然成立（回归 T02 探针）；
2. 参考条目符合 DocumentChunk 契约模型。
"""

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from courseware_core.materials.normalize import normalize_page_text
from courseware_core.models import DocumentChunk

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
REFERENCE = DEMO / "expected" / "reference_chunks.json"


@pytest.fixture(scope="module")
def reference_chunks() -> list[dict]:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def page_texts() -> dict:
    out = {}
    for name in ("01_stm32_interrupt_notes.pdf", "02_priority_casebook.pdf"):
        reader = PdfReader(DEMO / "inputs" / name)
        out[name] = {
            i + 1: normalize_page_text(p.extract_text() or "")
            for i, p in enumerate(reader.pages)
        }
    return out


def test_reference_offsets_hold_on_normalized_text(reference_chunks, page_texts):
    assert len(reference_chunks) == 12
    for ch in reference_chunks:
        page = page_texts[ch["document_name"]][ch["pdf_page"]]
        assert page[ch["page_start"] : ch["page_end"]] == ch["text"], ch["chunk_id"]


def test_reference_text_hashes_hold(reference_chunks):
    for ch in reference_chunks:
        assert (
            hashlib.sha256(ch["text"].encode("utf-8")).hexdigest() == ch["text_sha256"]
        ), ch["chunk_id"]


def test_reference_entries_satisfy_contract_model(reference_chunks):
    for ch in reference_chunks:
        model = DocumentChunk.model_validate(ch)
        assert model.page_end > model.page_start
        assert len(model.text) <= 1200


def test_reference_quotes_are_unique_substrings(reference_chunks, page_texts):
    """quote 在页内唯一（EvidenceSpan 定位前提，docs/04 §19）。"""
    for ch in reference_chunks:
        page = page_texts[ch["document_name"]][ch["pdf_page"]]
        assert page.count(ch["text"]) == 1, ch["chunk_id"]
