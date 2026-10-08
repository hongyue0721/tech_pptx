"""T12：DeckPatch 确定性应用引擎——模型只提议，服务器确定性应用（api.md §编辑）。

引擎是纯函数：不做 IO、不调模型。越权/结构非法的补丁在这里以
ModelOutputInvalid 收口（job=failed 路径由 worker 分类），与
"资料不足→blocked"严格分流（api.md:59 两类不能混淆）。
"""

import copy
import secrets
from typing import Callable, Optional

from pydantic import ValidationError

from courseware_core.errors import (
    CorpusChanged,
    ModelOutputInvalid,
    VersionConflict,
)
from courseware_core.models import DeckPatch, DeckSpec, Slide


def new_slide_id() -> str:
    return f"sld_{secrets.token_hex(8)}"


def relations_valid(slides: list[Slide], claims: list) -> bool:
    """claim/slide 引用关系与 id 唯一性门（T09 原实现迁入，生成与编辑共用一份真值）。"""
    claim_ids = [c.id for c in claims]
    slide_ids = [s.id for s in slides]
    if len(claim_ids) != len(set(claim_ids)) or len(slide_ids) != len(set(slide_ids)):
        return False
    known = set(claim_ids)
    for s in slides:
        for b in s.blocks:
            if b.type == "fact" and b.claim_id not in known:
                return False
    return True


def _require_target(target: str, authorized: set[str], slides: list[Slide]) -> int:
    if target not in authorized:
        raise ModelOutputInvalid(
            "operation targets a slide outside the authorized set",
            {"target_slide_id": target},
        )
    for index, slide in enumerate(slides):
        if slide.id == target:
            return index
    raise ModelOutputInvalid(
        "operation targets a slide that does not exist",
        {"target_slide_id": target},
    )


def _apply_reorder(slides: list[Slide], slide_ids: list[str]) -> list[Slide]:
    current = [s.id for s in slides]
    if sorted(slide_ids) != sorted(current):
        raise ModelOutputInvalid(
            "reorder must list every current slide exactly once",
            {"given": slide_ids, "current": current},
        )
    by_id = {s.id: s for s in slides}
    return [by_id[i] for i in slide_ids]


def _merge_claims(claims: list, incoming: list) -> list:
    known = {c.id: c for c in claims}
    merged = list(claims)
    for claim in incoming:
        existing = known.get(claim.id)
        if existing is not None:
            if existing.model_dump(mode="json") != claim.model_dump(mode="json"):
                # 共享 claim 被改写必须换新 ID（api.md:57）：同 ID 改内容会
                # 静默波及其他引用页，属于越权修改，不得伪装成正常补丁。
                raise ModelOutputInvalid(
                    "claim rewritten under an existing id; a new id is required",
                    {"claim_id": claim.id},
                )
            continue
        merged.append(claim)
        known[claim.id] = claim
    return merged


def apply_patch(
    deck: DeckSpec,
    patch: DeckPatch,
    *,
    authorized_slide_ids: list[str],
    new_id_factory: Optional[Callable[[], str]] = None,
) -> DeckSpec:
    """返回候选 DeckSpec（version=base+1，提交时服务端权威重排号）。

    非目标页不变性由构造保证：只有被授权目标的 slide 对象会被替换，
    claims 只增不改（同 id 改写直接拒绝），reorder 只改变数组顺序。
    """
    if patch.base_version != deck.version:
        raise VersionConflict(
            {"patch_base": patch.base_version, "deck_version": deck.version}
        )
    if patch.corpus_revision != deck.corpus_revision:
        raise CorpusChanged(
            {"patch_corpus": patch.corpus_revision, "deck_corpus": deck.corpus_revision}
        )
    factory = new_id_factory or new_slide_id
    authorized = set(authorized_slide_ids)
    claims = _merge_claims(deck.claims, patch.claims)
    slides = copy.deepcopy(deck.slides)
    for operation in patch.operations:
        if operation.op == "reorder_slides":
            slides = _apply_reorder(slides, operation.slide_ids)
        elif operation.op == "replace_slide":
            index = _require_target(operation.target_slide_id, authorized, slides)
            if operation.slide.id != operation.target_slide_id:
                # 替换页换 id 等价于"删一页+插一页"，超出 replace 授权语义。
                raise ModelOutputInvalid(
                    "replacement slide id must equal target_slide_id",
                    {"target_slide_id": operation.target_slide_id,
                     "slide_id": operation.slide.id},
                )
            slides[index] = copy.deepcopy(operation.slide)
        elif operation.op == "split_slide":
            index = _require_target(operation.target_slide_id, authorized, slides)
            first = operation.slides[0].model_copy(
                update={"id": operation.target_slide_id}
            )
            second = operation.slides[1].model_copy(update={"id": factory()})
            slides[index : index + 1] = [copy.deepcopy(first), copy.deepcopy(second)]
        else:  # pragma: no cover - discriminated union 已封闭三种 op
        # 兜底：新增 op 类型必须先在此登记，不得静默放行未审计的补丁动作。
            raise ModelOutputInvalid(
                "unsupported patch operation", {"op": operation.op}
            )
    candidate = deck.model_copy(
        update={"slides": slides, "claims": claims, "version": deck.version + 1}
    )
    # model_copy 不重校验：以 dump→validate 强制结果仍是合法 DeckSpec
    # （重复 id、超限页数等结构问题在这里拦截，不留给下游）。
    # N-3：结构溢出（split 超 16 页等）=模型越界产出，typed 收口
    # MODEL_OUTPUT_INVALID，不得以 ValidationError 冒泡成 INTERNAL_ERROR。
    try:
        return DeckSpec.model_validate(candidate.model_dump(mode="json"))
    except ValidationError as exc:
        raise ModelOutputInvalid(
            "patched deck exceeds DeckSpec bounds",
            {"errors": str(exc)[:600]},
        ) from exc


def moved_slide_ids(before: list[Slide], after: list[Slide]) -> list[str]:
    """按位置比较受影响页：仅顺序变化的页计入。"""
    after_ids = [s.id for s in after]
    if len(before) != len(after_ids):
        return [s.id for s in after]
    return [old.id for old, new_id in zip(before, after_ids) if old.id != new_id]
