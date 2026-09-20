<script setup lang="ts">
import { AButton } from "@any-design/anyui/vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError, api } from "../api/client";
import { changesApi, deckApi } from "../api/resources";
import StatusTag from "../components/common/StatusTag.vue";
import CourseShell from "../layouts/CourseShell.vue";
import type { CandidateChange, DeckSpec, Project } from "../types/models";

const props = defineProps<{ id: string }>();
const route = useRoute();
const router = useRouter();

const project = ref<Project | null>(null);
const change = ref<CandidateChange | null>(null);
const deck = ref<DeckSpec | null>(null);
const loadError = ref("");
const activeTab = ref<"content" | "evidence" | "checks">("content");
const inspectorOpen = ref(false);
const selectedIndex = ref(0);
let controller: AbortController | null = null;
let epoch = 0;

const changeId = computed(() => (route.query.change as string | undefined) ?? "");
const version = computed(() => {
  const v = Number(route.query.version);
  return Number.isInteger(v) && v >= 1 ? v : null;
});

const currentDeck = computed<DeckSpec | null>(() =>
  version.value !== null ? deck.value : change.value?.candidate ?? null,
);
const isCandidate = computed(() => version.value === null && change.value !== null);
const selectedSlide = computed(
  () => currentDeck.value?.slides[selectedIndex.value] ?? null,
);
const claimsById = computed(() => {
  const map = new Map<string, NonNullable<typeof currentDeck.value>["claims"][number]>();
  for (const c of currentDeck.value?.claims ?? []) map.set(c.id, c);
  return map;
});

const changeState = computed(() => {
  if (!change.value) return null;
  const st = change.value.status;
  if (st === "ready" && change.value.validation.can_commit)
    return { tone: "ready" as const, label: "核验通过 · 未应用" };
  if (st === "committed") return { tone: "ready" as const, label: "已应用为正式版本" };
  if (st === "stale") return { tone: "pending" as const, label: "候选已过期" };
  return { tone: "failed" as const, label: "候选未通过核验" };
});

const canApply = computed(
  () =>
    change.value?.status === "ready" &&
    change.value.validation.can_commit === true &&
    version.value === null,
);

