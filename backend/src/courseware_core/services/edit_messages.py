"""T12 编辑意图的模型消息装配（纯函数，与编排逻辑分离，同 generate_messages 分区结构）。"""

import json

from courseware_core.models import Claim, CourseBrief, EditProposal, Slide


def edit_messages(
    course: CourseBrief,
    instruction: str,
    authorized_slide_ids: list[str],
    target_slides: list[Slide],
    existing_claims: list[Claim],
    deck_outline: list[Slide],
    selected: list,
    *,
    system_body: str,
    system_ver: str,
    repair_note: str | None = None,
    prior: EditProposal | None = None,
) -> list[dict]:
    system = f"[prompt_version={system_ver}]\n{system_body}"
    outline = "\n".join(f"- {s.id}｜{s.title}｜layout={s.layout}" for s in deck_outline)
    targets = "\n".join(
        "【" + s.id + "】"
        + json.dumps(s.model_dump(mode="json"), ensure_ascii=False)
        for s in target_slides
    )
    claims_block = "\n".join(
        f"- {c.id}（{c.kind}）：{c.text}" for c in existing_claims
    ) or "（目标页无既有claim）"
    chunks = "\n".join(f"[{hit.chunk_id}] {hit.text}" for _, hit in selected)
    user = (
        f"【课程】{course.topic}｜{course.audience}\n"
        f"【教师编辑指令】{instruction}\n"
        f"【授权目标页（operations 只能针对这些 id：{'、'.join(authorized_slide_ids)}）】\n"
        f"{targets}\n"
        f"【目标页既有claim（未变可直接复用其 id）】\n{claims_block}\n"
        f"【全课件页序（reorder 必须是这些 id 的全排列）】\n{outline}\n"
        f"【允许教材片段（evidence 只能引用以下片段 id，quote 必须是对应原文的精确唯一子串）】\n{chunks}\n"
        f"【输出】EditDecision JSON：可实现→"
        f'{{"decision":"proposal","proposal":{{"operations":[...],"claims":[...],'
        f'"summary":"...","missing_evidence":[...]}}}}；'
        f'超出允许意图→{{"decision":"unsupported","reason":"..."}}。'
        f"资料缺口写 missing_evidence，不得编造引用补齐。"
    )
    if prior is not None:
        user += (
            "\n【你上一轮的输出（引用定位失败，需修正）】\n"
            + json.dumps(prior.model_dump(mode="json"), ensure_ascii=False)
        )
    if repair_note:
        user += f"\n【修复要求】{repair_note}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
