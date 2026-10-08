import type { ValidationReport } from "../types/models";

// ADR-12 partial 教师核准通道的前端派生（展示与门控用）。
// 规则与后端 courseware_core/services/claim_verdicts.partial_approval_channel
// 同口径——服务器 commit 时以权威推导复核，本函数不是放行依据。
export function partialApprovalChannel(v: ValidationReport): string[] | null {
  if (v.warnings.length > 0 || v.unbound_assertions.length > 0) return null;
  if (!v.schema_valid || !v.layout_valid) return null;
  const ids = v.claim_checks.map((c) => c.claim_id);
  if (ids.length === 0 || new Set(ids).size !== ids.length) return null;
  const partials = v.claim_checks
    .filter((c) => c.semantic_status === "partial")
    .map((c) => c.claim_id);
  if (partials.length === 0) return null;
  if (
    v.claim_checks.some(
      (c) => c.semantic_status !== "supported" && c.semantic_status !== "partial",
    )
  ) {
    return null;
  }
  return partials;
}
