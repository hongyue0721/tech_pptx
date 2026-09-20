"""T09 生成/核验的模型消息装配（纯函数，与编排逻辑分离）。

分区结构（docs/06:43）：教师输入、允许片段、输出 Schema 指引各自独立成段；
修复请求在同结构上追加【修复要求】，模型必须重出完整批次。
"""

import json

from courseware_core.models import Claim, ContentProposal, CourseBrief, Slide


def content_messages(
    course: CourseBrief,
    batch: list,
    selected: list,
    *,
    system_body: str,
    system_ver: str,
    repair_note: str | None = None,
    prior: ContentProposal | None = None,
) -> list[dict]:
    system = f"[prompt_version={system_ver}]\n{system_body}"
    pages = "\n".join(
        f"- {s.id}｜{s.title}｜{s.purpose}｜layout={s.layout}" for s in batch
    )
    chunks = "\n".join(f"[{hit.chunk_id}] {hit.text}" for _, hit in selected)
    user = (
        f"【课程】{course.topic}｜{course.audience}\n"
        f"【教师已确认计划页（slides 必须逐页覆盖这些 id，不得增删页）】\n{pages}\n"
        f"【允许教材片段（evidence 只能引用以下片段 id，quote 必须是对应原文的精确唯一子串）】\n{chunks}\n"
        f"【输出】ContentProposal JSON：claims（ClaimProposal）+ slides（fact 只引用"
        f" claim_id）。无法获得支持的部分写入 missing_evidence，不得编造引用补齐。"
    )
    if prior is not None:
        user += (
            "\n【你上一轮的输出（引用定位失败，需修正）】\n"
            + json.dumps(prior.model_dump(mode="json"), ensure_ascii=False)
        )
    if repair_note:
        user += f"\n【修复要求】{repair_note}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def verify_messages(
    located: list[Claim],
    batch_slides: list[Slide],
    *,
    system_body: str,
    system_ver: str,
) -> list[dict]:
    system = f"[prompt_version={system_ver}]\n{system_body}"
    claims_block = []
    for c in located:
        refs = "\n".join(
            f"  - 片段 {r.chunk_id}：{r.quote}" for r in c.evidence_refs
        )
        claims_block.append(f"【claim {c.id}】({c.kind}) {c.text}\n{refs}")
    visible = []
    for s in batch_slides:
        texts = [s.title] + [b.text for b in s.blocks if hasattr(b, "text")]
        visible.append(f"- {s.id}：" + " / ".join(texts))
    user = (
        "【待核验 claims 与其精确片段】\n" + "\n".join(claims_block) + "\n"
        "【页面可见文字（审查无绑定证据的专业断言）】\n" + "\n".join(visible) + "\n"
        "【输出】SemanticVerdicts JSON：每个上述 claim_id 恰好一条 check；"
        "无 unbound 问题时 unbound_assertions 为空数组。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
