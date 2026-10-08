<script setup lang="ts">
import { AButton } from "@any-design/anyui/vue";
import { computed, ref } from "vue";

import { ApiError } from "../../api/client";
import { describeError } from "../../api/errorMessages";
import { canonicalize, editKey } from "../../api/idempotency";
import { editsApi } from "../../api/resources";
import type { EditRequest, Slide } from "../../types/models";

const props = defineProps<{
  projectId: string;
  slides: Slide[];
  baseVersion: number;
  corpusRevision: number;
  disabled: boolean;
  disabledReason: string;
}>();
const emit = defineEmits<{ accepted: [jobId: string] }>();

const INTENTS = [
  { value: "condense", label: "精简", hint: "压缩本页文字，保留知识点与既有依据" },
  { value: "rephrase", label: "重述", hint: "换更口语的讲法重新表述本页" },
  { value: "split", label: "拆页", hint: "把本页拆成两页完整内容" },
] as const;

const intent = ref<string>(INTENTS[0].value);
const extra = ref("");
const selectedIds = ref<string[]>([]);
const submitting = ref(false);
const errorText = ref("");

const canSubmit = computed(() => {
  if (props.disabled || submitting.value) return false;
  if (selectedIds.value.length === 0) return false;
  if (extra.value.trim().length > 200) return false;
  return true;
});

const submitHint = computed(() => {
  if (props.disabled) return props.disabledReason;
  if (selectedIds.value.length === 0) return "请先在左侧页面列表勾选要编辑的页";
  if (extra.value.trim().length > 200) return "补充说明不能超过 200 字";
  return "";
});

function toggleSlide(id: string): void {
  const at = selectedIds.value.indexOf(id);
  if (at >= 0) selectedIds.value.splice(at, 1);
  else if (selectedIds.value.length < 12) selectedIds.value.push(id);
}

function buildInstruction(): string {
  const meta = INTENTS.find((i) => i.value === intent.value);
  const note = extra.value.trim();
  return note ? `${meta?.hint ?? ""}。补充要求：${note}` : (meta?.hint ?? "");
}

async function submit(): Promise<void> {
  if (!canSubmit.value) return;
  submitting.value = true;
  errorText.value = "";
  const body: EditRequest = {
    instruction: buildInstruction(),
    target_slide_ids: [...selectedIds.value],
    base_version: props.baseVersion,
    corpus_revision: props.corpusRevision,
  };
  try {
    const accepted = await editsApi.create(
      props.projectId,
      body,
      editKey(
        props.projectId,
        props.baseVersion,
        props.corpusRevision,
        canonicalize(body),
      ),
    );
    emit("accepted", accepted.job_id);
  } catch (err) {
    errorText.value = err instanceof ApiError ? describeError(err).message : String(err);
    // 失败时服务端占位已回滚：同键重试=重新执行；教师改配置后载荷变化
    // 自然构成新键（无 attempt 维度，与 restoreKey 同策略，Review N3）。
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <form class="edit-panel" @submit.prevent="submit">
    <p class="edit-note">
      编辑只产出候选稿：服务器核验通过并经教师"应用"后才成为正式版本，当前版本不会被直接改动。
    </p>
    <fieldset class="intent-set">
      <legend>编辑意图（应用于勾选页）</legend>
      <label v-for="i in INTENTS" :key="i.value" class="intent-row">
        <input v-model="intent" type="radio" name="edit-intent" :value="i.value" />
        <span class="intent-label">{{ i.label }}</span>
        <span class="intent-hint">{{ i.hint }}</span>
      </label>
    </fieldset>
    <div class="target-set" role="group" aria-label="选择要编辑的页">
      <p class="target-title">勾选目标页（最多 12 页）</p>
      <label v-for="(s, i) in props.slides" :key="s.id" class="target-row">
        <input
          type="checkbox"
          :checked="selectedIds.includes(s.id)"
          :disabled="!selectedIds.includes(s.id) && selectedIds.length >= 12"
          @change="toggleSlide(s.id)"
        />
        <span class="slide-no">{{ String(i + 1).padStart(2, "0") }}</span>
        <span class="slide-title">{{ s.title }}</span>
      </label>
    </div>
    <label class="extra-field">
      <span>补充说明（可选，≤200 字）</span>
      <input v-model="extra" type="text" maxlength="200" placeholder="例如：讲给没学过中断的同学" />
    </label>
    <p v-if="errorText" class="edit-error" role="alert">编辑未受理：{{ errorText }}</p>
    <div class="edit-actions">
      <AButton
        type="primary"
        :disabled="!canSubmit"
        :title="submitHint || '提交后生成编辑候选'"
        @click="submit"
      >
        {{ submitting ? "提交中…" : "生成编辑候选" }}
      </AButton>
      <span v-if="submitHint" class="hint-text">{{ submitHint }}</span>
    </div>
  </form>
</template>

<style scoped>
.edit-panel {
  display: grid;
  gap: 12px;
}
.edit-note {
  margin: 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  line-height: 1.5;
}
.intent-set,
.target-set {
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
  padding: 10px 12px;
  margin: 0;
  display: grid;
  gap: 6px;
}
.intent-set legend,
.target-title {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  padding: 0 4px;
  margin: 0 0 2px;
}
.intent-row,
.target-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: var(--cc-font-body);
}
.intent-label {
  font-weight: 600;
  white-space: nowrap;
}
.intent-hint {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
}
.target-row .slide-no {
  color: var(--cc-ink-weak);
  font-variant-numeric: tabular-nums;
}
.target-row .slide-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.extra-field {
  display: grid;
  gap: 4px;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.extra-field input {
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
  padding: 6px 8px;
  font: inherit;
  color: var(--cc-ink);
}
.edit-error {
  margin: 0;
  color: var(--cc-blocked);
  font-size: var(--cc-font-aux);
}
.edit-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.hint-text {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
</style>
