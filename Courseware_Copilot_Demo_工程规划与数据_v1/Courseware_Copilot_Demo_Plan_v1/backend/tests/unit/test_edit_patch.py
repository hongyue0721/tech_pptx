"""T12 loop③：DeckPatch 确定性应用引擎单元测试（先红后绿）。"""

import copy
import hashlib
import json

import pytest

from courseware_core.errors import (
    CorpusChanged,
    ModelOutputInvalid,
    VersionConflict,
)
from courseware_core.models import DeckPatch, DeckSpec
from courseware_core.services.edit_patch import apply_patch

COURSE = {
    "topic": "STM32 中断机制",
    "audience": "大二学生",
    "duration_minutes": 45,
    "goals": ["理解 NVIC"],
    "target_slides": 8,
}


def fact_block(claim_id: str) -> dict:
    return {"type": "fact", "claim_id": claim_id}


def teach(text: str) -> dict:
    return {"type": "teaching", "text": text}


def slide(sid: str, text: str, claim_id: str | None = None) -> dict:
    blocks = [teach(text)]
    if claim_id:
        blocks.append(fact_block(claim_id))
    return {"id": sid, "title": f"页{sid}", "layout": "concept", "blocks": blocks}


CLAIM_C1 = {
    "id": "clm_c1",
    "text": "NVIC 分组决定抢占与子优先级位数。",
    "kind": "direct",
    "evidence_refs": [
        {"chunk_id": "chk_1", "document_id": "doc_1", "pdf_page": 1,
         "start": 0, "end": 10, "quote": "分组决定…"}
    ],
}
CLAIM_C2 = copy.deepcopy(CLAIM_C1)
CLAIM_C2.update(id="clm_c2", text="优先级分组通过 AIRCR 配置。")


def deck(**overrides) -> DeckSpec:
    payload = {
        "schema_version": "1.0.0",
        "project_id": "prj_001",
        "version": 1,
        "corpus_revision": 1,
        "course": COURSE,
        "claims": [CLAIM_C1, CLAIM_C2],
        "slides": [
            slide("s1", "一", "clm_c1"),
            slide("s2", "二", "clm_c2"),
            slide("s3", "三", "clm_c1"),  # 共享 claim：c1 同时被 s1/s3 引用
        ],
    }
    payload.update(overrides)
    return DeckSpec(**payload)


def patch(operations: list[dict], claims: list[dict] | None = None, **overrides) -> DeckPatch:
    payload = {
        "base_version": 1,
        "corpus_revision": 1,
        "operations": operations,
        "claims": claims or [],
        "summary": "测试补丁",
    }
    payload.update(overrides)
    return DeckPatch(**payload)


def slide_hash(s) -> str:
    payload = s.model_dump(mode="json") if hasattr(s, "model_dump") else s
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def new_id_factory(seq: list[str]):
    it = iter(seq)
    return lambda: next(it)


ALL = ["s1", "s2", "s3"]


class TestReorder:
    def test_reorder_permutation_reorders_only(self):
        result = apply_patch(
            deck(), patch([{"op": "reorder_slides", "slide_ids": ["s3", "s1", "s2"]}]),
            authorized_slide_ids=ALL,
        )
        assert [s.id for s in result.slides] == ["s3", "s1", "s2"]
        assert [slide_hash(s) for s in result.slides if s.id == "s1"] == [
            slide_hash(deck().slides[0])
        ]
        assert [c.id for c in result.claims] == ["clm_c1", "clm_c2"]

    def test_reorder_must_be_full_permutation(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(), patch([{"op": "reorder_slides", "slide_ids": ["s3", "s1"]}]),
                authorized_slide_ids=ALL,
            )

    def test_reorder_unknown_id_rejected(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch([{"op": "reorder_slides", "slide_ids": ["s3", "s1", "s9"]}]),
                authorized_slide_ids=ALL,
            )

    def test_reorder_duplicate_id_rejected(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch([{"op": "reorder_slides", "slide_ids": ["s1", "s1", "s2"]}]),
                authorized_slide_ids=ALL,
            )


class TestReplace:
    def test_replace_only_touches_target(self):
        before = {s.id: slide_hash(s) for s in deck().slides}
        result = apply_patch(
            deck(),
            patch(
                [
                    {
                        "op": "replace_slide",
                        "target_slide_id": "s2",
                        "slide": slide("s2", "二改", "clm_c2"),
                    }
                ]
            ),
            authorized_slide_ids=["s2"],
        )
        after = {s.id: slide_hash(s) for s in result.slides}
        assert after["s1"] == before["s1"] and after["s3"] == before["s3"]
        assert after["s2"] != before["s2"]
        assert [s.id for s in result.slides] == ALL

    def test_replace_slide_id_must_match_target(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch(
                    [
                        {
                            "op": "replace_slide",
                            "target_slide_id": "s2",
                            "slide": slide("s1", "偷换", "clm_c1"),
                        }
                    ]
                ),
                authorized_slide_ids=["s2"],
            )

    def test_replace_unauthorized_target_rejected(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch(
                    [
                        {
                            "op": "replace_slide",
                            "target_slide_id": "s1",
                            "slide": slide("s1", "偷改", "clm_c1"),
                        }
                    ]
                ),
                authorized_slide_ids=["s2"],
            )


