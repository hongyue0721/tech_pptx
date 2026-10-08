"""分词：中文 jieba 与英文/代码标识符并行保留（docs/05 §9）。

不把 NVIC_SetPriority 切成无意义碎片：ASCII 标识符整词保留（小写化做
大小写不敏感匹配），中文段交给 jieba。分词版本变更必须同步索引重建。
"""

import re

import jieba

jieba.setLogLevel(60)

TOKENIZER_VERSION = "jieba-0.42.1+ascii-v1"

_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    tokens: list[str] = []
    masked = list(text)
    for match in _ASCII_RE.finditer(text):
        tokens.append(match.group(0).lower())
        for index in range(match.start(), match.end()):
            masked[index] = " "
    ascii_count = len(tokens)
    cjk = [
        word.strip()
        for word in jieba.lcut("".join(masked))
        # 单字中文词信息量低且极易跨主题误命中（如"波""测"），过滤之；
        # 语义级判断留给 L3 核验，检索层不承担。
        if len(word.strip()) >= 2 and _CJK_RE.search(word)
    ]
    tokens.extend(cjk)
    if not cjk and ascii_count == 0:
        # 全单字中文查询（如目标"熵"）：多字过滤会误伤成恒空，兜底保留单字。
        tokens.extend(char for char in text if _CJK_RE.match(char))
    return tokens
