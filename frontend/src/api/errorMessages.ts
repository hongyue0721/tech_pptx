// 错误码 → 教师可读文案。契约真源：api.md「错误码与HTTP语义」表。
// 原则：只翻译，不改写事实；未知码回落到服务器 message，绝不编造"成功式"安抚文案。

import { ApiError } from "./client";
import type { Job } from "../types/models";

interface ErrorCopy {
  message: string;
  retryable: boolean;
}

const ERROR_COPY: Record<string, ErrorCopy> = {
  UNAUTHORIZED: { message: "登录状态失效，请重新验证后再操作。", retryable: false },
  PROJECT_NOT_FOUND: { message: "该项目不存在或已被删除。", retryable: false },
  DECK_NOT_FOUND: { message: "还没有可用的正式课件版本。", retryable: false },
  ARTIFACT_NOT_FOUND: { message: "要下载的文件不存在，请重新生成后再试。", retryable: false },
  PLAN_NOT_FOUND: { message: "找不到这份大纲，请返回资料页重新生成。", retryable: false },
  CHANGE_NOT_FOUND: { message: "找不到这份候选课件，请重新生成。", retryable: false },
  EVIDENCE_NOT_FOUND: {
    message: "这段依据在当前资料版本里已找不到，请刷新资料后重试。",
    retryable: false,
  },
  // —— 以下码后端实际可发但 api.md 表未列（全量 Review D-07）：前端先兜底翻译，
  // api.md 是否补行为契约决策已登记待负责人拍板；不改动事实，只翻译。
  JOB_NOT_FOUND: { message: "找不到这个任务，请刷新页面核对状态。", retryable: false },
  EXTRACTION_LIMIT_EXCEEDED: {
    message: "资料提取内容超出处理上限，请精简文件后重新上传。",
    retryable: false,
  },
  WORKER_ALREADY_RUNNING: {
    message: "后台处理服务已在运行，本次操作未能执行，请稍后重试。",
    retryable: true,
  },
  ARTIFACT_INTEGRITY: {
    message: "文件完整性校验不通过，该产物不可用，请重新生成。",
    retryable: false,
  },
  INTERNAL_ERROR: { message: "服务内部错误，操作未完成，请稍后重试。", retryable: true },
  NOT_FOUND: { message: "请求的内容不存在，请刷新页面核对。", retryable: false },
  METHOD_NOT_ALLOWED: { message: "该操作不被支持，请通过页面按钮操作。", retryable: false },
  MALFORMED_SUCCESS: {
    message: "服务返回了无法解析的响应，操作结果未知，请刷新核对状态。",
    retryable: false,
  },
  PAYLOAD_TOO_LARGE: {
    message: "文件数量或大小超出限制（单份 ≤20MiB、最多 5 份），请精简资料。",
    retryable: false,
  },
  PAGE_LIMIT_EXCEEDED: { message: "资料页数超出限制，请精简后重新上传。", retryable: false },
  UNSUPPORTED_FILE: { message: "这个文件不是可解析的 PDF，请更换资料。", retryable: false },
  PDF_ENCRYPTED: { message: "PDF 已加密无法读取内容，请上传未加密版本。", retryable: false },
  PDF_TEXT_UNAVAILABLE: {
    message: "PDF 没有可提取的文字层（可能是纯扫描件），解析结果会不完整。",
    retryable: false,
  },
  VALIDATION_ERROR: { message: "提交的内容不符合要求，请检查后重试。", retryable: true },
  EDIT_UNSUPPORTED: { message: "这种修改暂不支持。", retryable: false },
  IDEMPOTENCY_CONFLICT: {
    message: "同一操作标识被用于不同请求，请刷新后重新操作。",
    retryable: false,
  },
  VERSION_CONFLICT: {
    message: "课件已被其他操作更新，请重新读取最新版本后再确认。",
    retryable: false,
  },
  CORPUS_CHANGED: {
    message: "资料内容已变化，请基于最新资料重新生成。",
    retryable: false,
  },
  PROJECT_BUSY: {
    message: "项目正有其他任务在处理，请等当前任务结束后再操作。",
    retryable: true,
  },
  PLAN_NOT_CONFIRMED: {
    message: "大纲还没有教师确认，请先在大纲页完成确认。",
    retryable: false,
  },
  CHANGE_NOT_COMMITTABLE: {
    message: "这份候选没有通过全部核验，暂时不能应用。",
    retryable: false,
  },
  CONSENT_REQUIRED: {
    message: "需要先确认云处理告知，再创建项目。",
    retryable: false,
  },
  INSUFFICIENT_EVIDENCE: {
    message: "资料不足以支撑这些目标，请补充资料后重试。",
    retryable: false,
  },
  EVIDENCE_CONFLICT: { message: "资料之间存在矛盾，请先人工核对来源。", retryable: false },
  EVIDENCE_INVALID: { message: "部分依据定位失败，请检查资料后重试。", retryable: false },
  MODEL_AUTH_ERROR: { message: "模型服务鉴权失败，请联系管理员检查配置。", retryable: false },
  MODEL_PROTOCOL_ERROR: { message: "模型服务响应异常，请稍后重试。", retryable: true },
  MODEL_RATE_LIMIT: { message: "模型服务当前限流，请稍候片刻再重试。", retryable: true },
  MODEL_TIMEOUT: { message: "模型服务响应超时，请稍后重试。", retryable: true },
  MODEL_UNAVAILABLE: { message: "模型服务暂时不可用，请稍后重新发起。", retryable: true },
  MODEL_OUTPUT_INVALID: {
    message: "模型输出格式校验未通过，请重新发起生成。",
    retryable: true,
  },
  BUDGET_EXCEEDED: {
    message: "本次模型调用预算已用完，请调整预算或减少重试。",
    retryable: false,
  },
  EXPORT_FAILED: { message: "导出失败，课件版本未受影响，可重试导出。", retryable: true },
  PREVIEW_FAILED: { message: "预览生成失败，课件版本未受影响。", retryable: true },
  JOB_INTERRUPTED: { message: "任务被中断，未产生结果，请重新发起。", retryable: true },
  CANCELLED: { message: "任务已取消。", retryable: false },
};

const FALLBACK: ErrorCopy = { message: "操作没有成功，请稍后重试。", retryable: true };

export function describeError(err: unknown): ErrorCopy {
  if (!(err instanceof ApiError)) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return { message: "请求已取消。", retryable: false };
    }
    if (err instanceof TypeError) {
      return { message: "网络连接失败，请检查网络后重试。", retryable: true };
    }
    return { ...FALLBACK, message: err instanceof Error ? err.message : FALLBACK.message };
  }
  const copy = ERROR_COPY[err.code];
  if (copy !== undefined) {
    return copy;
  }
  return { message: err.message, retryable: err.status >= 500 };
}

export function errorCopyFor(code: string): ErrorCopy | null {
  return ERROR_COPY[code] ?? null;
}

// job.error 是 ErrorResponse 载荷（非抛出的 ApiError），单独入口避免 instanceof 误用。
export function describeJobFailure(job: Job): string {
  if (job.error !== null) {
    const code = job.error.error.code;
    return errorCopyFor(code)?.message ?? `任务失败：${job.error.error.message}`;
  }
  if (job.status === "blocked") {
    return "任务被资料条件阻塞：资料不足或未通过核验，请查看提示后调整资料重试。";
  }
  return "任务未成功结束，请重试或检查资料。";
}