class TestSplit:
    def test_split_replaces_target_in_place_with_server_ids(self):
        result = apply_patch(
            deck(),
            patch(
                [
                    {
                        "op": "split_slide",
                        "target_slide_id": "s2",
                        "slides": [
                            slide("model_a", "二上", "clm_c2"),
                            slide("model_b", "二下", "clm_c2"),
                        ],
                    }
                ]
            ),
            authorized_slide_ids=["s2"],
            new_id_factory=new_id_factory(["sld_new1"]),
        )
        ids = [s.id for s in result.slides]
        assert ids == ["s1", "s2", "sld_new1", "s3"]
        before = {s.id: slide_hash(s) for s in deck().slides}
        after = {s.id: slide_hash(s) for s in result.slides}
        assert after["s1"] == before["s1"] and after["s3"] == before["s3"]

    def test_split_unauthorized_target_rejected(self):
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch(
                    [
                        {
                            "op": "split_slide",
                            "target_slide_id": "s1",
                            "slides": [
                                slide("a", "上", "clm_c1"),
                                slide("b", "下", "clm_c1"),
                            ],
                        }
                    ]
                ),
                authorized_slide_ids=["s2"],
                new_id_factory=lambda: "sld_x",
            )


class TestClaims:
    def test_new_claim_added_and_reference_valid(self):
        new_claim = copy.deepcopy(CLAIM_C1)
        new_claim.update(id="clm_c9", text="新增结论。")
        result = apply_patch(
            deck(),
            patch(
                [
                    {
                        "op": "replace_slide",
                        "target_slide_id": "s2",
                        "slide": slide("s2", "二改", "clm_c9"),
                    }
                ],
                claims=[new_claim],
            ),
            authorized_slide_ids=["s2"],
        )
        assert "clm_c9" in [c.id for c in result.claims]
        assert "clm_c2" in [c.id for c in result.claims]  # 集合保留，不静默删

    def test_shared_claim_rewritten_under_same_id_rejected(self):
        rewritten = copy.deepcopy(CLAIM_C1)
        rewritten.update(text="被改写的共享结论。")
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                deck(),
                patch(
                    [
                        {
                            "op": "replace_slide",
                            "target_slide_id": "s2",
                            "slide": slide("s2", "二改", "clm_c1"),
                        }
                    ],
                    claims=[rewritten],
                ),
                authorized_slide_ids=["s2"],
            )

    def test_identical_claim_carryover_allowed(self):
        result = apply_patch(
            deck(),
            patch(
                [
                    {
                        "op": "replace_slide",
                        "target_slide_id": "s2",
                        "slide": slide("s2", "二改", "clm_c2"),
                    }
                ],
                claims=[CLAIM_C2],
            ),
            authorized_slide_ids=["s2"],
        )
        assert [c.id for c in result.claims] == ["clm_c1", "clm_c2"]


class TestGuardsAndSequencing:
    def test_base_version_mismatch_rejected(self):
        with pytest.raises(VersionConflict):
            apply_patch(
                deck(version=2),
                patch([{"op": "reorder_slides", "slide_ids": ["s3", "s2", "s1"]}]),
                authorized_slide_ids=ALL,
            )

    def test_corpus_mismatch_rejected(self):
        with pytest.raises(CorpusChanged):
            apply_patch(
                deck(corpus_revision=2),
                patch([{"op": "reorder_slides", "slide_ids": ["s3", "s2", "s1"]}]),
                authorized_slide_ids=ALL,
            )

    def test_operations_apply_sequentially(self):
        result = apply_patch(
            deck(),
            patch(
                [
                    {
                        "op": "replace_slide",
                        "target_slide_id": "s2",
                        "slide": slide("s2", "二改", "clm_c2"),
                    },
                    {"op": "reorder_slides", "slide_ids": ["s2", "s3", "s1"]},
                ]
            ),
            authorized_slide_ids=["s2"],
        )
        assert [s.id for s in result.slides] == ["s2", "s3", "s1"]
        replaced = next(s for s in result.slides if s.id == "s2")
        assert replaced.blocks[0].text == "二改"

    def test_result_version_is_next_candidate_number(self):
        result = apply_patch(
            deck(),
            patch([{"op": "reorder_slides", "slide_ids": ["s3", "s1", "s2"]}]),
            authorized_slide_ids=ALL,
        )
        assert result.version == 2
        assert result.project_id == "prj_001"

    def test_split_exceeding_deckspec_bounds_maps_to_model_output_invalid(self):
        # N-7：结构溢出（split 使页数超 DeckSpec 上限 16）必须以 typed
        # MODEL_OUTPUT_INVALID 收口，不得以 ValidationError 冒泡成 INTERNAL_ERROR。
        slides = [slide(f"s{i}", f"内容{i}") for i in range(1, 17)]
        full = deck(slides=slides)
        with pytest.raises(ModelOutputInvalid):
            apply_patch(
                full,
                patch(
                    [
                        {
                            "op": "split_slide",
                            "target_slide_id": "s1",
                            "slides": [
                                slide("a", "上"),
                                slide("b", "下"),
                            ],
                        }
                    ]
                ),
                authorized_slide_ids=["s1"],
                new_id_factory=lambda: "sld_x",
            )
