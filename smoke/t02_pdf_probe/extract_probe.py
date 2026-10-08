"""T02 pypdf 中文抽取探针：对包内正例讲义做逐物理页文本抽取并输出质量报告。"""
import json
import hashlib
from pathlib import Path

from pypdf import PdfReader

PDF = Path(__file__).resolve().parents[2] / "demo-data/inputs/01_stm32_interrupt_notes.pdf"

reader = PdfReader(PDF)
pages = len(reader.pages)
report = {"extractor": f"pypdf {__import__('pypdf').__version__}", "pdf_pages": pages, "pages": []}
total_chars = 0
for i, page in enumerate(reader.pages, start=1):
    text = page.extract_text() or ""
    stripped = text.strip()
    normalized = stripped.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    report["pages"].append({
        "pdf_page": i,
        "chars": len(normalized),
        "sha256": digest,
        "has_chinese": any("\u4e00" <= c <= "\u9fff" for c in normalized),
        "head": normalized[:60],
    })
    total_chars += len(normalized)
report["total_chars"] = total_chars
print(json.dumps(report, ensure_ascii=False, indent=2))
