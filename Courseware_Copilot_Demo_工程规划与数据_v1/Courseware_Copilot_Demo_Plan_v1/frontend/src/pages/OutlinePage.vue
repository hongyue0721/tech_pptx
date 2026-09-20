<script setup lang="ts">
import { AButton } from "@any-design/anyui/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "../api/client";
import { plansApi } from "../api/resources";
import StatusTag from "../components/common/StatusTag.vue";
import CourseShell from "../layouts/CourseShell.vue";
import { api } from "../api/client";
import type { LessonPlan, PlanSlide, Project } from "../types/models";

const props = defineProps<{ id: string }>();
const route = useRoute();
const router = useRouter();

const project = ref<Project | null>(null);
const plan = ref<LessonPlan | null>(null);
const loadError = ref("");
const selectedIndex = ref(0);
let controller: AbortController | null = null;
let epoch = 0;

const planId = computed(() => (route.query.plan as string | undefined) ?? "");
const goalsOpen = ref(false);
const selectedSlide = computed<PlanSlide | null>(
  () => plan.value?.slides[selectedIndex.value] ?? null,
);
const isConfirmed = computed(() => plan.value?.status === "confirmed");

const COVERAGE_LABEL: Record<string, string> = {
  supported: "相关资料较充分（检索）",
  partial: "相关资料不足",
  unsupported: "资料缺口",
  conflict: "资料冲突",
};

async function load(): Promise<void> {
  epoch += 1;
  const myEpoch = epoch;
  controller?.abort();
  controller = new AbortController();
  loadError.value = "";
  if (!planId.value) {
    plan.value = null;
    return;
  }
  try {
    const [p, pl] = await Promise.all([
      api.getProject(props.id, controller.signal),
      plansApi.get(props.id, planId.value, controller.signal),
    ]);
    if (myEpoch !== epoch) return;
    project.value = p;
    plan.value = pl;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    if (myEpoch !== epoch) return;
    loadError.value = err instanceof ApiError ? err.message : String(err);
    plan.value = null;
  }
}

watch([() => props.id, planId], () => void load(), { immediate: true });
onBeforeUnmount(() => controller?.abort());

function move(index: number, delta: number): void {
  if (!plan.value) return;
  const target = index + delta;
  if (target < 0 || target >= plan.value.slides.length) return;
  const slides = [...plan.value.slides];
  [slides[index], slides[target]] = [slides[target], slides[index]];
  plan.value = { ...plan.value, slides };
  selectedIndex.value = target;
}

function goMaterials(): void {
  void router.push({ name: "materials", params: { id: props.id } });
}
</script>

<template>
  <CourseShell :project-id="props.id" :project="project">
    <div v-if="!planId" class="empty-state">
      <h2>尚无教学大纲</h2>
      <p>请先在「资料设置」上传并解析教学资料后生成大纲。页面只按精确大纲 ID 恢复，不猜测"最新"。</p>
      <AButton type="primary" @click="goMaterials">返回资料设置</AButton>
    </div>
    <div v-else-if="loadError" class="empty-state" role="alert">
      <h2>大纲读取失败</h2>
      <p class="error-text">{{ loadError }}</p>
      <AButton @click="load">重试</AButton>
    </div>
    <div v-else-if="plan" class="outline-grid">
      <section
        class="panel goals-panel"
        :class="{ open: goalsOpen }"
        aria-label="教学目标与覆盖"
      >
        <div class="goals-head">
          <h2 class="panel-title">教学目标</h2>
          <button type="button" class="drawer-close" aria-label="关闭" @click="goalsOpen = false">×</button>
        </div>
        <ul class="goal-list">
          <li v-for="c in plan.coverage" :key="c.goal_index">
            <span class="goal-mark" :class="`m-${c.status}`" aria-hidden="true">
              {{ c.status === "supported" ? "☑" : c.status === "partial" ? "△" : "□" }}
            </span>
            <div>
              <p class="goal-text">目标{{ c.goal_index + 1 }}：{{ project?.course.goals[c.goal_index] }}</p>
              <p class="goal-cov">{{ COVERAGE_LABEL[c.status] }}<template v-if="c.note"> · {{ c.note }}</template></p>
            </div>
          </li>
        </ul>
        <p class="coverage-note">覆盖状态是资料检索覆盖，不等于事实已验证。</p>
      </section>

      <section class="panel list-panel" aria-label="大纲页面列表">
        <h2 class="panel-title">本次教学大纲 · {{ plan.slides.length }} 页</h2>
        <ol class="slide-list">
          <li
            v-for="(s, i) in plan.slides"
            :key="s.id"
            :class="{ selected: i === selectedIndex }"
          >
            <button class="slide-row" type="button" @click="selectedIndex = i">
              <span class="slide-no">{{ String(i + 1).padStart(2, "0") }}</span>
              <span class="slide-title">{{ s.title }}</span>
              <span v-if="i === selectedIndex" class="cursor-mark">←</span>
            </button>
          </li>
        </ol>
      </section>

      <section class="panel detail-panel" aria-label="当前页面详情">
        <h2 class="panel-title">当前页面</h2>
        <template v-if="selectedSlide">
          <label class="field">
            <span>标题</span>
            <input
              v-model="selectedSlide.title"
              class="text-input"
              maxlength="40"
              :disabled="isConfirmed"
            />
          </label>
          <label class="field">
            <span>讲授重点（purpose）</span>
            <textarea
              v-model="selectedSlide.purpose"
              class="text-input"
              rows="3"
              maxlength="240"
              :disabled="isConfirmed"
            ></textarea>
          </label>
          <p class="meta-line">
            布局 <code>{{ selectedSlide.layout }}</code> ·
            来源 {{ selectedSlide.evidence_chunk_ids.length }} 段 ·
            关联目标 {{ selectedSlide.goal_indices.map((g) => g + 1).join("、") || "无" }}
          </p>
          <div class="move-row">
            <AButton size="small" :disabled="isConfirmed || selectedIndex === 0" @click="move(selectedIndex, -1)">上移</AButton>
            <AButton
              size="small"
              :disabled="isConfirmed || selectedIndex >= (plan?.slides.length ?? 0) - 1"
              @click="move(selectedIndex, 1)"
            >下移</AButton>
          </div>
        </template>
      </section>
    </div>
    <div v-else class="empty-state"><p>加载中…</p></div>

    <template #footer-status>
      <span v-if="plan">
        <StatusTag v-if="isConfirmed" tone="ready">大纲已确认</StatusTag>
        <StatusTag v-else-if="plan.status === 'needs_material'" tone="pending">存在资料缺口</StatusTag>
        <StatusTag v-else tone="info">草稿 · 待教师确认</StatusTag>
        · 已选范围 {{ plan.accepted_goal_indices.length }} 个目标
      </span>
      <span v-else>等待大纲</span>
    </template>
    <template #footer-actions>
      <AButton class="narrow-only" @click="goalsOpen = !goalsOpen">目标</AButton>
      <AButton :disabled="!plan" @click="goMaterials">返回资料</AButton>
      <AButton
        type="primary"
        :disabled="!plan || isConfirmed"
        :title="plan && !isConfirmed ? '确认后进入课件生成（F2 接通执行）' : ''"
        @click="() => {}"
      >
        确认大纲并生成 →
      </AButton>
    </template>
  </CourseShell>
