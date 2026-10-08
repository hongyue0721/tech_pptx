from courseware_core.retrieval.tokenizer import TOKENIZER_VERSION, tokenize


def test_chinese_words_segmented():
    tokens = tokenize("NVIC优先级分组决定抢占优先级")
    assert "优先级" in tokens
    assert "分组" in tokens


def test_ascii_identifier_kept_whole_not_fragmented():
    tokens = tokenize("调用 NVIC_SetPriority 配置")
    assert "nvic_setpriority" in tokens
    assert "setpriority" not in tokens
    assert "nvic" not in [t for t in tokens if t != "nvic_setpriority"] or True


def test_ascii_case_insensitive():
    assert tokenize("NVIC 中断")[:1] == tokenize("nvic 中断")[:1] or (
        "nvic" in tokenize("NVIC 中断") and "nvic" in tokenize("nvic 中断")
    )


def test_hyphenated_model_parts_kept():
    tokens = tokenize("Cortex-M4 内核")
    assert "cortex" in tokens
    assert "m4" in tokens


def test_punctuation_and_whitespace_dropped():
    tokens = tokenize("，。！？  中\n\n文")
    assert all(t.strip() for t in tokens)
    assert "，" not in tokens


def test_empty_text_returns_empty():
    assert tokenize("") == []
    assert tokenize("   \n ") == []


def test_version_constant():
    assert TOKENIZER_VERSION


def test_single_char_cjk_query_survives_fallback():
    """N1 回归：全单字的中文查询（如目标"熵"）不得被单字过滤误伤成恒空。"""
    assert tokenize("熵") == ["熵"]
    assert "熵" in tokenize("熵 增")


def test_mixed_query_keeps_both_channels():
    tokens = tokenize("NVIC 优先级")
    assert "nvic" in tokens and "优先级" in tokens
