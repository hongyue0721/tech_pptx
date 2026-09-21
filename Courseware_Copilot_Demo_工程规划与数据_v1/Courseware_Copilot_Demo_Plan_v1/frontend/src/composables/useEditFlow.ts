// T12 编辑/移动 job 的 URL 驱动流程（ReviewPage 编排抽取，页面守 500 行评审线）。
// 规则：202 即写 ?job=；终态即消耗意图（清 job，防刷新撞旧键空转）；
// 任何未显式列举的终态（含 interrupted）都必须走兜底分支消耗 URL（Review N1）。

import { computed, ref, type Ref } from "vue";

import { ApiError } from "../api/client";
import { describeError } from "../api/errorMessages";
import type { Job, Project } from "../types/models";
import { useJobPolling } from "./useJobPolling";

export interface EditFlowDeps {
  routeQueryJob: () => string | undefined;
  isCandidateView: () => boolean;
  project: Ref<Project | null>;
  versionView: () => number | null;
  gotoQuery: (patch: Record<string, string | number | null>) => Promise<unknown>;
}

export function useEditFlow(deps: EditFlowDeps) {
  const jobId = computed<string | null>(() => deps.routeQueryJob() ?? null);
  const editJob = ref<Job | null>(null);
  const editJobError = ref("");

  function onSettled(job: Job): void {
    editJob.value = job;
    if (job.status === "succeeded" && job.result_ref?.type === "change") {
      void deps.gotoQuery({ job: null, change: job.result_ref.id, version: null });
      return;
    }
    if (job.status === "blocked") {
      editJobError.value =
        job.error?.error.code === "INSUFFICIENT_EVIDENCE"
          ? "本次编辑因资料不足被服务器拦停：保留当前版本，请补充资料或收窄要求后重试。"
          : "编辑任务被服务器拦停，请查看任务错误说明。";
      void deps.gotoQuery({ job: null });
      return;
    }
    if (job.status === "failed") {
      editJobError.value = job.error
        ? `编辑未成功：${describeError(new ApiError(0, job.error)).message}`
        : "编辑任务失败，当前版本未受影响。";
      void deps.gotoQuery({ job: null });
      return;
    }
    if (job.status === "cancelled") {
      editJobError.value = "编辑任务已取消，当前版本未受影响。";
      void deps.gotoQuery({ job: null });
      return;
    }
    // 兜底（interrupted 等）：崩溃恢复置 interrupted 是真实可达终态，
    // 不清 URL 会让刷新反复轮询同一终态 job、教师对中断零感知。
    editJobError.value = "编辑任务已中断或结束，当前版本未受影响；请刷新后重试。";
    void deps.gotoQuery({ job: null });
  }

  const { isPolling, cancelling, requestCancel } = useJobPolling(jobId, {
    onSettled,
    onHalted: (message) => {
      editJobError.value = message;
      void deps.gotoQuery({ job: null });
    },
  });

  function onAccepted(newJobId: string): void {
    editJobError.value = "";
    editJob.value = null;
    void deps.gotoQuery({ job: newJobId, change: null, version: null });
  }

  function onRestored(newVersion: number): void {
    editJobError.value = "";
    void deps.gotoQuery({ version: newVersion, change: null, job: null });
  }

  // 受理门参数取项目真值（edit_service 按 current_version/corpus_revision
  // 校验）；展示 deck 的快照值在历史版本视图下可分叉，不得用作载荷。
  const baseVersion = computed(() => deps.project.value?.current_version ?? 0);
  const corpusRevision = computed(() => deps.project.value?.corpus_revision ?? 0);
  const disabledReason = computed(() => {
    const project = deps.project.value;
    if (!project) return "项目信息未就绪";
    if (project.current_version < 1) return "还没有正式版本，无法编辑";
    if (isPolling.value) return "编辑任务进行中，完成或取消后可再次编辑";
    if (project.active_job_id) return "该项目正在执行其他任务，完成或取消后才能编辑";
    if (deps.isCandidateView()) return "候选审阅期间不可叠加编辑，请先应用或放弃当前候选";
    const view = deps.versionView();
    if (view !== null && view !== project.current_version) {
      return "正在查看历史版本，回到当前版本后才能编辑";
    }
    return "";
  });
  const allowed = computed(() => disabledReason.value === "");

  return {
    editJob,
    editJobError,
    isPolling,
    cancelling,
    requestCancel,
    onAccepted,
    onRestored,
    baseVersion,
    corpusRevision,
    disabledReason,
    allowed,
  };
}
