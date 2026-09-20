<script setup lang="ts">
import { AButton, AInput, ATextarea } from "@any-design/anyui/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import { materialsApi } from "../api/resources";
import StatusTag from "../components/common/StatusTag.vue";
import type { CreateProjectRequest, Material, Project } from "../types/models";
import CourseShell from "../layouts/CourseShell.vue";

const props = defineProps<{ id?: string }>();
const router = useRouter();
const route = useRoute();

const project = ref<Project | null>(null);
const loadError = ref("");
let controller: AbortController | null = null;

// 创建前表单（真实提交，校验与后端一致：topic/audience 必填、goals≤8、页数4-12）
const topic = ref("");
const audience = ref("");
const durationMinutes = ref(45);
const targetSlides = ref(8);
const goalsText = ref("");
const consent = ref(false);
const submitting = ref(false);
const formError = ref("");

// 本地待提交队列：创建项目前可增删；创建后逐份上传（F2 接通）。
interface QueuedFile {
  name: string;
  size: number;
  file: File;
}
const queue = ref<QueuedFile[]>([]);
const materials = ref<Material[]>([]);
const materialsError = ref("");

const isCreateMode = computed(() => !props.id);
const goals = computed(() =>
  goalsText.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0),
);
const readyCount = computed(() => materials.value.filter((m) => m.status === "ready").length);
const allReady = computed(
  () => materials.value.length > 0 && readyCount.value === materials.value.length,
);
const canGenerateOutline = computed(() => allReady.value && !project.value?.active_job_id);

function onPickFiles(event: Event): void {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  for (const file of files) {
    if (!file.name.toLowerCase().endsWith(".pdf")) continue;
    if (queue.value.some((q) => q.name === file.name && q.size === file.size)) continue;
    queue.value.push({ name: file.name, size: file.size, file });
  }
  input.value = "";
}

function removeQueued(index: number): void {
  queue.value.splice(index, 1);
}

async function createAndUpload(): Promise<void> {
  submitting.value = true;
  formError.value = "";
  const body: CreateProjectRequest = {
    course: {
      topic: topic.value,
      audience: audience.value,
      duration_minutes: durationMinutes.value,
      goals: goals.value,
      target_slides: targetSlides.value,
    },
    consent_to_cloud_processing: consent.value,
  };
  try {
    const created = await api.createProject(body, crypto.randomUUID());
    await router.push({ name: "materials", params: { id: created.id } });
  } catch (err) {
    formError.value =
      err instanceof ApiError ? `${err.message}（${err.code}）` : String(err);
  } finally {
    submitting.value = false;
  }
}

async function loadProject(projectId: string, epoch: number): Promise<void> {
  controller?.abort();
  controller = new AbortController();
  loadError.value = "";
  try {
    const loaded = await api.getProject(projectId, controller.signal);
    if (route.name !== "materials" && route.name !== "intake") return;
    if (epoch !== loadEpoch) return;
    project.value = loaded;
    await loadMaterials(projectId, epoch);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    if (epoch !== loadEpoch) return;
    loadError.value = err instanceof ApiError ? err.message : String(err);
  }
}

let loadEpoch = 0;

async function loadMaterials(projectId: string, epoch: number): Promise<void> {
  try {
    const list = await materialsApi.list(projectId);
    if (epoch !== loadEpoch) return;
    materials.value = list.materials;
    materialsError.value = "";
  } catch (err) {
    if (epoch !== loadEpoch) return;
    materialsError.value = err instanceof ApiError ? err.message : String(err);
  }
}

watch(
  () => props.id,
  (id) => {
    loadEpoch += 1;
    if (!id) {
      project.value = null;
      materials.value = [];
      return;
    }
    void loadProject(id, loadEpoch);
  },
  { immediate: true },
);

onBeforeUnmount(() => controller?.abort());

