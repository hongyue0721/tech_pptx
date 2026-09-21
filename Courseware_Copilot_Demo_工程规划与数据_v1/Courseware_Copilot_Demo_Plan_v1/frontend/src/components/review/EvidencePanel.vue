<script setup lang="ts">
import { computed } from "vue";

import type { Claim, EvidenceSpan, Slide } from "../../types/models";

const props = defineProps<{ slide: Slide | null; claims: Claim[] }>();
const emit = defineEmits<{ openEvidence: [span: EvidenceSpan] }>();

interface EvidenceRow {
  key: string;
  kindLabel: string;
  text: string;
  missing: boolean;
  refs: EvidenceSpan[];
}

const rows = computed<EvidenceRow[]>(() => {
  const out: EvidenceRow[] = [];
  const byId = new Map(props.claims.map((c) => [c.id, c]));
  props.slide?.blocks.forEach((b, bi) => {
    if (b.type === "fact") {
      const c = byId.get(b.claim_id);
      out.push({
        key: `f${bi}`,
        kindLabel: "事实",
        text: c?.text ?? "该条引用未建立，查看核验报告",
        missing: !c,
        refs: c?.evidence_refs ?? [],
      });
    } else if (b.type === "illustration") {
      out.push({
        key: `i${bi}`,
        kindLabel: "示例",
        text: b.text,
        missing: false,
        refs: b.evidence_refs,
      });
    }
  });
  return out;
});
</script>

<template>
  <div class="ep">
    <p class="ep-hint">本页依据（服务器定位结果）：</p>
    <p v-if="!rows.length" class="ep-none">
      本页为封面或讲授页，不引用事实依据。
    </p>
    <ul v-else class="ep-list">
      <li v-for="r in rows" :key="r.key">
        <p class="ep-text" :class="{ missing: r.missing }">
          <span class="ep-tag">{{ r.kindLabel }}</span>{{ r.text }}
        </p>
        <p v-if="r.missing" class="ep-note">引用缺失：不静默删除，请查看核验报告。</p>
        <ul v-else class="ep-refs">
          <li v-for="(ref, ri) in r.refs" :key="ri">
            第 {{ ref.pdf_page }} 页 · 片段 {{ ref.chunk_id.slice(0, 8) }}…
            <button
              type="button"
              class="ep-link"
              @click="emit('openEvidence', ref)"
            >查看原文</button>
          </li>
          <li v-if="!r.refs.length" class="ep-note">该条没有服务器定位的证据片段。</li>
        </ul>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.ep {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: var(--cc-font-aux);
}
.ep-hint {
  margin: 0;
  color: var(--cc-ink-weak);
}
.ep-none {
  margin: 0;
  color: var(--cc-ink-weak);
}
.ep-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.ep-list li {
  border-bottom: 1px solid var(--cc-border);
  padding-bottom: 8px;
}
.ep-text {
  margin: 0;
  font-size: var(--cc-font-ui);
}
.ep-text.missing {
  color: var(--cc-blocked);
}
.ep-tag {
  font-size: 11px;
  color: var(--cc-primary);
  border: 1px solid var(--cc-primary);
  border-radius: 4px;
  padding: 0 5px;
  margin-right: 6px;
}
.ep-refs {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 2px;
  color: var(--cc-ink-weak);
}
.ep-note {
  margin: 4px 0 0;
  color: var(--cc-blocked);
}
.ep-link {
  background: none;
  border: none;
  color: var(--cc-primary);
  cursor: pointer;
  padding: 0 2px;
  font-size: inherit;
}
.ep-link:disabled {
  color: var(--cc-ink-weak);
  cursor: default;
}
</style>
