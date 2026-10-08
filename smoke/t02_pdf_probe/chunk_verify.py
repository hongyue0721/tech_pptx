"""T02 探针对账：将本次抽取与包内 reference_chunks.json（pypdf-demo-nfc-v1 产物）比对。"""
import json
from pathlib import Path

from pypdf import PdfReader

BASE = Path(__file__).resolve().parents[2]
notes = PdfReader(f"{BASE}/demo-data/inputs/01_stm32_interrupt_notes.pdf")
cases = PdfReader(f"{BASE}/demo-data/inputs/02_priority_casebook.pdf")
page_text = {
    "notes": {(i + 1): (p.extract_text() or "") for i, p in enumerate(notes.pages)},
    "cases": {(i + 1): (p.extract_text() or "") for i, p in enumerate(cases.pages)},
}
chunks = json.load(open(f"{BASE}/demo-data/expected/reference_chunks.json"))
result = []
for ch in chunks:
    doc = "notes" if ch["document_id"].startswith("doc_notes") else "cases"
    text = page_text[doc][ch["pdf_page"]]
    # 验证偏移处文本与chunk逐字符一致
    sliced = text[ch["page_start"]:ch["page_end"]]
    match = sliced == ch["text"]
    # 验证text_sha256
    import hashlib
    h = hashlib.sha256(ch["text"].encode("utf-8")).hexdigest()
    result.append({
        "chunk_id": ch["chunk_id"],
        "offset_match": match,
        "hash_match": h == ch["text_sha256"],
        "len": len(ch["text"]),
    })
ok = all(r["offset_match"] and r["hash_match"] for r in result)
print(json.dumps({"chunks": len(result), "all_match": ok, "detail": result[:4]}, ensure_ascii=False, indent=2))