async function load(): Promise<void> {
  epoch += 1;
  const myEpoch = epoch;
  controller?.abort();
  controller = new AbortController();
  loadError.value = "";
  if (!changeId.value && version.value === null) {
    change.value = null;
    deck.value = null;
    return;
  }
  try {
    const p = await api.getProject(props.id, controller.signal);
    if (myEpoch !== epoch) return;
    project.value = p;
    if (changeId.value) {
      const ch = await changesApi.get(props.id, changeId.value, controller.signal);
      if (myEpoch !== epoch) return;
      change.value = ch;
    }
    if (version.value !== null) {
      const d = await deckApi.get(props.id, version.value, controller.signal);
      if (myEpoch !== epoch) return;
      deck.value = d;
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") return;
    if (myEpoch !== epoch) return;
    loadError.value = err instanceof ApiError ? err.message : String(err);
  }
}

watch([() => props.id, changeId, version], () => void load(), { immediate: true });
onBeforeUnmount(() => controller?.abort());

watch(currentDeck, (d) => {
  if (d && selectedIndex.value >= d.slides.length) selectedIndex.value = 0;
});

function goOutline(): void {
  void router.push({ name: "outline", params: { id: props.id } });
}

const footerText = computed(() => {
  if (loadError.value) return loadError.value;
  if (change.value && changeState.value?.label === "候选未通过核验") {
    return "存在未通过核验的事实，保留当前正式版本；可在右侧查看原因";
  }
  if (isCandidate.value) return "教师确认后才形成正式版本";
  if (version.value !== null) return `正式版本 v${version.value}`;
  return "没有可展示的候选或正式版本";
});
</script>

<template>
  <CourseShell :project-id="props.id" :project="project">
    <div v-if="loadError" class="empty-state" role="alert">
      <h2>读取失败</h2>
      <p class="error-text">{{ loadError }}</p>
      <AButton @click="load">重试</AButton>
    </div>
    <div v-else-if="!currentDeck" class="empty-state">
      <h2>还没有可审阅的内容</h2>
      <p>候选稿或正式版本需要先生成并确认大纲。页面按精确 change/version 参数恢复。</p>
      <AButton type="primary" @click="goOutline">前往大纲确认</AButton>
    </div>
    <div v-else class="review-grid">
      <nav class="panel nav-panel" aria-label="页导航">
        <h2 class="panel-title">{{ currentDeck.slides.length }} 页</h2>
        <ol>
          <li
            v-for="(s, i) in currentDeck.slides"
            :key="s.id"
            :class="{ selected: i === selectedIndex }"
          >
            <button type="button" @click="selectedIndex = i">
              <span class="slide-no">{{ String(i + 1).padStart(2, "0") }}</span>
              <span class="slide-title">{{ s.title }}</span>
            </button>
          </li>
        </ol>
      </nav>

      <section class="stage" aria-label="课件结构预览">
        <div class="stage-head">
          <h2 class="panel-title">课件结构预览</h2>
          <StatusTag v-if="isCandidate" :tone="changeState?.tone ?? 'info'">
            {{ changeState?.label }}
          </StatusTag>
          <StatusTag v-else tone="ready">正式版本 v{{ currentDeck.version }}</StatusTag>
          <button
            type="button"
            class="narrow-only inspector-toggle"
            @click="inspectorOpen = !inspectorOpen"
          >详情</button>
        </div>
        <div class="deck-frame" role="img" :aria-label="`第 ${selectedIndex + 1} 页结构预览`">
          <template v-if="selectedSlide">
            <h3 class="frame-title">{{ selectedSlide.title }}</h3>
            <ul class="frame-blocks">
              <li v-for="(b, bi) in selectedSlide.blocks" :key="bi" :class="`block-${b.type}`">
                <template v-if="b.type === 'fact'">
                  <span class="block-tag">事实</span>
                  {{ claimsById.get(b.claim_id)?.text ?? "该条引用未建立，查看核验报告" }}
                </template>
                <template v-else-if="b.type === 'teaching'">
                  <span class="block-tag">讲授</span>{{ b.text }}
                </template>
                <template v-else>
                  <span class="block-tag">示例</span>{{ b.text }}
                  <em v-for="a in b.assumptions" :key="a" class="assumption">（假设：{{ a }}）</em>
                </template>
              </li>
            </ul>
          </template>
        </div>
        <div class="pager">
          <button
            type="button"
            :disabled="selectedIndex === 0"
            @click="selectedIndex -= 1"
          >‹ 上一页</button>
          <span>{{ selectedIndex + 1 }} / {{ currentDeck.slides.length }}</span>
          <button
            type="button"
            :disabled="selectedIndex >= currentDeck.slides.length - 1"
            @click="selectedIndex += 1"
          >下一页 ›</button>
        </div>
        <p class="preview-note">结构预览（语义块布局），非 PowerPoint 渲染效果。</p>
      </section>

      <aside
        class="panel inspector"
        :class="{ open: inspectorOpen }"
        aria-label="当前页详情"
      >
        <div class="tabs" role="tablist">
          <button
            v-for="t in (['content', 'evidence', 'checks'] as const)"
            :key="t"
            role="tab"
            :aria-selected="activeTab === t"
            :class="{ active: activeTab === t }"
            @click="activeTab = t"
          >
            {{ t === "content" ? "内容" : t === "evidence" ? "依据" : "核验" }}
          </button>
          <button
            type="button"
            class="drawer-close narrow-only"
            aria-label="关闭详情"
            @click="inspectorOpen = false"
          >×</button>
        </div>
        <div v-if="activeTab === 'content'" class="tab-body">
          <template v-if="selectedSlide">
            <p class="ins-title">{{ selectedSlide.title }}</p>
            <p v-for="(b, bi) in selectedSlide.blocks" :key="bi" class="ins-block">
              <span class="block-tag">{{ b.type === "fact" ? "事实" : b.type === "teaching" ? "讲授" : "示例" }}</span>
              <template v-if="b.type === 'fact'">{{ claimsById.get(b.claim_id)?.text ?? "引用未建立" }}</template>
              <template v-else>{{ b.text }}</template>
            </p>
          </template>
        </div>
        <div v-else-if="activeTab === 'evidence'" class="tab-body">
          <p class="ins-hint">本页依据（服务器定位结果）：</p>
          <ul class="ev-list">
            <li v-for="c in currentDeck.claims" :key="c.id">
              <p class="ev-claim">{{ c.text }}</p>
              <p v-for="(r, ri) in c.evidence_refs" :key="ri" class="ev-ref">
                {{ r.document_id }} · 第 {{ r.pdf_page }} 页
                <button type="button" class="link-btn" disabled title="原文抽屉随 F3 接通">查看原文</button>
              </p>
            </li>
          </ul>
        </div>
        <div v-else class="tab-body">
          <template v-if="change">
            <p class="ins-hint">候选核验报告（{{ change.validation.can_commit ? "全部通过" : "存在阻塞" }}）：</p>
            <ul class="check-list">
              <li v-for="ck in change.validation.claim_checks" :key="ck.claim_id">
                <StatusTag
                  :tone="ck.semantic_status === 'supported' && ck.locator_status === 'located' ? 'ready' : 'failed'"
                >{{ ck.locator_status === "invalid" ? "定位失败" : ck.semantic_status }}</StatusTag>
                <span class="check-reason">{{ ck.reason }}</span>
              </li>
              <li v-for="(u, ui) in change.validation.unbound_assertions" :key="`u${ui}`">
                <StatusTag tone="failed">未绑定断言</StatusTag>
                <span class="check-reason">{{ u.slide_id }} {{ u.field_path }}：{{ u.text }}</span>
              </li>
              <li v-for="(w, wi) in change.validation.warnings" :key="`w${wi}`">
                <StatusTag tone="pending">提示</StatusTag>
                <span class="check-reason">{{ w }}</span>
              </li>
            </ul>
          </template>
          <p v-else class="ins-hint">正式版本没有独立核验报告；核验结论以生成时的候选记录为准。</p>
        </div>
      </aside>
    </div>

    <template #footer-status>
      <span :class="{ 'error-text': Boolean(loadError) }">{{ footerText }}</span>
      <span v-if="project && isCandidate" class="ver-line">
        v{{ change?.base_version }} → 候选 v{{ (change?.base_version ?? 0) + 1 }}（未应用）
      </span>
    </template>
    <template #footer-actions>
      <AButton :disabled="!project" @click="goOutline">返回大纲</AButton>
      <AButton disabled title="导出模块（T10）尚未接通，接通后启用">导出 PPTX</AButton>
      <AButton
        type="primary"
        :disabled="!canApply"
        :title="canApply ? '教师确认后应用为正式版本' : '候选未通过核验或已过期时不可应用'"
        @click="() => {}"
      >
        应用此候选版本
      </AButton>
    </template>
  </CourseShell>
</template>

<style scoped>
.review-grid {
  height: 100%;
  display: grid;
  grid-template-columns: 174px minmax(0, 1fr) 300px;
  gap: var(--cc-gap-panel);
  min-height: 0;
}
.panel {
  background: var(--cc-panel);
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-panel);
  padding: 14px 16px;
  min-height: 0;
  overflow: auto;
}
.panel-title {
  font-size: var(--cc-font-section);
  margin-bottom: 10px;
}
.nav-panel ol {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.nav-panel li.selected {
  background: var(--cc-selected);
  border-radius: var(--cc-radius-control);
}
.nav-panel button {
  width: 100%;
  display: flex;
  gap: 8px;
  align-items: baseline;
  background: none;
  border: none;
  font: inherit;
  color: inherit;
  cursor: pointer;
  padding: 8px;
  text-align: left;
}
.slide-no {
  color: var(--cc-accent);
  font-size: var(--cc-font-aux);
}
.slide-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stage {
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.stage-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.deck-frame {
  flex: 1;
  min-height: 0;
  background: var(--cc-panel);
  border: 1px solid var(--cc-border);
  border-radius: var(--cc-radius-panel);
  aspect-ratio: 16 / 9;
  max-height: 100%;
  margin: 0 auto;
  width: 100%;
  padding: 22px 28px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.frame-title {
  font-size: 20px;
}
.frame-blocks {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
  font-size: var(--cc-font-ui);
}
.block-tag {
  font-size: 11px;
  color: var(--cc-primary);
  border: 1px solid var(--cc-primary);
  border-radius: 4px;
  padding: 0 5px;
  margin-right: 6px;
}
.assumption {
  color: var(--cc-ink-weak);
  font-size: var(--cc-font-aux);
}
.pager {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 8px 0 2px;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.pager button {
  background: none;
  border: 1px solid var(--cc-border-strong);
  border-radius: var(--cc-radius-control);
  padding: 3px 10px;
  cursor: pointer;
  color: var(--cc-ink);
}
.pager button:disabled {
  opacity: 0.5;
  cursor: default;
}
.preview-note {
  margin: 2px 0 0;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
  text-align: center;
}
.inspector {
  padding: 0;
  display: flex;
  flex-direction: column;
}
.tabs {
  display: flex;
  border-bottom: 1px solid var(--cc-border);
  flex-shrink: 0;
}
.tabs button {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 10px 0;
  font: inherit;
  color: var(--cc-ink-weak);
  cursor: pointer;
}
.tabs button.active {
  color: var(--cc-ink);
  font-weight: 600;
  border-bottom-color: var(--cc-primary);
}
.tab-body {
  padding: 12px 14px;
  overflow: auto;
  min-height: 0;
}
.ins-title {
  font-weight: 600;
  margin: 0 0 8px;
}
.ins-block {
  margin: 0 0 8px;
  font-size: var(--cc-font-ui);
}
.ins-hint {
  margin: 0 0 8px;
  font-size: var(--cc-font-aux);
  color: var(--cc-ink-weak);
}
.ev-list,
.check-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
  font-size: var(--cc-font-aux);
}
.ev-claim {
  margin: 0;
  font-weight: 500;
  font-size: var(--cc-font-ui);
}
.ev-ref {
  margin: 2px 0 0;
  color: var(--cc-ink-weak);
}
.link-btn {
  background: none;
  border: none;
  color: var(--cc-primary);
  cursor: pointer;
  padding: 0 2px;
  font-size: inherit;
}
.link-btn:disabled {
  color: var(--cc-ink-weak);
  cursor: default;
}
.check-reason {
  display: block;
  margin-top: 2px;
  color: var(--cc-ink-weak);
}
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--cc-ink-weak);
}
.empty-state h2 {
  color: var(--cc-ink);
  font-size: var(--cc-font-section);
}
.error-text {
  color: var(--cc-blocked);
}
.ver-line {
  margin-left: 10px;
}
.narrow-only {
  display: none;
}
.drawer-close {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--cc-ink-weak);
  padding: 0 10px;
}
.inspector-toggle {
  margin-left: auto;
  background: none;
  border: 1px solid var(--cc-border-strong);
  border-radius: var(--cc-radius-control);
  padding: 3px 10px;
  cursor: pointer;
  color: var(--cc-ink);
  font-size: var(--cc-font-aux);
}
@media (max-width: 1080px) {
  .review-grid {
    grid-template-columns: 150px minmax(0, 1fr);
  }
  .narrow-only {
    display: inline-flex;
  }
  .inspector {
    position: fixed;
    right: 0;
    top: 0;
    bottom: 0;
    width: 320px;
    z-index: 30;
    border-radius: 0;
    transform: translateX(105%);
    transition: transform 0.18s ease;
    box-shadow: -6px 0 24px rgba(37, 49, 68, 0.18);
  }
  .inspector.open {
    transform: translateX(0);
  }
}
</style>
