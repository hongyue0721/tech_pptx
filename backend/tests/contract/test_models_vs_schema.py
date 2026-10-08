"""契约对齐测试：Pydantic 模型与 contracts/models.schema.json 双向一致。

方向1：合法样例 → Pydantic 接受 → dump 结果被 JSON Schema 接受。
方向2：非法数据 → Pydantic 拒绝（约束不松于 Schema）。
"""

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import TypeAdapter, ValidationError

import courseware_core.models as models
from samples import SAMPLES

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"

with SCHEMA_PATH.open(encoding="utf-8") as f:
    ROOT_SCHEMA = json.load(f)

DEFS = ROOT_SCHEMA["$defs"]

ADAPTERS: dict[str, TypeAdapter] = {
    name: TypeAdapter(getattr(models, name)) for name in SAMPLES
}


def sub_schema(def_name: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{def_name}",
        "$defs": DEFS,
    }


def test_all_schema_defs_have_pydantic_model():
    missing = [name for name in DEFS if not hasattr(models, name)]
    assert missing == [], f"missing Pydantic models: {missing}"


def test_samples_cover_every_def():
    assert set(SAMPLES) == set(DEFS)


@pytest.mark.parametrize("def_name", sorted(SAMPLES))
def test_valid_sample_roundtrip(def_name: str):
    adapter = ADAPTERS[def_name]
    for sample in SAMPLES[def_name]:
        obj = adapter.validate_python(sample)
        dumped = json.loads(adapter.dump_json(obj))
        jsonschema.validate(
            dumped, sub_schema(def_name), format_checker=jsonschema.FormatChecker()
        )


@pytest.mark.parametrize("def_name", sorted(SAMPLES))
def test_extra_field_rejected_by_both(def_name: str):
    adapter = ADAPTERS[def_name]
    bad = dict(SAMPLES[def_name][0])
    bad["bogus_field"] = 1
    with pytest.raises(ValidationError):
        adapter.validate_python(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, sub_schema(def_name))


INVALID_CASES = [
    ("CourseBrief", {"topic": "", "audience": "a", "duration_minutes": 45,
                     "goals": ["g"], "target_slides": 8}),
    ("CourseBrief", {"topic": "t", "audience": "a", "duration_minutes": 5,
                     "goals": ["g"], "target_slides": 8}),
    ("CourseBrief", {"topic": "t", "audience": "a", "duration_minutes": 45,
                     "goals": [], "target_slides": 8}),
    ("CourseBrief", {"topic": "t", "audience": "a", "duration_minutes": 45,
                     "goals": ["g"], "target_slides": 20}),
    ("Health", {"status": "degraded", "service": "courseware-copilot", "version": "1"}),
    ("Material", {"id": "m", "project_id": "p", "original_name": "n.pdf",
                  "sha256": "xyz", "status": "ready", "pdf_pages": 1,
                  "usable_pages": 1, "corpus_revision": 1, "warnings": [],
                  "error_code": None}),
    ("Claim", {"id": "c", "text": "t", "kind": "derived",
               "evidence_refs": [SAMPLES["EvidenceSpan"][0]], "rationale": None}),
    ("DeckSpec", {**SAMPLES["DeckSpec"][0], "version": 0}),
    ("ErrorResponse", {"error": {"code": "X", "message": "m", "request_id": ""}}),
    ("ConfirmDeleteRequest", {"acknowledged": False}),
    ("SlideBlock", {"type": "unknown", "text": "x"}),
    ("PatchOperation", {"op": "split_slide", "target_slide_id": "s",
                        "slides": [SAMPLES["Slide"][0]]}),
    ("Job", {**SAMPLES["Job"][0], "status": "done"}),
    ("Job", {**SAMPLES["Job"][0], "llm_calls": 100}),
]


@pytest.mark.parametrize("def_name,bad", INVALID_CASES,
                         ids=[f"{n}-{i}" for i, (n, _) in enumerate(INVALID_CASES)])
