<script setup lang="ts">
import { ADrawer } from "@any-design/anyui/vue";
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { describeError } from "../../api/errorMessages";
import { evidenceApi } from "../../api/resources";
import type { DocumentChunk, EvidenceSpan } from "../../types/models";
import { codePointSplit } from "../../utils/textOffset";

const props = defineProps<{
  modelValue: boolean;
  projectId: string;
  corpusRevision: number | null;
  span: EvidenceSpan | null;
}>();
const emit = defineEmits<{ "update:modelValue": [open: boolean] }>();

const chunkCache = new Map<string, DocumentChunk>();

const chunk = ref<DocumentChunk | null>(null);
const loading = ref(false);
const errorText = ref("");
let controller: AbortController | null = null;
let epoch = 0;

const segments = computed(() => {
  if (!chunk.value || !props.span) return null;
  return codePointSplit(chunk.value.text, props.span.start, props.span.end);
});
const quoteMatches = computed(
  () => segments.value !== null && segments.value.middle === props.span?.quote,
);
const title = computed(() => {
  if (!chunk.value) return "原文片段";
  const page = chunk.value.printed_page_label ?? `第 ${chunk.value.pdf_page} 页`;
  return `${chunk.value.document_name} · ${page}`;
});

async function load(): Promise<void> {
  epoch += 1;
  const myEpoch = epoch;
  controller?.abort();
  controller = new AbortController();
  const span = props.span;
  if (!props.modelValue || !span || props.corpusRevision === null) {
    chunk.value = null;
    loading.value = false;
    return;
  }
  const cacheKey = `${props.projectId}|${props.corpusRevision}|${span.chunk_id}`;
  const cached = chunkCache.get(cacheKey);
  if (cached !== undefined) {
    chunk.value = cached;
    errorText.value = "";
    loading.value = false;
    return;
  }
  loading.value = true;
  errorText.value = "";
  chunk.value = null;
  try {
    const d = await evidenceApi.get(
      props.projectId,
      span.chunk_id,
      props.corpusRevision,
      controller.signal,
    );
    if (myEpoch !== epoch) return;
    chunkCache.set(cacheKey, d);
    chunk.value = d;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    if (myEpoch !== epoch) return;
    errorText.value =
      err instanceof ApiError ? describeError(err).message : String(err);
  } finally {
    if (myEpoch === epoch) loading.value = false;
  }
}

watch(() => [props.modelValue, props.span?.chunk_id, props.corpusRevision], () => void load());

function close(): void {
  emit("update:modelValue", false);
}
</script>

<template>
  <ADrawer
    :model-value="props.modelValue"
    position="right"
    :width="420"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="ed">
      <div class="ed-head">
        <h2 class="ed-title">{{ title }}</h2>
        <button type="button" class="ed-close" aria-label="关闭原文" @click="close">×</button>
      </div>
      <p v-if="props.span" class="ed-meta">
        片段 {{ props.span.chunk_id }} · 偏移 [{{ props.span.start }}, {{ props.span.end }})（码点）
      </p>
      <p v-if="loading" class="ed-hint">正在读取原文…</p>
      <p v-else-if="errorText" class="ed-error" role="alert">原文读取失败：{{ errorText }}</p>
      <template v-else-if="chunk && segments">
        <p v-if="!quoteMatches" class="ed-error" role="alert">
          偏移切片与引用文本不一致，以下按服务器原文如实展示，引用单独列出，请谨慎对照。
        </p>
        <p class="ed-text">
          {{ segments.before }}<mark class="ed-mark">{{ segments.middle }}</mark>{{ segments.after }}
        </p>
        <h3 class="ed-sub">引用文本（claim 定位的 quote）</h3>
        <blockquote class="ed-quote">{{ props.span?.quote }}</blockquote>
      </template>
    </div>
  </ADrawer>
</template>

<style scoped>
.ed {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px 18px;
  font-size: var(--cc-font-ui);
}
.ed-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ed-title {
  flex: 1;
  min-width: 0;
  font-size: var(--cc-font-section);
  margin: 0;
}
.ed-close {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: var(--cc-ink-weak);
}
.ed-meta {
  margin: 0;
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
  word-break: break-all;
}
.ed-hint {
  margin: 0;
  color: var(--cc-ink-weak);
}
.ed-error {
  margin: 0;
  color: var(--cc-blocked);
}
.ed-text {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 46vh;
  overflow: auto;
}
.ed-mark {
  background: #f5e6c8;
  color: inherit;
  padding: 1px 2px;
  border-radius: 3px;
}
.ed-sub {
  margin: 6px 0 0;
  font-size: var(--cc-font-ui);
}
.ed-quote {
  margin: 0;
  padding: 8px 12px;
  border-left: 3px solid var(--cc-primary);
  background: var(--cc-selected);
  color: var(--cc-ink);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
