// Job 轮询：jobId 由 URL 驱动（ref），受理 202 即写 URL，本 composable 只 GET 不 POST。
// 规则：前台 2s / 后台 5s；终态停止；卸载 abort；epoch 防旧回包覆盖新任务；
// GET 失败不重新发起 POST——保留错误并继续按节奏轮询（404 视为异常终态停止）。

import { onScopeDispose, ref, watch, type Ref } from "vue";

import { ApiError } from "../api/client";
import { jobsApi } from "../api/resources";
import type { Job, JobStatus } from "../types/models";

export const JOB_TERMINAL_STATUSES: ReadonlySet<JobStatus> = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "blocked",
  "interrupted",
]);

export function isTerminalJob(job: Job | null): boolean {
  return job !== null && JOB_TERMINAL_STATUSES.has(job.status);
}

const DEFAULT_FOREGROUND_MS = 2000;
const DEFAULT_BACKGROUND_MS = 5000;

export interface JobPollingOptions {
  onSettled?: (job: Job) => void;
  // 异常停止（404/401）通知消费者复位自身状态，防止 generating/uploading 卡死。
  onHalted?: (message: string) => void;
  foregroundMs?: number;
  backgroundMs?: number;
}

export function useJobPolling(jobId: Ref<string | null>, options: JobPollingOptions = {}) {
  const foregroundMs = options.foregroundMs ?? DEFAULT_FOREGROUND_MS;
  const backgroundMs = options.backgroundMs ?? DEFAULT_BACKGROUND_MS;

  const job = ref<Job | null>(null);
  const settledJob = ref<Job | null>(null);
  const pollError = ref<string | null>(null);
  const isPolling = ref(false);

  let epoch = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let controller: AbortController | null = null;

  function clearTimer(): void {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  }

  function delayMs(): number {
    return typeof document !== "undefined" && document.hidden ? backgroundMs : foregroundMs;
  }

  function schedule(myEpoch: number, id: string): void {
    clearTimer();
    timer = setTimeout(() => void tick(myEpoch, id), delayMs());
  }

  async function tick(myEpoch: number, id: string): Promise<void> {
    if (myEpoch !== epoch) return;
    controller?.abort();
    controller = new AbortController();
    try {
      const latest = await jobsApi.get(id, controller.signal);
      if (myEpoch !== epoch) return;
      job.value = latest;
      pollError.value = null;
      if (isTerminalJob(latest)) {
        isPolling.value = false;
        clearTimer();
        settledJob.value = latest;
        options.onSettled?.(latest);
        return;
      }
      schedule(myEpoch, id);
    } catch (err) {
      if (myEpoch !== epoch) return;
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (err instanceof ApiError && err.status === 404) {
        isPolling.value = false;
        clearTimer();
        pollError.value = "任务记录不存在，可能已被清理，请重新发起操作。";
        options.onHalted?.(pollError.value);
        return;
      }
      if (err instanceof ApiError && err.status === 401) {
        isPolling.value = false;
        clearTimer();
        pollError.value = "登录状态失效，请重新验证。";
        options.onHalted?.(pollError.value);
        return;
      }
      // 网络/5xx/409 等：如实暴露，继续轮询，绝不因 GET 失败重发 POST。
      pollError.value = err instanceof Error ? err.message : String(err);
      schedule(myEpoch, id);
    }
  }

  function stop(): void {
    epoch += 1;
    clearTimer();
    controller?.abort();
    controller = null;
    isPolling.value = false;
  }

  watch(
    jobId,
    (id) => {
      stop();
      job.value = null;
      settledJob.value = null;
      pollError.value = null;
      if (id === null || id === "") return;
      const myEpoch = epoch;
      isPolling.value = true;
      void tick(myEpoch, id);
    },
    { immediate: true },
  );

  function onVisibility(): void {
    const id = jobId.value;
    if (id === null || id === "" || !isPolling.value) return;
    // 回到前台立即补一次，避免后台节流造成的状态滞后。
    clearTimer();
    void tick(epoch, id);
  }

  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onVisibility);
  }

  onScopeDispose(() => {
    if (typeof document !== "undefined") {
      document.removeEventListener("visibilitychange", onVisibility);
    }
    stop();
  });

  return { job, settledJob, pollError, isPolling, stop };
}
