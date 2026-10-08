from pathlib import Path

import pytest

from courseware_core.errors import DomainError
from courseware_core.materials.parser import ParseLimits, parse_pdf

DEMO = Path(__file__).resolve().parents[3] / "demo-data"
INPUTS = DEMO / "inputs"
NEGATIVE = DEMO / "negative"


def test_normal_notes_parses_all_pages_with_text():
    doc = parse_pdf(INPUTS / "01_stm32_interrupt_notes.pdf", ParseLimits())
    assert doc.pdf_pages >= 1
    assert doc.usable_pages == doc.pdf_pages
    assert all(p.text for p in doc.pages)
    assert doc.pages[0].pdf_page == 1


def test_parsed_text_is_normalized():
    doc = parse_pdf(INPUTS / "02_priority_casebook.pdf", ParseLimits())
    for page in doc.pages:
        assert "\r" not in page.text
        assert "\x00" not in page.text
        assert page.text == page.text.strip()


def test_encrypted_rejected_without_password():
    with pytest.raises(DomainError) as exc:
        parse_pdf(NEGATIVE / "encrypted.pdf", ParseLimits())
    assert exc.value.code == "PDF_ENCRYPTED"


def test_malformed_rejected_as_unsupported():
    with pytest.raises(DomainError) as exc:
        parse_pdf(NEGATIVE / "malformed.pdf", ParseLimits())
    assert exc.value.code == "UNSUPPORTED_FILE"


def test_non_pdf_bytes_rejected(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"just some text, not a pdf at all")
    with pytest.raises(DomainError) as exc:
        parse_pdf(fake, ParseLimits())
    assert exc.value.code == "UNSUPPORTED_FILE"


def test_blank_document_raises_text_unavailable():
    with pytest.raises(DomainError) as exc:
        parse_pdf(NEGATIVE / "blank.pdf", ParseLimits())
    assert exc.value.code == "PDF_TEXT_UNAVAILABLE"


def test_scanned_only_raises_text_unavailable_with_page_warning():
    with pytest.raises(DomainError) as exc:
        parse_pdf(NEGATIVE / "scanned_only.pdf", ParseLimits())
    assert exc.value.code == "PDF_TEXT_UNAVAILABLE"


def test_mixed_file_parses_with_per_page_warnings():
    doc = parse_pdf(NEGATIVE / "mixed_text_scan.pdf", ParseLimits())
    assert doc.pdf_pages == 2
    assert doc.usable_pages == 1
    scan_pages = [w for p in doc.pages for w in p.warnings if w.code == "SCAN_DETECTED"]
    assert len(scan_pages) == 1
    assert scan_pages[0].pdf_page == 2
    assert list(doc.pages[0].warnings) == []


def test_page_limit_exceeded_rejected():
    with pytest.raises(DomainError) as exc:
        parse_pdf(INPUTS / "01_stm32_interrupt_notes.pdf", ParseLimits(max_pages=1))
    assert exc.value.code == "PAGE_LIMIT_EXCEEDED"


def test_char_limit_exceeded_rejected():
    with pytest.raises(DomainError) as exc:
        parse_pdf(INPUTS / "01_stm32_interrupt_notes.pdf", ParseLimits(max_chars=10))
    assert exc.value.code == "EXTRACTION_LIMIT_EXCEEDED"


def test_page_warnings_have_readable_message():
    doc = parse_pdf(NEGATIVE / "mixed_text_scan.pdf", ParseLimits())
    warning = doc.pages[1].warnings[0]
    assert warning.message
    assert warning.pdf_page == 2
