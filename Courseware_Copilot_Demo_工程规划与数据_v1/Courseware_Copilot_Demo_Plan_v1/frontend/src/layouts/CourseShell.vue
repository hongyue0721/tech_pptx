<script setup lang="ts">
import { computed } from "vue";

import type { Project } from "../types/models";
import { projectSummary, useStepNav } from "./stepNav";

const props = defineProps<{
  projectId?: string;
  project?: Project | null;
}>();

const { active, steps } = useStepNav(() => props.projectId);
const summary = computed(() => projectSummary(props.project ?? null));
</script>

<template>
  <div class="course-shell">
    <header class="shell-header">
      <span class="brand">课研 <span class="brand-sub">Courseware Copilot</span></span>
      <span v-if="summary" class="header-summary">{{ summary }}</span>
    </header>
    <nav class="shell-steps" aria-label="教学流程">
      <ol>
        <li
          v-for="step in steps"
          :key="step.key"
          :class="{ active: active === step.key, disabled: !step.enabled }"
        >
          <RouterLink
            :to="step.to"
            :aria-current="active === step.key ? 'step' : undefined"
            :tabindex="step.enabled ? undefined : -1"
          >
            <span class="step-index">{{ step.index }}</span>{{ step.label }}
          </RouterLink>
        </li>
      </ol>
    </nav>
    <main class="shell-main">
      <slot />
    </main>
    <footer class="shell-footer">
      <div class="footer-status"><slot name="footer-status" /></div>
      <div class="footer-actions"><slot name="footer-actions" /></div>
    </footer>
  </div>
</template>

<style scoped>
.course-shell {
  height: 100dvh;
  display: grid;
  grid-template-rows: var(--cc-row-header) var(--cc-row-steps) minmax(0, 1fr) var(--cc-row-footer);
}
.shell-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 var(--cc-page-pad);
  background: var(--cc-panel);
  border-bottom: 1px solid var(--cc-border);
}
.brand {
  font-size: 19px;
  font-weight: 700;
  color: var(--cc-primary);
  font-family: "Songti SC", "Noto Serif CJK SC", Georgia, serif;
  white-space: nowrap;
}
.brand-sub {
  font-size: var(--cc-font-aux);
  font-weight: 500;
  color: var(--cc-ink-weak);
  font-family: inherit;
}
.header-summary {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.shell-steps ol {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 34px;
  margin: 0;
  padding: 0 var(--cc-page-pad);
  height: 100%;
}
.shell-steps li a {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  text-decoration: none;
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-ui);
  padding: 6px 2px;
  border-bottom: 2px solid transparent;
}
.shell-steps li.active a {
  color: var(--cc-ink);
  font-weight: 600;
  border-bottom-color: var(--cc-primary);
}
.shell-steps li.disabled a {
  color: var(--cc-border-strong);
  pointer-events: none;
}
.step-index {
  font-size: 11px;
  color: var(--cc-accent);
  font-variant-numeric: tabular-nums;
}
.shell-main {
  min-height: 0;
  overflow: hidden;
  padding: var(--cc-gap-panel) var(--cc-page-pad);
}
.shell-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 var(--cc-page-pad);
  background: var(--cc-panel);
  border-top: 1px solid var(--cc-border);
}
.footer-status {
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  min-width: 0;
}
.footer-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
}
</style>
