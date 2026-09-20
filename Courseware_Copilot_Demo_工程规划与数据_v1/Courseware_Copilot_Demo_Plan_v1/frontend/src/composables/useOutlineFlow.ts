// 大纲确认流：教师编辑（标题/重点/顺序/接受范围）→ POST confirm 成功 → POST generations。
// 严格串行不绕过确认；已确认后失败重试只重发 generate（同幂等键），不新建计划。
// 缺口目标（unsupported/conflict）不可勾选接受；取消勾选前须先解除内容页引用（与后端同规则）。
// generate job 写入 URL，刷新恢复轮询；job 终态后按 result_ref 精确跳转 review。

import { computed, ref, type Ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { canonicalize, generateKey, planConfirmKey } from "../api/idempotency";
import { describeError, describeJobFailure } from "../api/errorMessages";
import { changesApi, plansApi } from "../api/resources";
import type {
  ConfirmPlanRequest,
  GenerateRequest,
  Job,
  LessonPlan,
  PlanSlide,
  Project,
} from "../types/models";
import { useJobPolling } from "./useJobPolling";

export function useOutlineFlow(
  projectId: Ref<string>,
  plan: Ref<LessonPlan | null>,
  project: Ref<Project | null>,
) {
  const route = useRoute();
  const router = useRouter();

  const editedSlides = ref<PlanSlide[]>([]);
  const acceptedGoals = ref<number[]>([]);
  const reviewed = ref(false);
  const confirming = ref(false);
  const generating = ref(false);
  const flowError = ref("");
  const activeJobId = ref<string | null>(null);

  const polling = useJobPolling(activeJobId, {
    onSettled: handleSettled,
    onHalted: (msg) => {
      generating.value = false;
      flowError.value = msg;
    },
  });

  // attempt 由 URL query 承载：刷新/重开同 URL 不丢"上一意图已终结"事实，
  // 避免首击重放旧 failed job（与 useMaterialIntake 同规则）。
  const initialPa = Number(route.query.pa);
  let genAttempt = Number.isInteger(initialPa) && initialPa >= 0 ? initialPa : 0;

  const isConfirmed = computed(() => plan.value?.status === "confirmed");
  const isStale = computed(() => plan.value?.status === "stale");
  const readOnly = computed(() => isConfirmed.value || isStale.value);
  const busy = computed(
    () => confirming.value || generating.value || polling.isPolling.value,
  );
  const canConfirmAndGenerate = computed(
    () =>
      plan.value !== null &&
      !isConfirmed.value &&
      !isStale.value &&
      reviewed.value &&
      acceptedGoals.value.length > 0 &&
      !busy.value,
  );
  const canGenerateOnly = computed(() => isConfirmed.value && !isStale.value && !busy.value);

  function resetFromPlan(p: LessonPlan): void {
    editedSlides.value = JSON.parse(JSON.stringify(p.slides)) as PlanSlide[];
    acceptedGoals.value = [...p.accepted_goal_indices];
    reviewed.value = false;
    flowError.value = "";
    confirming.value = false;
    generating.value = false;
  }

  function coverageStatus(goalIndex: number): string | null {
    const hit = plan.value?.coverage.find((c) => c.goal_index === goalIndex);
    return hit ? hit.status : null;
  }

  function goalAcceptable(goalIndex: number): boolean {
    const status = coverageStatus(goalIndex);
    return status === "supported" || status === "partial";
  }

  function isGoalAccepted(goalIndex: number): boolean {
    return acceptedGoals.value.includes(goalIndex);
  }

  function toggleGoal(goalIndex: number, checked: boolean): void {
    flowError.value = "";
    if (checked) {
      if (!goalAcceptable(goalIndex)) return;
      acceptedGoals.value = [...acceptedGoals.value, goalIndex].sort((a, b) => a - b);
      return;
    }
    // 取消接受前，任何页面（含封面）仍引用该目标则拒绝——后端对全部 slides 做
    // "不得触碰接受范围外目标"检查，豁免 title 会换来 422，预检必须同口径。
    const blockers = editedSlides.value.filter((s) => s.goal_indices.includes(goalIndex));
    if (blockers.length > 0) {
      flowError.value = `目标${goalIndex + 1}仍被 ${blockers.length} 个页面引用，请先调整这些页面再取消接受。`;
      return;
    }
    acceptedGoals.value = acceptedGoals.value.filter((g) => g !== goalIndex);
  }

  function moveSlide(index: number, delta: number): void {
    const target = index + delta;
    if (target < 0 || target >= editedSlides.value.length) return;
    const slides = [...editedSlides.value];
    [slides[index], slides[target]] = [slides[target], slides[index]];
    editedSlides.value = slides;
  }

  function syncJobToUrl(id: string | null): void {
    void router.replace({
      query: { ...route.query, job: id ?? undefined, pa: String(genAttempt) },
    });
  }

  async function handleSettled(job: Job): Promise<void> {
    if (job.kind !== "generate") {
      syncJobToUrl(null);
      return;
    }
    generating.value = false;
    // 该键的意图已被消费：attempt 前进并落 URL，刷新后首击不重放旧终态 job；
    // 受理前抛错（结果未知）不走此路径，同键恢复承诺保持。
    genAttempt += 1;
    syncJobToUrl(null);
    // blocked 候选同样以 succeeded job + change 呈现（教师去审阅页看报告），不伪装失败。
    if (job.status === "succeeded" && job.result_ref?.type === "change") {
      await router.push({
        name: "review",
        params: { id: job.project_id },
        query: { change: job.result_ref.id },
      });
      return;
    }
    flowError.value = describeJobFailure(job);
  }

  async function startGeneration(): Promise<void> {
    const p = plan.value;
    const prj = project.value;
    if (p === null || prj === null || generating.value) return;
    generating.value = true;
    flowError.value = "";
    const body: GenerateRequest = {
      plan_id: p.id,
      base_version: prj.current_version,
      corpus_revision: p.corpus_revision,
    };
    try {
      // attempt 在 job 终态时前进（handleSettled）：结果未知（受理前抛错）不换键=同键恢复。
      const accepted = await changesApi.generate(
        projectId.value,
        body,
        generateKey(projectId.value, p.id, prj.current_version, p.corpus_revision, genAttempt),
      );
      activeJobId.value = accepted.job_id;
      syncJobToUrl(accepted.job_id);
    } catch (err) {
      generating.value = false;
      flowError.value = describeError(err).message;
    }
  }

  async function confirmAndGenerate(): Promise<void> {
    const p = plan.value;
    if (p === null || busy.value) return;
    if (!isConfirmed.value) {
      confirming.value = true;
      flowError.value = "";
      const body: ConfirmPlanRequest = {
        corpus_revision: p.corpus_revision,
        slides: editedSlides.value,
        accepted_goal_indices: acceptedGoals.value,
        acknowledged: true,
      };
      try {
        const confirmed = await plansApi.confirm(
          projectId.value,
          p.id,
          body,
          planConfirmKey(projectId.value, p.id, canonicalize(body)),
        );
        plan.value = confirmed;
      } catch (err) {
        confirming.value = false;
        flowError.value = describeError(err).message;
        return; // confirm 失败绝不进入 generations
      }
      confirming.value = false;
    }
    await startGeneration();
  }

  function restoreJob(): void {
    const fromUrl = route.query.job;
    if (typeof fromUrl === "string" && fromUrl.length > 0) {
      activeJobId.value = fromUrl;
    }
  }

  return {
    editedSlides,
    acceptedGoals,
    reviewed,
    confirming,
    generating,
    flowError,
    job: polling.job,
    pollError: polling.pollError,
    isPolling: polling.isPolling,
    isConfirmed,
    isStale,
    readOnly,
    busy,
    canConfirmAndGenerate,
    canGenerateOnly,
    resetFromPlan,
    goalAcceptable,
    isGoalAccepted,
    toggleGoal,
    moveSlide,
    confirmAndGenerate,
    startGeneration,
    restoreJob,
  };
}
