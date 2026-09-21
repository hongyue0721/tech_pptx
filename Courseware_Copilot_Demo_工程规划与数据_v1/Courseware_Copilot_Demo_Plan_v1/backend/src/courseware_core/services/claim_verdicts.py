"""verdict→ClaimVerification 的纯函数映射（T09 生成与 T12 编辑共用一份真值）。

可信链硬规则（2026-09-20 固化）：严格双射——verdict 造新 claim ID=整批不采信；
重复/漏答=not_checked 不盖绿；locator 失败的 claim 不进语义队列。
"""

from courseware_core.models import Claim, ClaimVerification, SemanticVerdicts


def map_verdicts(
    verdicts: SemanticVerdicts, expected_ids: set[str]
) -> tuple[dict, set[str], set[str]]:
    """返回 (checks_map, duplicate_ids, extra_ids)。

    同一 claim_id 重复答复：整条记入 duplicate_ids 并从 checks_map 移除
    （T09-Review B2：不得保留首条把 unsupported 盖成 supported）。
    """
    checks_map: dict[str, object] = {}
    duplicate_ids: set[str] = set()
    extra_ids: set[str] = set()
    for check in verdicts.checks:
        if check.claim_id not in expected_ids:
            extra_ids.add(check.claim_id)
            continue
        if check.claim_id in checks_map:
            checks_map.pop(check.claim_id)
            duplicate_ids.add(check.claim_id)
            continue
        checks_map[check.claim_id] = check
    return checks_map, duplicate_ids, extra_ids


def verdicts_to_checks(
    located: list[Claim],
    checks_map: dict,
    duplicate_ids: set[str],
    extra_ids: set[str],
) -> list[ClaimVerification]:
    if extra_ids:
        # 答复失控=整批核验不可信（AGENT_00-Q03），不采信其余"正常"条目。
        return [
            ClaimVerification(
                claim_id=c.id,
                locator_status="located",
                semantic_status="not_checked",
                reason=(
                    "semantic verdicts contained unknown claim ids: "
                    + ",".join(sorted(extra_ids)[:5])
                )[:600],
            )
            for c in located
        ]
    checks: list[ClaimVerification] = []
    for c in located:
        if c.id in duplicate_ids:
            checks.append(
                ClaimVerification(
                    claim_id=c.id,
                    locator_status="located",
                    semantic_status="not_checked",
                    reason="semantic model returned duplicate verdicts for this claim",
                )
            )
            continue
        verdict = checks_map.get(c.id)
        if verdict is None:
            # 漏答不得跳过变绿：记 not_checked → 门自然不过。
            checks.append(
                ClaimVerification(
                    claim_id=c.id,
                    locator_status="located",
                    semantic_status="not_checked",
                    reason="semantic model returned no verdict for this claim",
                )
            )
        else:
            checks.append(
                ClaimVerification(
                    claim_id=c.id,
                    locator_status="located",
                    semantic_status=verdict.status,
                    reason=verdict.reason,
                )
            )
    return checks
