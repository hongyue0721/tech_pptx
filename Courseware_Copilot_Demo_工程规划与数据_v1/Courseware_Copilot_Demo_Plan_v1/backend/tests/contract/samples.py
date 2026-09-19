"""每个契约类型的合法样例，与 contracts/models.schema.json 的 $defs 一一对应。"""

HEX64 = "a" * 64

COURSE_BRIEF = {
    "topic": "STM32 中断机制",
    "audience": "大二电子信息专业学生",
    "duration_minutes": 45,
    "goals": ["理解 NVIC 优先级分组", "掌握 EXTI 配置流程"],
    "target_slides": 8,
}

EVIDENCE_SPAN = {
    "chunk_id": "chk_001",
    "document_id": "doc_001",
    "pdf_page": 3,
    "start": 10,
    "end": 42,
    "quote": "NVIC 优先级分组决定了抢占优先级与子优先级的位数分配。",
}

CLAIM = {
    "id": "clm_001",
    "text": "NVIC 优先级分组决定抢占与子优先级的位数分配。",
    "kind": "direct",
    "evidence_refs": [EVIDENCE_SPAN],
    "rationale": None,
}

DERIVED_CLAIM = {
    "id": "clm_002",
    "text": "配置 EXTI 前必须先完成 NVIC 分组。",
    "kind": "derived",
    "evidence_refs": [EVIDENCE_SPAN],
    "rationale": "两条笔记正文的先后依赖关系推出。",
}

SLIDE = {
    "id": "sld_001",
    "title": "NVIC 优先级分组",
    "layout": "concept",
    "blocks": [
        {"type": "fact", "claim_id": "clm_001"},
        {"type": "teaching", "text": "先分组，再设优先级数值。"},
        {
            "type": "illustration",
            "text": "把抢占优先级想象成打断了说话。",
            "assumptions": ["学生熟悉课堂打断场景"],
            "evidence_refs": [],
        },
    ],
}

DECK_SPEC = {
    "schema_version": "1.0.0",
    "project_id": "prj_001",
    "version": 1,
    "corpus_revision": 1,
    "course": COURSE_BRIEF,
    "claims": [CLAIM, DERIVED_CLAIM],
    "slides": [SLIDE],
}

PLAN_SLIDE = {
    "id": "pln_001",
    "title": "NVIC 分组",
    "purpose": "讲清分组与位数关系",
    "layout": "concept",
    "goal_indices": [0],
    "evidence_chunk_ids": ["chk_001"],
}

VALIDATION_REPORT = {
    "schema_valid": True,
    "relations_valid": True,
    "layout_valid": True,
    "claim_checks": [
        {
            "claim_id": "clm_001",
            "locator_status": "located",
            "semantic_status": "supported",
            "reason": "引用原文直接支持。",
        }
    ],
    "warnings": [],
    "can_commit": True,
    "model_id": "ollama/glm-5.3-flash",
    "prompt_version": "v1",
    "checked_at": "2026-09-18T12:00:00+00:00",
    "raw_result_sha256": HEX64,
    "unbound_assertions": [],
}

