<script setup lang="ts">
// 兼容入口 /project/:id：按服务器真值转入相应页（API_UI_MATRIX D-04 口径）。
// 只用 Project 暴露的真值字段路由——active_job_id 与 current_version；
// 不猜 plan/change id（接口未提供"最新候选"查询，猜测=伪造定位状态）。
import { onMounted } from "vue";
import { useRouter, type RouteLocationRaw } from "vue-router";

import { api } from "../api/client";

const props = defineProps<{ id: string }>();
const router = useRouter();

onMounted(async () => {
  let target: RouteLocationRaw = { name: "materials", params: { id: props.id } };
  try {
    const p = await api.getProject(props.id);
    if (p.active_job_id === null && p.current_version >= 1) {
      // 无活动任务且已有正式版本：直落正式版本审阅视图（version 为服务器真值）。
      target = {
        name: "review",
        params: { id: props.id },
        query: { version: String(p.current_version) },
      };
    }
    // active_job_id 非空时留在资料页：其恢复链跟踪活动任务（parse/plan/generate
    // 终态按 kind 诚实处理）。
  } catch {
    // 读取失败回落资料页，由页面自己呈现真实错误态——入口不编造"加载成功"。
  }
  void router.replace(target);
});
</script>

<template>
  <p class="entry-loading">正在打开课题…</p>
</template>

<style scoped>
.entry-loading {
  padding: 24px;
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-ui);
}
</style>
