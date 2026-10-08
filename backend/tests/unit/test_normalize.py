from courseware_core.materials.normalize import normalize_page_text


def test_crlf_and_cr_become_lf():
    assert normalize_page_text("a\r\nb\rc\n") == "a\nb\nc"


def test_nul_removed():
    assert normalize_page_text("a\x00b") == "ab"


def test_unicode_nfc_composed():
    decomposed = "é"  # e + combining acute
    assert normalize_page_text(decomposed) == "é"


def test_strip_edges_only():
    assert normalize_page_text("  \n\n abc \n  ") == "abc"


def test_internal_spaces_not_collapsed():
    assert normalize_page_text("a  b   c") == "a  b   c"


def test_digits_unchanged():
    assert normalize_page_text("12,000 50.000") == "12,000 50.000"


def test_idempotent():
    once = normalize_page_text("a\r\nb  \x00c ")
    assert normalize_page_text(once) == once