const statusText = computed(() => {
  if (isCreateMode.value) {
    return queue.value.length > 0
      ? `待提交资料 ${queue.value.length} 份，创建后自动解析`
      : "创建课题后可上传教学资料";
  }
  if (loadError.value) return "项目读取失败，请刷新重试";
  if (materials.value.length === 0) return "尚未上传教学资料";
  const failed = materials.value.filter((m) => m.status === "failed").length;
  if (failed > 0) return `${readyCount.value} 份就绪，${failed} 份解析失败`;
  return `${readyCount.value} 份资料文本就绪`;
});
</script>

<template>
  <CourseShell :project-id="props.id" :project="project">
    <div class="intake-grid">
      <section class="panel brief-panel" aria-labelledby="brief-title">
        <h2 id="brief-title" class="panel-title">这节课，想讲什么？</h2>
        <form v-if="isCreateMode" class="brief-form" @submit.prevent="createAndUpload">
          <label class="field">
            <span>课题</span>
            <AInput v-model="topic" placeholder="如：STM32 中断系统" :maxlength="120" />
          </label>
          <label class="field">
            <span>授课对象</span>
            <AInput v-model="audience" placeholder="如：大二电子信息专业" :maxlength="120" />
          </label>
          <div class="field-row">
            <label class="field">
              <span>课时（分钟）</span>
              <input v-model.number="durationMinutes" class="num-input" type="number" min="10" max="120" />
            </label>
            <label class="field">
              <span>目标页数</span>
              <input v-model.number="targetSlides" class="num-input" type="number" min="4" max="12" />
            </label>
          </div>
          <label class="field">
            <span>教学目标（每行一条，最多 8 条）</span>
            <ATextarea v-model="goalsText" :rows="3" placeholder="理解 NVIC 优先级分组…" />
          </label>
          <label class="consent">
            <input id="consent" v-model="consent" type="checkbox" />
            <span>我同意必要课程内容交由云模型处理（仅课程文本，不含附件原文外发）</span>
          </label>
          <p v-if="formError" class="error" role="alert">{{ formError }}</p>
        </form>
        <dl v-else class="brief-readonly">
          <div><dt>课题</dt><dd>{{ project?.course.topic ?? "…" }}</dd></div>
          <div><dt>授课对象</dt><dd>{{ project?.course.audience ?? "…" }}</dd></div>
          <div><dt>课时 / 页数</dt><dd>{{ project?.course.duration_minutes ?? "…" }} 分钟 · {{ project?.course.target_slides ?? "…" }} 页</dd></div>
          <div class="span-2">
            <dt>教学目标</dt>
            <dd><ul><li v-for="g in project?.course.goals ?? []" :key="g">{{ g }}</li></ul></dd>
          </div>
          <p class="readonly-note">课程要求在创建后只读；如需调整请新建课题。</p>
        </dl>
      </section>

      <section class="panel materials-panel" aria-labelledby="mat-title">
        <div class="materials-head">
          <h2 id="mat-title" class="panel-title">教学资料</h2>
          <span class="count">{{ isCreateMode ? queue.length : materials.length }} / 5</span>
        </div>
        <label class="drop-zone" :class="{ disabled: !isCreateMode }">
          <input type="file" accept="application/pdf" multiple hidden @change="onPickFiles" />
          <strong>{{ isCreateMode ? "拖入 PDF 或点击选择（先入队列）" : "上传入口将在资料链路接通后启用" }}</strong>
          <span class="drop-hint">PDF · 单份 ≤20MiB · 最多 5 份 · 逐份解析</span>
        </label>
        <ul v-if="isCreateMode" class="file-list">
          <li v-for="(q, i) in queue" :key="`${q.name}-${i}`">
            <span class="file-name">{{ q.name }}</span>
            <StatusTag tone="info">待提交</StatusTag>
            <button class="link-btn" type="button" @click="removeQueued(i)">移除</button>
          </li>
        </ul>
        <ul v-else class="file-list" aria-live="polite">
          <li v-if="materialsError" class="error">{{ materialsError }}</li>
          <li v-for="m in materials" :key="m.id">
            <span class="file-name">{{ m.original_name }}</span>
            <StatusTag v-if="m.status === 'ready'" tone="ready">文本就绪</StatusTag>
            <StatusTag v-else-if="m.status === 'failed'" tone="failed">解析失败</StatusTag>
            <StatusTag v-else tone="pending">解析中</StatusTag>
            <details v-if="m.warnings.length" class="warnings">
              <summary>{{ m.warnings.length }} 条解析警告</summary>
              <ul><li v-for="w in m.warnings" :key="w.pdf_page">第 {{ w.pdf_page }} 页：{{ w.message }}</li></ul>
            </details>
          </li>
          <li v-if="materials.length === 0 && !materialsError" class="empty-hint">
            尚未上传资料。可先创建课题，再逐份上传解析。
          </li>
        </ul>
        <p class="privacy-note">资料仅用于本项目大纲与课件生成；来源与页码以服务器解析结果为准。</p>
      </section>
    </div>

    <template #footer-status>
      <span :class="{ 'error-text': Boolean(loadError) }">{{ statusText }}</span>
    </template>
    <template #footer-actions>
      <template v-if="isCreateMode">
        <AButton
          type="primary"
          :disabled="submitting || !topic || !audience || goals.length === 0 || !consent"
          @click="createAndUpload"
        >
          {{ submitting ? "创建中…" : "保存设置并解析资料 →" }}
        </AButton>
      </template>
      <template v-else>
        <AButton
          type="primary"
          :disabled="!canGenerateOutline"
          :title="canGenerateOutline ? '' : '资料尚未全部就绪'"
          @click="() => {}"
        >
          生成教学大纲 →
        </AButton>
      </template>
    </template>
  </CourseShell>
