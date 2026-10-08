import unicodedata


def normalize_page_text(raw: str) -> str:
    """docs/04 §15 固定归一化：CRLF/CR→LF、删 NUL、Unicode NFC、整页首尾 strip。

    不折叠正文空格、不改数字、不合并跨页内容。修改此算法必须提升
    extractor_version 并重建索引，否则旧引用偏移会静默失效。
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    text = unicodedata.normalize("NFC", text)
    return text.strip()
