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


def _slide_visible_texts(s: Slide) -> list[str]:
    """页面全部可见文字：标题 + 各块 text + illustration 假设（审计输入唯一装配）。"""
    texts = [s.title]
    for idx, b in enumerate(s.blocks):
        if hasattr(b, "text"):
            texts.append(f"blocks[{idx}].text={b.text}")
        for a_idx, assumption in enumerate(getattr(b, "assumptions", []) or []):
            texts.append(f"blocks[{idx}].assumptions[{a_idx}]={assumption}")
    return texts


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
        visible.append(f"- {s.id}：" + " / ".join(_slide_visible_texts(s)))
    user = (
        "【待核验 claims 与其精确片段】\n" + "\n".join(claims_block) + "\n"
        "【页面可见文字（审查无绑定证据的专业断言）】\n" + "\n".join(visible) + "\n"
        "【输出】SemanticVerdicts JSON：每个上述 claim_id 恰好一条 check；"
        "无 unbound 问题时 unbound_assertions 为空数组。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def audit_messages(
    slides: list[Slide],
    located: list[Claim],
    required_ids: list[str],
    *,
    system_body: str,
    system_ver: str,
) -> list[dict]:
    """可见文字审计消息（与 claim 语义核验分离的独立通道）：豁免页不进
    必审清单；已绑定 claim 文本给出，模型只报"未被覆盖"的新专业断言。"""
    system = f"[prompt_version={system_ver}]\n{system_body}"
    visible = []
    for s in slides:
        if s.id in required_ids:
            visible.append(f"- {s.id}：" + " / ".join(_slide_visible_texts(s)))
    bound = "\n".join(f"- {c.id}: {c.text}" for c in located) or "（本批无已绑定claim）"
    user = (
        "【需审计页面（每页必须恰好返回一次 audited_slide_ids）】"
        + "、".join(required_ids) + "\n"
        "【页面可见文字】\n" + "\n".join(visible) + "\n"
        "【已绑定claim清单（这些内容已有证据，不算无绑定断言）】\n" + bound + "\n"
        "【输出】VisibleTextAudit JSON：audited_slide_ids 恰好覆盖需审计页面；"
        "unbound_assertions 列出未被清单覆盖的新专业断言（slide_id/field_path/text/reason）。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