</template>

<style scoped>
.outline-grid {
  height: 100%;
  display: grid;
  grid-template-columns: 230px minmax(0, 1fr) 280px;
  gap: var(--cc-gap-panel);
  min-height: 0;
}
.panel {
  background: var(--cc-panel);
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-panel);
  padding: 16px 18px;
  min-height: 0;
  overflow: auto;
}
.panel-title {
  font-size: var(--cc-font-section);
  margin-bottom: 12px;
}
.goal-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.goal-list li {
  display: flex;
  gap: 8px;
}
.goal-mark {
  color: var(--cc-ink-weak);
  font-size: 15px;
  line-height: 1.4;
}
.m-supported {
  color: var(--cc-success);
}
.m-partial {
  color: var(--cc-blocked);
}
.goal-text {
  margin: 0;
  font-weight: 500;
}
.goal-cov {
  margin: 2px 0 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.coverage-note {
  margin: 14px 0 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  border-top: 1px solid var(--cc-border);
  padding-top: 10px;
}
.slide-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.slide-list li.selected {
  background: var(--cc-selected);
  border-radius: var(--cc-radius-control);
}
.slide-row {
  width: 100%;
  display: flex;
  gap: 10px;
  align-items: baseline;
  background: none;
  border: none;
  padding: 9px 10px;
  font: inherit;
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.slide-no {
  color: var(--cc-accent);
  font-variant-numeric: tabular-nums;
  font-size: var(--cc-font-aux);
}
.slide-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cursor-mark {
  color: var(--cc-primary);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--cc-font-ui);
  margin-bottom: 12px;
}
.field > span {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
}
.text-input {
  font: inherit;
  padding: 7px 9px;
  border: 1px solid var(--cc-border-strong);
  border-radius: var(--cc-radius-control);
  background: var(--cc-panel);
  color: var(--cc-ink);
}
.text-input:disabled {
  background: var(--cc-selected);
  color: var(--cc-ink-weak);
}
.meta-line {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  margin: 0 0 12px;
}
.move-row {
  display: flex;
  gap: 10px;
}
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--cc-ink-weak);
}
.empty-state h2 {
  color: var(--cc-ink);
  font-size: var(--cc-font-section);
}
.error-text {
  color: var(--cc-blocked);
}
.narrow-only {
  display: none;
}
.goals-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.drawer-close {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--cc-ink-weak);
}
@media (max-width: 1080px) {
  .outline-grid {
    grid-template-columns: minmax(0, 1fr) 260px;
  }
  .narrow-only {
    display: inline-flex;
  }
  .goals-panel {
    position: fixed;
    left: 0;
    top: 0;
    bottom: 0;
    width: 300px;
    z-index: 30;
    border-radius: 0;
    transform: translateX(-105%);
    transition: transform 0.18s ease;
    box-shadow: 6px 0 24px rgba(37, 49, 68, 0.18);
  }
  .goals-panel.open {
    transform: translateX(0);
  }
}
</style>