SAMPLES: dict[str, list[dict]] = {
    "CourseBrief": [COURSE_BRIEF],
    "CreateProjectRequest": [
        {"course": COURSE_BRIEF, "consent_to_cloud_processing": True}
    ],
    "Project": [
        {
            "id": "prj_001",
            "course": COURSE_BRIEF,
            "current_version": 0,
            "corpus_revision": 0,
            "active_job_id": None,
            "consent_to_cloud_processing": True,
            "created_at": "2026-09-18T12:00:00+00:00",
            "updated_at": "2026-09-18T12:00:00+00:00",
        }
    ],
    "ConfirmDeleteRequest": [{"acknowledged": True}],
    "ErrorResponse": [
        {
            "error": {
                "code": "PROJECT_NOT_FOUND",
                "message": "project not found",
                "request_id": "req_abc",
                "details": {},
            }
        }
    ],
    "Health": [
        {"status": "ok", "service": "courseware-copilot", "version": "0.1.0"}
    ],
    "PageWarning": [
        {"pdf_page": 2, "code": "LOW_TEXT", "message": "本页可提取文本过少"}
    ],
    "Material": [
        {
            "id": "mat_001",
            "project_id": "prj_001",
            "original_name": "notes.pdf",
            "sha256": HEX64,
            "status": "ready",
            "pdf_pages": 8,
            "usable_pages": 8,
            "corpus_revision": 1,
            "warnings": [],
            "error_code": None,
        }
    ],
    "MaterialList": [{"materials": [], "corpus_revision": 0}],
    "MaterialUploadAccepted": [
        {"material_id": "mat_001", "job_id": "job_001", "duplicate": False}
    ],
    "DocumentChunk": [
        {
            "chunk_id": "chk_001",
            "project_id": "prj_001",
            "document_id": "doc_001",
            "corpus_revision": 1,
            "document_name": "notes.pdf",
            "pdf_page": 3,
            "printed_page_label": None,
            "page_start": 0,
            "page_end": 120,
            "text": "NVIC 优先级分组决定了抢占优先级与子优先级的位数分配。",
            "text_sha256": HEX64,
            "extractor_version": "pypdf-5.9.0",
            "tokenizer_version": "jieba-v1",
        }
    ],
    "EvidenceProposal": [
        {"chunk_id": "chk_001", "quote": "NVIC 优先级分组"}
    ],
    "EvidenceSpan": [EVIDENCE_SPAN],
    "Claim": [CLAIM, DERIVED_CLAIM],
    "SlideBlock": [
        {"type": "fact", "claim_id": "clm_001"},
        {"type": "teaching", "text": "先分组再设数值。"},
        {
            "type": "illustration",
            "text": "打断的比喻。",
            "assumptions": ["课堂场景"],
            "evidence_refs": [],
        },
    ],
    "Slide": [SLIDE],
    "DeckSpec": [DECK_SPEC],
    "ObjectiveCoverage": [
        {
            "goal_index": 0,
            "status": "supported",
            "chunk_ids": ["chk_001"],
            "note": "目标0有直接证据。",
        }
    ],
    "PlanSlide": [PLAN_SLIDE],
    "PlanRequest": [{"corpus_revision": 1}],
    "LessonPlan": [
        {
            "id": "pln_001",
            "project_id": "prj_001",
            "corpus_revision": 1,
            "status": "draft",
            "coverage": [
                {
                    "goal_index": 0,
                    "status": "supported",
                    "chunk_ids": ["chk_001"],
                    "note": "",
                }
            ],
            "slides": [PLAN_SLIDE],
            "accepted_goal_indices": [],
            "created_at": "2026-09-18T12:00:00+00:00",
        }
    ],
    "ConfirmPlanRequest": [
        {
            "corpus_revision": 1,
            "slides": [PLAN_SLIDE],
            "accepted_goal_indices": [0],
            "acknowledged": True,
        }
    ],
    "GenerateRequest": [
        {"plan_id": "pln_001", "base_version": 0, "corpus_revision": 1}
    ],
    "EditRequest": [
        {
            "instruction": "把第二页精简成三点。",
            "target_slide_ids": ["sld_001"],
            "base_version": 1,
            "corpus_revision": 1,
        }
    ],
    "PatchOperation": [
        {"op": "replace_slide", "target_slide_id": "sld_001", "slide": SLIDE},
        {"op": "split_slide", "target_slide_id": "sld_001", "slides": [SLIDE, SLIDE]},
        {"op": "reorder_slides", "slide_ids": ["sld_001"]},
    ],
    "DeckPatch": [
        {
            "base_version": 1,
            "corpus_revision": 1,
            "operations": [
                {"op": "reorder_slides", "slide_ids": ["sld_001"]}
            ],
            "claims": [CLAIM],
            "summary": "重排页面。",
        }
    ],
    "ClaimVerification": [
        {
            "claim_id": "clm_001",
            "locator_status": "located",
            "semantic_status": "supported",
            "reason": "直接引用。",
        }
    ],
    "ValidationReport": [VALIDATION_REPORT],
    "CandidateChange": [
        {
            "id": "chg_001",
            "project_id": "prj_001",
            "base_version": 0,
            "corpus_revision": 1,
            "status": "ready",
            "kind": "generation",
            "affected_slide_ids": ["sld_001"],
            "summary": "首轮生成候选。",
            "candidate": DECK_SPEC,
            "validation": VALIDATION_REPORT,
            "created_at": "2026-09-18T12:00:00+00:00",
        }
    ],
    "CommitRequest": [
        {"base_version": 0, "corpus_revision": 1, "acknowledged": True}
    ],
    "RestoreRequest": [
        {
            "target_version": 1,
            "base_version": 2,
            "corpus_revision": 1,
            "acknowledged": True,
        }
    ],
    "DeckVersion": [
        {
            "project_id": "prj_001",
            "version": 1,
            "corpus_revision": 1,
            "parent_version": 0,
            "restored_from": None,
            "created_at": "2026-09-18T12:00:00+00:00",
            "content_sha256": HEX64,
        }
    ],
    "JobAccepted": [{"job_id": "job_001"}],
    "JobResultRef": [{"type": "change", "id": "chg_001"}],
    "Job": [
        {
            "id": "job_001",
            "project_id": "prj_001",
            "kind": "generate",
            "status": "running",
            "stage": "generating",
            "cancel_requested": False,
            "base_version": 0,
            "corpus_revision": 1,
            "result_ref": None,
            "error": None,
            "created_at": "2026-09-18T12:00:00+00:00",
            "updated_at": "2026-09-18T12:00:00+00:00",
            "llm_calls": 1,
        }
    ],
    "ExportRequest": [{"version": 1, "format": "pptx"}],
    "PreviewItem": [
        {
            "slide_id": "sld_001",
            "status": "ready",
            "source_type": "outline",
            "artifact_id": None,
            "warning": None,
        }
    ],
    "PreviewManifest": [
        {
            "project_id": "prj_001",
            "version": 1,
            "items": [
                {
                    "slide_id": "sld_001",
                    "status": "ready",
                    "source_type": "outline",
                    "artifact_id": None,
                    "warning": None,
                }
            ],
        }
    ],
    "ClaimProposal": [
        {
            "id": "clm_001",
            "text": "NVIC 分组决定位数分配。",
            "kind": "direct",
            "evidence_refs": [{"chunk_id": "chk_001", "quote": "NVIC 优先级分组"}],
            "rationale": None,
        }
    ],
    "ContentProposal": [
        {
            "claims": [
                {
                    "id": "clm_001",
                    "text": "NVIC 分组决定位数分配。",
                    "kind": "direct",
                    "evidence_refs": [
                        {"chunk_id": "chk_001", "quote": "NVIC 优先级分组"}
                    ],
                    "rationale": None,
                }
            ],
            "slides": [SLIDE],
            "missing_evidence": [],
        }
    ],
    "PlanProposal": [
        {
            "slides": [PLAN_SLIDE],
            "coverage_notes": [
                {
                    "goal_index": 0,
                    "candidate_chunk_ids": ["chk_001"],
                    "note": "目标0候选证据充足。",
                }
            ],
        }
    ],
    "EditProposal": [
        {
            "operations": [
                {"op": "reorder_slides", "slide_ids": ["sld_001"]}
            ],
            "claims": [],
            "summary": "重排。",
            "missing_evidence": [],
        }
    ],
    "SemanticVerdicts": [
        {
            "checks": [
                {
                    "claim_id": "clm_001",
                    "status": "supported",
                    "reason": "原文直接支持。",
                }
            ],
            "unbound_assertions": [],
        }
    ],
    "UnboundAssertion": [
        {
            "slide_id": "sld_001",
            "field_path": "blocks[1].text",
            "text": "未经授权的断言。",
            "reason": "无对应claim。",
        }
    ],
}
