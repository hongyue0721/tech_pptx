// 资料上传与作业编排：逐份上传（不用 Promise.all）、等 parse job 释放写锁再传下一份；
// 幂等键由文件指纹派生（结果未知重试不换键）；job 写入 URL，刷新可恢复；
// GET 失败绝不重新 POST；重复上传（duplicate）不产生新 job，如项目忙则等待现有 job。

import { computed, ref, watch, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "../api/client";
import { describeError, describeJobFailure } from "../api/errorMessages";
import { planCreateKey, uploadMaterialKey } from "../api/idempotency";
import { materialsApi, plansApi } from "../api/resources";
import type { Job, Material } from "../types/models";
import { useJobPolling } from "./useJobPolling";

export interface QueuedFile {
  name: string;
  size: number;
  file: File;
  state: "pending" | "uploading" | "parsing" | "done" | "failed";
  error: string;
}

export const MAX_MATERIALS = 5;

export function useMaterialIntake(projectId: Ref<string | null>) {
  const route = useRoute();
  const router = useRouter();

  const queue = ref<QueuedFile[]>([]);
  const materials = ref<Material[]>([]);
  const materialsError = ref("");
  const corpusRevision = ref(0);
  const uploading = ref(false);
  const generating = ref(false);
  const jobNotice = ref("");
  const activeJobId = ref<string | null>(null);

  let dataEpoch = 0;
  // attempt 由 URL query 承载（刷新/新标签页打开同一 URL 时意图计数不丢，
  // 避免重放旧 failed job）；非负整数校验防手改 URL 注入 NaN。
  const initialPa = Number(route.query.pa);
  let planAttempt = Number.isInteger(initialPa) && initialPa >= 0 ? initialPa : 0;

  const polling = useJobPolling(activeJobId, {
    onSettled: handleSettled,
    onHalted: (msg) => {
      generating.value = false;
      jobNotice.value = msg;
    },
  });

  const readyCount = computed(() => materials.value.filter((m) => m.status === "ready").length);
  const failedCount = computed(() => materials.value.filter((m) => m.status === "failed").length);
  const allReady = computed(
    () => materials.value.length > 0 && readyCount.value === materials.value.length,
  );
  const busy = computed(
    () => uploading.value || generating.value || polling.isPolling.value,
  );
  // failed 队列项不阻断生成（服务器语义：失败资料不阻碍 plan），只阻断在途工作。
  const hasInflightWork = computed(() =>
    queue.value.some((q) => q.state === "pending" || q.state === "uploading" || q.state === "parsing"),
  );
  const canGenerateOutline = computed(
    () => allReady.value && !busy.value && !hasInflightWork.value,
  );

  function syncJobToUrl(id: string | null): void {
    void router.replace({
      query: { ...route.query, job: id ?? undefined, pa: String(planAttempt) },
    });
  }

  function startJob(id: string): void {
    activeJobId.value = id;
    syncJobToUrl(id);
  }

  async function handleSettled(job: Job): Promise<void> {
    if (job.kind !== "plan") {
      syncJobToUrl(null);
      return;
    }
    generating.value = false;
    // 该键的意图已被消费（无论成败）：attempt 前进并落 URL——刷新后首击不会
    // 重放旧终态 job；受理前抛错（结果未知）不走此路径，同键恢复承诺保持。
    planAttempt += 1;
    syncJobToUrl(null);
    if (job.status === "succeeded" && job.result_ref?.type === "plan") {
      await router.push({
        name: "outline",
        params: { id: job.project_id },
        query: { plan: job.result_ref.id },
      });
      return;
    }
    jobNotice.value = describeJobFailure(job);
  }

  async function loadMaterials(): Promise<void> {
    const id = projectId.value;
    const epoch = dataEpoch;
    if (id === null) return;
    try {
      const list = await materialsApi.list(id);
      if (epoch !== dataEpoch) return;
      materials.value = list.materials;
      corpusRevision.value = list.corpus_revision;
      materialsError.value = "";
    } catch (err) {
      if (epoch !== dataEpoch) return;
      materialsError.value = describeError(err).message;
    }
  }

  // 等待轮询器把指定 job 带到终态；期间不重发任何 POST。
  function waitSettled(id: string): Promise<Job> {
    const settled = polling.settledJob.value;
    if (settled !== null && settled.id === id) return Promise.resolve(settled);
    return new Promise<Job>((resolve, reject) => {
      const stopSettled = watch(polling.settledJob, (job) => {
        if (job !== null && job.id === id) {
          cleanup();
          resolve(job);
        }
      });
      const stopError = watch(polling.pollError, (msg) => {
        if (msg !== null && !polling.isPolling.value) {
          cleanup();
          reject(new Error(msg));
        }
      });
      const stopProject = watch(projectId, () => {
        cleanup();
        reject(new DOMException("project switched", "AbortError"));
      });
      function cleanup(): void {
        stopSettled();
        stopError();
        stopProject();
      }
    });
  }

  async function runUploadLoop(): Promise<void> {
    const id = projectId.value;
    if (id === null || uploading.value) return;
    const epoch = dataEpoch;
    uploading.value = true;
    jobNotice.value = "";
    try {
      while (true) {
        const item = queue.value.find((q) => q.state === "pending");
        if (item === undefined) break;
        item.state = "uploading";
        const accepted = await materialsApi.upload(
          id,
          item.file,
          uploadMaterialKey(id, item.file.name, item.file.size, item.file.lastModified),
        );
        if (epoch !== dataEpoch) return;
        if (accepted.job_id !== null) {
          item.state = "parsing";
          startJob(accepted.job_id);
          const settled = await waitSettled(accepted.job_id);
          if (epoch !== dataEpoch) return;
          if (settled.status === "succeeded") {
            // 入库成功后本地队列项移除，服务器资料列表为唯一事实源。
            queue.value.splice(queue.value.indexOf(item), 1);
          } else {
            item.state = "failed";
            item.error = describeJobFailure(settled);
          }
        } else {
          // duplicate：无新 job；若项目仍有活动任务，等它释放写锁再继续。
          queue.value.splice(queue.value.indexOf(item), 1);
          const project = await api.getProject(id);
          if (epoch !== dataEpoch) return;
          if (project.active_job_id !== null) {
            startJob(project.active_job_id);
            await waitSettled(project.active_job_id);
            if (epoch !== dataEpoch) return;
          }
        }
        await loadMaterials();
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      const inflight = queue.value.find((q) => q.state === "uploading" || q.state === "parsing");
      if (inflight !== undefined) {
        inflight.state = "failed";
        inflight.error = describeError(err).message;
      }
      jobNotice.value = describeError(err).message;
    } finally {
      if (epoch === dataEpoch) uploading.value = false;
    }
  }

  function enqueueFiles(files: File[]): void {
    for (const file of files) {
      if (!file.name.toLowerCase().endsWith(".pdf")) continue;
      if (queue.value.some((q) => q.name === file.name && q.size === file.size)) continue;
      // 入队即按剩余额度截断（服务器已入库 + 本地在队），不靠服务器拒绝兜底。
      if (materials.value.length + queue.value.length >= MAX_MATERIALS) {
        materialsError.value = `最多 ${MAX_MATERIALS} 份资料，超出的文件未加入队列。`;
        return;
      }
      queue.value.push({
        name: file.name,
        size: file.size,
        file,
        state: "pending",
        error: "",
      });
    }
  }

  function removeQueued(index: number): void {
    queue.value.splice(index, 1);
  }

  async function generateOutline(): Promise<void> {
    const id = projectId.value;
    if (id === null || generating.value || busy.value) return;
    generating.value = true;
    jobNotice.value = "";
    try {
      // attempt 在 job 终态时前进（handleSettled）：结果未知（受理前抛错）不换键=同键恢复。
      const accepted = await plansApi.create(
        id,
        corpusRevision.value,
        planCreateKey(id, corpusRevision.value, planAttempt),
      );
      startJob(accepted.job_id);
    } catch (err) {
      generating.value = false;
      jobNotice.value = describeError(err).message;
    }
  }

  // 页面加载/项目切换后的恢复：URL 精确 job 优先，其次服务器活动任务。
  async function restoreJob(activeJobIdFromServer: string | null): Promise<void> {
    dataEpoch += 1;
    // 旧循环因 epoch 失配自行退出，这里复位其占用的状态，防止 uploading 死锁；
    // 在途项降级回 pending（File 仍在本地，可对新项目重新提交，键含 projectId 不互撞）。
    uploading.value = false;
    for (const q of queue.value) {
      if (q.state === "uploading" || q.state === "parsing") {
        q.state = "pending";
        q.error = "";
      }
    }
    materials.value = [];
    materialsError.value = "";
    jobNotice.value = "";
    generating.value = false;
    activeJobId.value = null;
    const id = projectId.value;
    if (id === null) return;
    await loadMaterials();
    if (queue.value.some((q) => q.state === "pending")) {
      void runUploadLoop();
      return;
    }
    const fromUrl = route.query.job;
    if (typeof fromUrl === "string" && fromUrl.length > 0) {
      activeJobId.value = fromUrl;
      return;
    }
    if (activeJobIdFromServer !== null) {
      activeJobId.value = activeJobIdFromServer;
    }
  }

  return {
    queue,
    materials,
    materialsError,
    corpusRevision,
    uploading,
    generating,
    jobNotice,
    activeJobId,
    job: polling.job,
    pollError: polling.pollError,
    isPolling: polling.isPolling,
    readyCount,
    failedCount,
    allReady,
    busy,
    canGenerateOutline,
    enqueueFiles,
    removeQueued,
    runUploadLoop,
    loadMaterials,
    generateOutline,
    restoreJob,
  };
}
