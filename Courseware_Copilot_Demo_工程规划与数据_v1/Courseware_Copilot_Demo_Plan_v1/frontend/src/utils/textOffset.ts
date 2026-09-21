// 服务器契约：EvidenceSpan.start/end 是归一化文本的 Python 码点偏移；
// JS 字符串索引是 UTF-16 码元。含非 BMP 字符（emoji、扩展汉字）时两者错位，
// 一律经 Array.from 转码点数组换算，禁止直接 slice/indexOf 高亮。

export interface OffsetSegments {
  before: string;
  middle: string;
  after: string;
}

export function codePointSplit(text: string, start: number, end: number): OffsetSegments {
  const chars = Array.from(text);
  const s = Math.max(0, Math.min(start, chars.length));
  const e = Math.max(s, Math.min(end, chars.length));
  return {
    before: chars.slice(0, s).join(""),
    middle: chars.slice(s, e).join(""),
    after: chars.slice(e).join(""),
  };
}
