<script setup lang="ts">
// 轻量状态标签：状态必须搭配文字（不只靠颜色），语义来自服务器字段。
withDefaults(defineProps<{ tone: "ready" | "pending" | "failed" | "info" }>(), {
  tone: "info",
});
</script>

<template>
  <span class="status-tag" :class="`tone-${tone}`"><slot /></span>
</template>

<style scoped>
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--cc-font-aux);
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.status-tag::before {
  content: "";
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.tone-ready {
  color: var(--cc-success);
  border-color: var(--cc-success);
  background: #eef3ef;
}
.tone-pending {
  color: var(--cc-blocked);
  border-color: var(--cc-blocked);
  background: #f7f0e7;
}
.tone-failed {
  color: #8a2f2a;
  border-color: #8a2f2a;
  background: #f6ecec;
}
.tone-info {
  color: var(--cc-ink-weak);
  border-color: var(--cc-border-strong);
  background: var(--cc-selected);
}
</style>
