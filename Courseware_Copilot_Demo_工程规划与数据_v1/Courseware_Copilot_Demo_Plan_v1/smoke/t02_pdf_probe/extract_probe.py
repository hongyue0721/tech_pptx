"""T02 pypdf 中文抽取探针：对包内正例讲义做逐物理页文本抽取并输出质量报告。"""
import json
import sys
import hashlib

sys.path.insert(0, "/home/hongyue/.cache/uv/archive-v0/eLs9Ods-FqgczIHp")
from pypdf import PdfReader

PDF = "/home/hongyue/Projects/ppt_edit/Courseware_Copilot_Demo_工程规划与数据_v1/Courseware_Copilot_Demo_Plan_v1/demo-data/inputs/01_stm32_interrupt_notes.pdf"

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
