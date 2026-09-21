import type { ErrorResponse } from "../types/models";

const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  readonly code: string;
  readonly requestId: string;
  readonly details: Record<string, unknown>;
  readonly status: number;

  constructor(status: number, body: ErrorResponse) {
    super(body.error.message);
    this.code = body.error.code;
    this.requestId = body.error.request_id;
    this.details = body.error.details ?? {};
    this.status = status;
  }
}

function newRequestId(): string {
  return `web_${crypto.randomUUID()}`.slice(0, 128);
}

// 网关/代理可能返回非 JSON（如 HTML 502）：解析失败不得抛 SyntaxError 穿透
// 到教师可见文案，按状态码构造兜底错误。request 与 fetchForm 共用（单一来源）。
export async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null;
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    const requestId = response.headers.get("x-request-id") ?? "";
    if (!response.ok) {
      throw new ApiError(response.status, {
        error: {
          code: "HTTP_" + response.status,
          message: `服务返回了无法解析的响应（HTTP ${response.status}）`,
          request_id: requestId,
          details: {},
        },
      });
    }
    throw new ApiError(response.status, {
      error: {
        code: "MALFORMED_SUCCESS",
        message: "服务返回了无法解析的成功响应，操作结果未知，请刷新核对状态",
        request_id: requestId,
        details: {},
      },
    });
  }
  if (!response.ok) {
    throw new ApiError(response.status, payload as ErrorResponse);
  }
  return payload;
}

export async function request<T>(
  method: string,
  path: string,
  options: { body?: unknown; idempotencyKey?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const headers: Record<string, string> = { "X-Request-ID": newRequestId() };
  if (options.idempotencyKey !== undefined) {
    headers["Idempotency-Key"] = options.idempotencyKey;
  }
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API_PREFIX}${path}`, {
    method,
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  return (await parseResponse(response)) as T;
}

export const api = {
  getHealth: (signal?: AbortSignal) =>
    request<import("../types/models").Health>("GET", "/health", { signal }),
  createProject: (
    body: import("../types/models").CreateProjectRequest,
    idempotencyKey: string,
  ) => request<import("../types/models").Project>("POST", "/projects", { body, idempotencyKey }),
  getProject: (projectId: string, signal?: AbortSignal) =>
    request<import("../types/models").Project>(
      "GET",
      `/projects/${encodeURIComponent(projectId)}`,
      { signal },
    ),
  deleteProject: (projectId: string, idempotencyKey: string) =>
    request<null>("DELETE", `/projects/${encodeURIComponent(projectId)}`, {
      body: { acknowledged: true },
      idempotencyKey,
    }),
};
