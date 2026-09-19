<script setup lang="ts">
import { onBeforeUnmount } from "vue";

import { useProject } from "../composables/useProject";

const props = defineProps<{ id: string }>();

const { project, state, errorMessage, abort } = useProject(props.id);

onBeforeUnmount(abort);
</script>

<template>
  <div class="workspace">
    <header class="topbar">
      <span class="course-name">{{ project?.course.topic ?? "加载中…" }}</span>
      <span v-if="project" class="version">v{{ project.current_version }}</span>
    </header>
    <div class="columns">
      <nav class="left" aria-label="页导航">
        <p class="placeholder">页导航（待 T08 实现）</p>
      </nav>
      <section class="center" aria-live="polite">
        <p v-if="state === 'loading'">正在加载项目…</p>
        <p v-else-if="state === 'unauthorized'">鉴权失效，请重新登录网关后再试。</p>
        <p v-else-if="state === 'not_found'">项目不存在，请返回<a href="/">首页</a>。</p>
        <p v-else-if="state === 'failed'">加载失败：{{ errorMessage }}</p>
        <p v-else>尚无正式课件。下一步：上传教材资料并生成教学大纲（待 T05/T07 实现）。</p>
      </section>
      <aside class="right">
        <p class="placeholder">AI 编辑面板（待 T09 实现）</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.workspace {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.topbar {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #ddd;
}
.columns {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 340px;
}
.left,
.right {
  border-right: 1px solid #eee;
  padding: 0.5rem;
  min-width: 0;
}
.right {
  border-right: none;
  border-left: 1px solid #eee;
}
.center {
  padding: 1rem;
  min-width: 0;
}
.placeholder {
  color: #888;
}
</style>
