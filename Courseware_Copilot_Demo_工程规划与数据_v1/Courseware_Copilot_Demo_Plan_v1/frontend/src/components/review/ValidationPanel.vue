<script setup lang="ts">
import { computed, ref } from "vue";

import StatusTag from "../common/StatusTag.vue";
import type { CandidateChange, Claim, ClaimVerification } from "../../types/models";

const props = defineProps<{ change: CandidateChange }>();

const claimsById = computed(() => {
  const map = new Map<string, Claim>();
  for (const c of props.change.candidate.claims) map.set(c.id, c);
  return map;
});

const gates = computed(() => {
  const v = props.change.validation;
  return [
    { label: "结构校验", ok: v.schema_valid },
    { label: "引用关系", ok: v.relations_valid },
    { label: "布局一致", ok: v.layout_valid },
  ];
});

const SEMANTIC: Record<
  ClaimVerification["semantic_status"],
  { label: string; tone: "ready" | "pending" | "failed" }
> = {
  supported: { label: "有依据", tone: "ready" },
  partial: { label: "部分依据", tone: "pending" },
  unsupported: { label: "无依据", tone: "failed" },
  conflict: { label: "与依据冲突", tone: "failed" },
  not_checked: { label: "未核验", tone: "failed" },
};

function checkTone(ck: ClaimVerification): "ready" | "pending" | "failed" {
  if (ck.locator_status === "invalid") return "failed";
  return SEMANTIC[ck.semantic_status].tone;
}

function checkLabel(ck: ClaimVerification): string {
  if (ck.locator_status === "invalid") return "定位失败";
  return SEMANTIC[ck.semantic_status].label;
}

function isPassed(ck: ClaimVerification): boolean {
  return ck.locator_status === "located" && ck.semantic_status === "supported";
}

const problemChecks = computed(() =>
  props.change.validation.claim_checks.filter((ck) => !isPassed(ck)),
);
const passedChecks = computed(() =>
  props.change.validation.claim_checks.filter(isPassed),
);
const showPassed = ref(false);

function claimText(claimId: string): string {
  return claimsById.value.get(claimId)?.text ?? "（该条引用未建立）";
}

const STATUS_LABEL: Record<CandidateChange["status"], string> = {
  ready: "就绪待应用",
  blocked: "未通过核验",
  committed: "已应用",
  discarded: "已丢弃",
  stale: "已过期",
};

const checkedAtText = computed(() => {
  const raw = props.change.validation.checked_at;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? raw : d.toLocaleString();
});
</script>

<template>
  <div class="vp">
    <p class="vp-hint">
      服务器核验结论（候选状态{{ STATUS_LABEL[props.change.status] }}，
      {{ props.change.validation.can_commit ? "可应用" : "不可应用" }}）：
    </p>
    <div class="vp-gates">
      <StatusTag v-for="g in gates" :key="g.label" :tone="g.ok ? 'ready' : 'failed'">
        {{ g.label }}{{ g.ok ? "通过" : "未通过" }}
      </StatusTag>
    </div>
    <p class="vp-trace">
      核验模型 {{ props.change.validation.model_id ?? "（无模型判定，仅结构校验）" }} ·
      prompt {{ props.change.validation.prompt_version }} ·
      {{ checkedAtText }}
    </p>

    <h3 class="vp-sub">需要关注的事实（{{ problemChecks.length }} 条）</h3>
    <p v-if="!problemChecks.length" class="vp-none">全部事实均有依据且定位成功。</p>
    <ul v-else class="vp-list">
      <li v-for="ck in problemChecks" :key="ck.claim_id">
        <StatusTag :tone="checkTone(ck)">{{ checkLabel(ck) }}</StatusTag>
        <p class="vp-claim">{{ claimText(ck.claim_id) }}</p>
        <p class="vp-reason">{{ ck.reason }}</p>
      </li>
    </ul>

    <template v-if="passedChecks.length">
      <button
        type="button"
        class="vp-toggle"
        :aria-expanded="showPassed"
        @click="showPassed = !showPassed"
      >
        已通过核验的事实（{{ passedChecks.length }} 条）{{ showPassed ? "收起" : "展开" }}
      </button>
      <ul v-if="showPassed" class="vp-list vp-list-passed">
        <li v-for="ck in passedChecks" :key="ck.claim_id">
          <StatusTag tone="ready">有依据</StatusTag>
          <p class="vp-claim">{{ claimText(ck.claim_id) }}</p>
        </li>
      </ul>
    </template>

    <template v-if="props.change.validation.unbound_assertions.length">
      <h3 class="vp-sub">未绑定断言（{{ props.change.validation.unbound_assertions.length }} 条）</h3>
      <ul class="vp-list">
        <li v-for="(u, ui) in props.change.validation.unbound_assertions" :key="`u${ui}`">
          <StatusTag tone="failed">未绑定</StatusTag>
          <p class="vp-claim">{{ u.slide_id }} · {{ u.field_path }}：{{ u.text }}</p>
          <p class="vp-reason">{{ u.reason }}</p>
        </li>
      </ul>
    </template>

    <template v-if="props.change.validation.warnings.length">
      <h3 class="vp-sub">证据缺口与边界声明（{{ props.change.validation.warnings.length }} 条）</h3>
      <ul class="vp-list vp-warnings">
        <li v-for="(w, wi) in props.change.validation.warnings" :key="`w${wi}`">
          {{ w }}
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.vp {
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: var(--cc-font-aux);
}
.vp-hint {
  margin: 0;
  color: var(--cc-ink-weak);
}
.vp-gates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.vp-trace {
  margin: 0;
  color: var(--cc-ink-weak);
  word-break: break-all;
}
.vp-sub {
  margin: 6px 0 0;
  font-size: var(--cc-font-ui);
}
.vp-none {
  margin: 0;
  color: var(--cc-success);
}
.vp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
}
.vp-list li {
  border-bottom: 1px solid var(--cc-border);
  padding-bottom: 8px;
}
.vp-list-passed li {
  border-bottom: none;
  padding-bottom: 4px;
}
.vp-claim {
  margin: 4px 0 0;
  font-size: var(--cc-font-ui);
}
.vp-reason {
  margin: 2px 0 0;
  color: var(--cc-ink-weak);
}
.vp-toggle {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--cc-primary);
  cursor: pointer;
  font: inherit;
  padding: 0;
}
.vp-warnings li {
  border-bottom: none;
  padding-bottom: 0;
  color: var(--cc-ink-weak);
}
</style>
