<script setup lang="ts">
import { AButton } from "@any-design/anyui/vue";
import { computed, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { describeError } from "../../api/errorMessages";
import { restoreKey } from "../../api/idempotency";
import { restoresApi } from "../../api/resources";
import type { Project, RestoreRequest } from "../../types/models";

const props = defineProps<{ project: Project | null }>();
const emit = defineEmits<{ restored: [version: number] }>();

const open = ref(false);
const target = ref(0);
const confirming = ref(false);
const busy = ref(false);
const errorText = ref("");

const currentVersion = computed(() => props.project?.current_version ?? 0);
const hasHistory = computed(() => currentVersion.value >= 2);

// 恢复=以旧版本内容创建新版本（docs/07 §5）；旧版本行不可变，无需逐行读取
// 历史内容即可列出可恢复目标（1..current-1）。逐版本内容查看走 ‹› 版本导航。
const targets = computed(() => {
  const list: number[] = [];
  for (let v = 1; v < currentVersion.value; v += 1) list.push(v);
  return list;
});

const busyReason = computed(() => {
  if (!props.project) return "项目信息未就绪";
  if (props.project.active_job_id) return "该项目正在执行其他任务，完成或取消后才能恢复版本";
  if (currentVersion.value < 2) return "至少有两个正式版本后才可恢复";
  return "";
});

watch(open, () => {
  errorText.value = "";
  confirming.value = false;
  target.value = hasHistory.value ? currentVersion.value - 1 : 0;
});

async function restore(): Promise<void> {
  const project = props.project;
  if (!project || target.value < 1 || busy.value) return;
  busy.value = true;
  errorText.value = "";
  const body: RestoreRequest = {
    target_version: target.value,
    base_version: project.current_version,
    corpus_revision: project.corpus_revision,
    acknowledged: true,
  };
  try {
    const dv = await restoresApi.create(
      project.id,
      body,
      restoreKey(project.id, body.target_version, body.base_version, body.corpus_revision),
    );
    emit("restored", dv.version);
    open.value = false;
  } catch (err) {
    // 409=基线/语料/锁冲突：如实呈现服务器事实，教师刷新基线后重试；
    // 键含 base_version，基线前进后自然构成新意图键。
    errorText.value = err instanceof ApiError ? describeError(err).message : String(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="history-zone">
    <button
      type="button"
      class="history-toggle"
      :aria-expanded="open"
      @click="open = !open"
    >版本历史与恢复</button>
    <div v-if="open" class="history-body">
      <p class="history-fact">
        当前正式版本 v{{ currentVersion }}。恢复不会删除历史，也不会回到旧编号：
        它以所选版本的内容创建一个新版本（例如 v{{ Math.max(currentVersion - 1, 1) }} → v{{ currentVersion + 1 }}）。
      </p>
      <p v-if="!hasHistory" class="history-hint">{{ busyReason || "至少有两个正式版本后才可恢复" }}</p>
      <template v-else>
        <label class="history-field">
          <span>恢复到版本内容</span>
          <select v-model.number="target">
            <option :value="0" disabled>请选择版本</option>
            <option v-for="v in targets" :key="v" :value="v">v{{ v }}</option>
          </select>
        </label>
        <label class="history-ack">
          <input v-model="confirming" type="checkbox" />
          <span>我已核对：恢复会以 v{{ target || "…" }} 的内容生成新版本 v{{ currentVersion + 1 }}，当前 v{{ currentVersion }} 及历史版本保持不变</span>
        </label>
        <p v-if="errorText" class="history-error" role="alert">恢复未成功：{{ errorText }}</p>
        <AButton
          type="primary"
          :disabled="!confirming || target < 1 || busy || Boolean(busyReason)"
          :title="busyReason || (confirming ? '以所选版本内容创建新版本' : '请先勾选确认')"
          @click="restore"
        >
          {{ busy ? "恢复中…" : "确认恢复" }}
        </AButton>
      </template>
    </div>
  </div>
</template>

<style scoped>
.history-zone {
  display: grid;
  gap: 8px;
}
.history-toggle {
  justify-self: start;
  background: none;
  border: none;
  color: var(--cc-primary);
  font: inherit;
  font-size: var(--cc-font-aux);
  cursor: pointer;
  padding: 2px 0;
  text-decoration: underline;
}
.history-body {
  display: grid;
  gap: 10px;
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
  padding: 10px 12px;
}
.history-fact,
.history-hint {
  margin: 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  line-height: 1.5;
}
.history-field {
  display: grid;
  gap: 4px;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.history-field select {
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-control);
  padding: 6px 8px;
  font: inherit;
  color: var(--cc-ink);
}
.history-ack {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: var(--cc-font-aux);
  line-height: 1.5;
}
.history-error {
  margin: 0;
  color: var(--cc-blocked);
  font-size: var(--cc-font-aux);
}
</style>
