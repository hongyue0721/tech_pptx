// 稳定操作幂等键：键由"操作意图 + 业务锚点"派生，同一操作重试（含刷新后重发）
// 必须是同一个键；结果未知时绝不换键。随机键只在无业务锚点的一次性意图时使用。

function hashParts(raw: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < raw.length; i++) {
    const c = raw.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 16777619) >>> 0;
    h2 = Math.imul(h2 + c, 0x5bd1e995) >>> 0;
  }
  return (h1.toString(36) + h2.toString(36)).padStart(13, "0");
}

function stableKey(scope: string, ...parts: (string | number)[]): string {
  const key = `${scope}_${hashParts(parts.join("|"))}`;
  return key.slice(0, 128);
}

export function createProjectKey(formFingerprint: string): string {
  return stableKey("create", formFingerprint);
}

export function uploadMaterialKey(
  projectId: string,
  fileName: string,
  fileSize: number,
  fileModifiedMs: number,
): string {
  return stableKey("upload", projectId, fileName, fileSize, fileModifiedMs);
}

export function planCreateKey(
  projectId: string,
  corpusRevision: number,
  attempt: number,
): string {
  return stableKey("plan", projectId, corpusRevision, attempt);
}

export function planConfirmKey(
  projectId: string,
  planId: string,
  payloadCanonical: string,
): string {
  return stableKey("confirm", projectId, planId, payloadCanonical);
}

export function generateKey(
  projectId: string,
  planId: string,
  baseVersion: number,
  corpusRevision: number,
  attempt: number,
): string {
  return stableKey("gen", projectId, planId, baseVersion, corpusRevision, attempt);
}

export function commitKey(projectId: string, changeId: string): string {
  return stableKey("commit", projectId, changeId);
}

export function cancelJobKey(jobId: string): string {
  return stableKey("cancel", jobId);
}

// 幂等重放要求同载荷同键：对确认载荷做键序稳定的规范化序列化。
export function canonicalize(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalize).join(",")}]`;
  }
  const entries = Object.keys(value as Record<string, unknown>)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canonicalize((value as Record<string, unknown>)[k])}`);
  return `{${entries.join(",")}}`;
}