</template>

<style scoped>
.intake-grid {
  height: 100%;
  display: grid;
  grid-template-columns: minmax(320px, 5fr) minmax(320px, 4fr);
  gap: var(--cc-gap-panel);
  min-height: 0;
}
.panel {
  background: var(--cc-panel);
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-panel);
  padding: 18px 20px;
  min-height: 0;
  overflow: auto;
}
.panel-title {
  font-size: var(--cc-font-section);
  margin-bottom: 14px;
}
.brief-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--cc-font-ui);
}
.field > span {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
}
.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.num-input {
  font: inherit;
  font-size: var(--cc-font-ui);
  padding: 7px 9px;
  border: 1px solid var(--cc-border-strong);
  border-radius: var(--cc-radius-control);
  background: var(--cc-panel);
  color: var(--cc-ink);
}
.consent {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.brief-readonly {
  margin: 0;
  display: grid;
  gap: 10px;
}
.brief-readonly > div {
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.brief-readonly dt {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
  min-width: 72px;
}
.brief-readonly dd {
  margin: 0;
  font-weight: 500;
}
.brief-readonly ul {
  margin: 0;
  padding-left: 18px;
}
.readonly-note {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  margin: 4px 0 0;
}
.materials-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.count {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.drop-zone {
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
  justify-content: center;
  border: 1px dashed var(--cc-border-strong);
  border-radius: var(--cc-radius-panel);
  padding: 26px 14px;
  cursor: pointer;
  background: var(--cc-selected);
  text-align: center;
}
.drop-zone.disabled {
  cursor: default;
  opacity: 0.75;
}
.drop-hint {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.file-list {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
  display: grid;
  gap: 8px;
  max-height: 200px;
  overflow: auto;
}
.file-list li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
}
.file-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.link-btn {
  background: none;
  border: none;
  color: var(--cc-primary);
  cursor: pointer;
  font-size: var(--cc-font-aux);
  padding: 2px 4px;
}
.warnings {
  width: 100%;
  font-size: var(--cc-font-aux);
  color: var(--cc-blocked);
}
.warnings ul {
  margin: 4px 0 0;
  padding-left: 16px;
}
.empty-hint {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
  border: none !important;
}
.privacy-note {
  margin: 12px 0 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.error {
  color: var(--cc-blocked);
  font-size: var(--cc-font-aux);
  margin: 0;
}
.error-text {
  color: var(--cc-blocked);
}
@media (max-width: 1080px) {
  .intake-grid {
    grid-template-columns: minmax(0, 1fr);
    overflow: auto;
  }
}
</style>
