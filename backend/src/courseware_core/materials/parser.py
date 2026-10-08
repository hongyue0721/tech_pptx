"""受控 PDF 文本抽取（docs/11 §5-§11、docs/04 §11-§17）。

纯解析：无网络、无 LLM、无跨页合并、不写 DB。输出逐页归一化文本与质量警告。
仅支持文本层 PDF，不做 OCR；混合文件逐页告警，不声称没文本的页已读完。
"""

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from courseware_core.errors import DomainError
from courseware_core.models import PageWarning

from .normalize import normalize_page_text

# 抽取算法版本：归一化/抽取逻辑任何改变都必须提升该值并重建索引（docs/04 §15）。
EXTRACTOR_VERSION = "pypdf-5.9.0-nfc-v1"

# docs/11 §7 产品限额的单一事实源；ProjectLimits 默认值引用此处，避免双份漂移（N14）。
PROJECT_MAX_PAGES = 200
PROJECT_MAX_CHARS = 500_000


@dataclass(frozen=True)
class ParsedPage:
    pdf_page: int
    text: str
    warnings: tuple[PageWarning, ...]
    printed_page_label: str | None = None


@dataclass(frozen=True)
class ParsedDocument:
    pages: tuple[ParsedPage, ...]

    @property
    def pdf_pages(self) -> int:
        return len(self.pages)

    @property
    def usable_pages(self) -> int:
        return sum(1 for p in self.pages if p.text)


@dataclass(frozen=True)
class ParseLimits:
    max_pages: int = PROJECT_MAX_PAGES
    max_chars: int = PROJECT_MAX_CHARS


def parse_pdf(path: Path, limits: ParseLimits = ParseLimits()) -> ParsedDocument:
    # 不吞 OSError：原件缺失/IO 故障属内部不一致，应冒泡给调用方收口
    # （service 兜底标 INTERNAL_ERROR），伪装成 UNSUPPORTED_FILE 会掩盖事实。
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise DomainError("UNSUPPORTED_FILE", "file is not a PDF by structure, not just extension")
    try:
        reader = PdfReader(str(path))
    except (PdfReadError, ValueError, OSError) as exc:
        raise DomainError("UNSUPPORTED_FILE", "unreadable PDF structure") from exc
    if reader.is_encrypted:
        # 拒绝加密文件，不尝试任何密码（docs/11 §9）。
        raise DomainError("PDF_ENCRYPTED", "encrypted PDFs are rejected")

    pages = reader.pages
    if len(pages) > limits.max_pages:
        raise DomainError(
            "PAGE_LIMIT_EXCEEDED",
            f"document exceeds the page allowance",
        )

    parsed: list[ParsedPage] = []
    total_chars = 0
    for index, page in enumerate(pages):
        try:
            text = normalize_page_text(page.extract_text() or "")
        except Exception:  # 单页解析失败按无文本处理并告警，不中断整本
            text = ""
            warning = PageWarning(
                pdf_page=index + 1,
                code="PAGE_PARSE_ERROR",
                message="page extraction failed and was skipped",
            )
            parsed.append(ParsedPage(pdf_page=index + 1, text="", warnings=(warning,)))
            continue
        total_chars += len(text)
        if total_chars > limits.max_chars:
            # 字符限额独立错误码（N2）：不冒充页限额。
            raise DomainError(
                "EXTRACTION_LIMIT_EXCEEDED",
                "extracted characters exceed the project allowance",
            )
        warnings: list[PageWarning] = []
        if not text:
            if _page_has_image(page):
                warnings.append(
                    PageWarning(
                        pdf_page=index + 1,
                        code="SCAN_DETECTED",
                        message="page has no extractable text layer (image content); OCR not performed",
                    )
                )
            else:
                warnings.append(
                    PageWarning(
                        pdf_page=index + 1,
                        code="EMPTY_PAGE",
                        message="page contains no extractable text",
                    )
                )
        parsed.append(
            ParsedPage(pdf_page=index + 1, text=text, warnings=tuple(warnings))
        )

    if not any(p.text for p in parsed):
        # 空白与扫描型返回明确错误（docs/11 §9），混合文件不走此分支。
        raise DomainError(
            "PDF_TEXT_UNAVAILABLE",
            "document has no extractable text on any page",
        )
    return ParsedDocument(pages=tuple(parsed))


def _page_has_image(page) -> bool:
    """低层 XObject 检测图片页；不用 page.images（依赖 Pillow，不在冻结栈内）。"""
    try:
        resources = page.get("/Resources")
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        if not resources:
            return False
        xobjects = resources.get("/XObject")
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        if not xobjects:
            return False
        for name in xobjects:
            obj = xobjects[name]
            obj = obj.get_object() if hasattr(obj, "get_object") else obj
            if str(obj.get("/Subtype")) == "/Image":
                return True
    except Exception:
        # 有意的宽兜底（N15）：资源字典结构异常时按"无图片"处理，
        # 该页若也无文本则落 EMPTY_PAGE——两种告警都不声称"读完了内容"。
        return False
    return False
