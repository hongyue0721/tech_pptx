<script setup lang="ts">
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { describeError } from "../../api/errorMessages";
import { canonicalize, editKey } from "../../api/idempotency";
import { editsApi } from "../../api/resources";
import type { EditRequest, Project, Slide } from "../../types/models";

const props = defineProps<{
  project: Project | null;
  slides: Slide[];
  corpusRevision: number;
}>();
const emit = defineEmits<{ accepted: [jobId: string] }>();

const selected = ref(1);
const busy = ref(false);
const errorText = ref("");

const currentVersion = computed(() => props.project?.current_version ?? 0);
const slideCount = computed(() => props.slides.length);
const active = computed(() => props.project?.active_job_id ?? null);
const busyReason = computed(() => {
  if (!props.project) return "项目信息未就绪";
  if (active.value) return "该项目正在执行其他任务，完成或取消后才能移动页面";
  if (slideCount.value < 2) return "至少两页才能移动";
  return "";
});

// 候选应用/恢复后页数可能变化：选中位置跟随收缩，防越界残留（Review Q3）。
watch(slideCount, (n) => {
  if (selected.value > n) selected.value = Math.max(1, n);
});

function canMove(from: number): boolean {
  return !busyReason.value && from >= 1 && from <= slideCount.value;
}

async function move(from: number, to: number): Promise<void> {
  if (!canMove(from) || to < 1 || to > slideCount.value || busy.value) return;
  busy.value = true;
  errorText.value = "";
  const ids = Array.from({ length: props.slides.length }, (_, i) => i + 1);
  const [moved] = ids.splice(from - 1, 1);
  ids.splice(to - 1, 0, moved);
  // 页 ID 真源=服务器 deck 的当前顺序，位置映射到实际 slide.id。
  const mapped = ids.map((pos) => props.slides[pos - 1]!.id);
  const instruction = JSON.stringify({ action: "reorder", slide_ids: mapped });
  const body: EditRequest = {
    instruction,
    target_slide_ids: mapped,
    base_version: currentVersion.value,
    corpus_revision: props.corpusRevision,
  };
  try {
    const accepted = await editsApi.create(
      props.project!.id,
      body,
      editKey(
        props.project!.id,
        currentVersion.value,
        props.corpusRevision,
        canonicalize(body),
      ),
    );
    emit("accepted", accepted.job_id);
  } catch (err) {
    errorText.value = err instanceof ApiError ? describeError(err).message : String(err);
    // 同键重试=重新执行（占位回滚语义）；移动目标变化由载荷自然换键。
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="move-zone">
    <label class="move-field">
      <span>移动第几页</span>
      <select v-model.number="selected">
        <option v-for="i in slideCount" :key="i" :value="i">第 {{ i }} 页</option>
      </select>
    </label>
    <div class="move-actions">
      <button
        type="button"
        :disabled="!canMove(selected) || selected <= 1"
        aria-label="上移一页"
        @click="move(selected, selected - 1)"
      >↑ 上移</button>
      <button
        type="button"
        :disabled="!canMove(selected) || selected >= slideCount"
        aria-label="下移一页"
        @click="move(selected, selected + 1)"
      >↓ 下移</button>
      <span v-if="busy" class="move-busy">提交中…</span>
    </div>
    <p v-if="busyReason" class="move-hint">{{ busyReason }}</p>
    <p v-if="errorText" class="move-error" role="alert">移动未受理：{{ errorText }}</p>
    <p class="move-note">移动是确定性操作（不外发模型内容），仍按候选确认流程生成新版本。</p>
  </div>
</template>

<style scoped>
.move-zone {
  display: grid;
  gap: 8px;
}
.move-field {
  display: grid;
  gap: 4px;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.move-field select {
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
  padding: 6px 8px;
  font: inherit;
  color: var(--cc-ink);
}
.move-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.move-actions button {
  border: 1px solid var(--cc-border-strong);
  border-radius: var(--cc-radius-control);
  background: var(--cc-panel);
  color: var(--cc-ink);
  font: inherit;
  font-size: var(--cc-font-aux);
  padding: 6px 10px;
  cursor: pointer;
}
.move-actions button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.move-busy,
.move-hint,
.move-note {
  margin: 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  line-height: 1.5;
}
.move-error {
  margin: 0;
  color: var(--cc-blocked);
  font-size: var(--cc-font-aux);
}
</style>
