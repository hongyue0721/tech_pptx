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

async function request<T>(
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
  if (response.status === 204) {
    return null as T;
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiError(response.status, payload as ErrorResponse);
  }
  return payload as T;
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
