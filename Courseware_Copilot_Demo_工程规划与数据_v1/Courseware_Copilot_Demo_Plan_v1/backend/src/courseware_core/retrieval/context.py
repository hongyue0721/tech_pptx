"""证据上下文预算装配（docs/05 §9）：plan 与 generate 共用同一公平算法。

轮转（round-robin）而非先到先得：多目标/多页各自检索后按名次轮取，防止
后面的键被前面的键饿死；每键上限与全局字符预算双闸。
"""

from typing import Sequence

from courseware_core.retrieval.bm25 import RankedChunk


def select_evidence_within_budget(
    hits_by_key: dict[int, Sequence[RankedChunk]],
    *,
    per_key_max: int,
    char_budget: int,
) -> list[tuple[int, RankedChunk]]:
    selected: list[tuple[int, RankedChunk]] = []
    used_ids: set[str] = set()
    budget = char_budget
    for rank in range(per_key_max):
        for key in sorted(hits_by_key):
            hits = hits_by_key[key]
            if rank >= len(hits):
                continue
            hit = hits[rank]
            if hit.chunk_id in used_ids:
                continue
            if budget - len(hit.text) < 0:
                return selected
            used_ids.add(hit.chunk_id)
            budget -= len(hit.text)
            selected.append((key, hit))
    return selected