def test_invalid_rejected_by_pydantic_and_schema(def_name: str, bad: dict):
    with pytest.raises(ValidationError):
        ADAPTERS[def_name].validate_python(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, sub_schema(def_name))


def test_naive_datetime_rejected_by_pydantic():
    """契约语义要求带时区UTC（schema format 无法机器强制，Pydantic 侧必须更严）。"""
    bad = dict(SAMPLES["Project"][0])
    bad["created_at"] = "2026-09-18T12:00:00"
    with pytest.raises(ValidationError):
        ADAPTERS["Project"].validate_python(bad)


def _span(i: int) -> dict:
    return {**SAMPLES["EvidenceSpan"][0], "chunk_id": f"chk_{i}"}


LONG_129 = "x" * 129
LONG_201 = "y" * 201
LONG_241 = "z" * 241
LONG_501 = "w" * 501
LONG_601 = "v" * 601

ITEMS_INVALID_CASES = [
    ("CourseBrief", {**SAMPLES["CourseBrief"][0], "goals": [LONG_241]}),
    ("CourseBrief", {**SAMPLES["CourseBrief"][0], "goals": [""]}),
    ("SlideBlock", {**SAMPLES["SlideBlock"][2], "assumptions": [LONG_201]}),
    ("SlideBlock", {**SAMPLES["SlideBlock"][2], "assumptions": [""]}),
    ("SlideBlock", {**SAMPLES["SlideBlock"][2], "evidence_refs": [_span(i) for i in range(6)]}),
    ("ObjectiveCoverage", {**SAMPLES["ObjectiveCoverage"][0], "chunk_ids": [LONG_129]}),
    ("ObjectiveCoverage", {**SAMPLES["ObjectiveCoverage"][0], "chunk_ids": [""]}),
    ("PlanSlide", {**SAMPLES["PlanSlide"][0], "evidence_chunk_ids": [LONG_129]}),
    ("PlanSlide", {**SAMPLES["PlanSlide"][0], "goal_indices": [8]}),
    ("PlanSlide", {**SAMPLES["PlanSlide"][0], "goal_indices": [-1]}),
    ("EditRequest", {**SAMPLES["EditRequest"][0], "target_slide_ids": [LONG_129]}),
    ("PatchOperation", {"op": "reorder_slides", "slide_ids": [LONG_129]}),
    ("ValidationReport", {**SAMPLES["ValidationReport"][0], "warnings": [LONG_601]}),
    ("CandidateChange", {**SAMPLES["CandidateChange"][0], "affected_slide_ids": [LONG_129]}),
    ("ContentProposal", {**SAMPLES["ContentProposal"][0], "missing_evidence": [LONG_501]}),
    ("EditProposal", {**SAMPLES["EditProposal"][0], "missing_evidence": [LONG_501]}),
    ("PlanProposal", {
        **SAMPLES["PlanProposal"][0],
        "coverage_notes": [{
            "goal_index": 0, "candidate_chunk_ids": [LONG_129], "note": "n",
        }],
    }),
    ("LessonPlan", {**SAMPLES["LessonPlan"][0], "accepted_goal_indices": [8]}),
    ("ConfirmPlanRequest", {**SAMPLES["ConfirmPlanRequest"][0], "accepted_goal_indices": [8]}),
]


@pytest.mark.parametrize("def_name,bad", ITEMS_INVALID_CASES,
                         ids=[f"{n}-{i}" for i, (n, _) in enumerate(ITEMS_INVALID_CASES)])
def test_items_constraint_violation_rejected_by_both(def_name: str, bad: dict):
    """schema 的 array items 元素级约束在 Pydantic 侧必须同样生效（review B1/B2 闭环用例）。"""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, sub_schema(def_name))
    with pytest.raises(ValidationError):
        ADAPTERS[def_name].validate_python(bad)
