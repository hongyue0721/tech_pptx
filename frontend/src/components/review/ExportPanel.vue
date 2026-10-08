<script setup lang="ts">
import { AButton } from "@any-design/anyui/vue";
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { describeError } from "../../api/errorMessages";
import { exportKey } from "../../api/idempotency";
import { exportsApi } from "../../api/resources";
import { useJobPolling } from "../../composables/useJobPolling";
import type { Job } from "../../types/models";

// T10 导出面板：固定版本 PPTX 渲染 job（只读快照，不占项目写锁）。
// succeeded 后产物下载链接常驻（含刷新恢复：?export_job= 由页面编排）；
// 失败/取消消耗 URL——幂等键=版本意图，占位回滚后同键重试即重新执行。
const props = defineProps<{
  projectId: string;
  version: number;
  initialJobId?: string | null;
}>();
const emit = defineEmits<{ (e: "update:jobId", value: string | null): void }>();

const jobId = ref<string | null>(props.initialJobId ?? null);
const settled = ref<Job | null>(null);
const errorText = ref("");
const starting = ref(false);

watch(
  () => props.initialJobId,
  (value) => {
    const next = value ?? null;
    if (next !== jobId.value) jobId.value = next;
  },
);

function onSettled(job: Job): void {
  if (job.status === "succeeded") {
    settled.value = job;
    return;
  }
  settled.value = null;
  errorText.value =
    job.status === "cancelled"
      ? "导出已取消。"
      : `导出失败：${job.error ? describeError(new ApiError(0, job.error)).message : "未知错误"}`;  emit("update:jobId", null);
}

function onHalted(): void {
  errorText.value = "无法获取导出任务状态，请刷新页面重试。";
  settled.value = null;
  emit("update:jobId", null);
}

const { isPolling, cancelling, requestCancel } = useJobPolling(jobId, {
  onSettled,
  onHalted: onHalted,
});

const pptxArtifactId = computed(() => {
  const job = settled.value;
  if (!job || job.status !== "succeeded" || job.result_ref?.type !== "artifact") return null;
  return job.result_ref.id;
});
// 伴随 evidence-report 的 id 规则是 api.md §版本/导出 的契约事实（art_{job}_report）。
const reportArtifactId = computed(() => {
  const id = pptxArtifactId.value;
  return id ? id.replace(/_pptx$/, "_report") : null;
});

async function startExport(): Promise<void> {
  if (starting.value || isPolling.value) return;
  starting.value = true;
  errorText.value = "";
  settled.value = null;
  try {
    const accepted = await exportsApi.create(
      props.projectId,
      { version: props.version, format: "pptx" },
      exportKey(props.projectId, props.version),
    );
    jobId.value = accepted.job_id;
    emit("update:jobId", accepted.job_id);
  } catch (error) {
    errorText.value = describeError(error).message;
  } finally {
    starting.value = false;
  }
}

const downloadUrl = (artifactId: string) => exportsApi.downloadUrl(props.projectId, artifactId);
</script>

<template>
  <span class="export-panel">
    <template v-if="pptxArtifactId">
      <a class="export-link" :href="downloadUrl(pptxArtifactId)">下载 PPTX（v{{ version }}）</a>
      <a
        v-if="reportArtifactId"
        class="export-link export-link-report"
        :href="downloadUrl(reportArtifactId)"
        title="每条事实对应的资料代号、页码与完整引用"
      >证据报告</a>
      <span class="export-note">按 v{{ version }} 导出；最终版式以 Office 打开导出文件为准。</span>
    </template>
    <template v-else>
      <AButton
        :disabled="starting || isPolling || version < 1"
        :title="version < 1 ? '尚无正式版本，应用候选后才可导出' : '把当前正式版本渲染为可编辑 PPTX'"
        @click="startExport"
      >
        {{ isPolling ? "渲染中…" : `导出 PPTX（v${version}）` }}
      </AButton>
      <AButton
        v-if="isPolling"
        :disabled="cancelling"
        :title="cancelling ? '已提交取消请求，等待服务器确认' : '请求取消导出'"
        @click="requestCancel"
      >
        {{ cancelling ? "取消中…" : "取消" }}
      </AButton>
    </template>
    <p v-if="errorText" class="export-error error-text" role="alert">{{ errorText }}</p>
  </span>
</template>

<style scoped>
.export-panel {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.export-link {
  color: var(--cc-accent, #2563eb);
  text-decoration: underline;
}
.export-note {
  font-size: 12px;
  color: var(--cc-text-muted, #6b7280);
}
.export-error {
  width: 100%;
  margin: 4px 0 0;
  font-size: 13px;
}
</style>
