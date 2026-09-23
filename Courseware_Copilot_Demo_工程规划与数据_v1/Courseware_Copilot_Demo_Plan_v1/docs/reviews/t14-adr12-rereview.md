# T14 ADR-12 轻量复审（partial 核准通道一致性）

执行模型 id: tierflow/Qwen3.8-Flash

复审类型：读文件核对 + 定向测试，不改代码。
PACK=Courseware_Copilot_Demo_工程规划与数据_v1/Courseware_Copilot_Demo_Plan_v1

## 逐项核对

### 1. 前端派生与后端权威推导同口径 — PASS

文件：`frontend/src/utils/approvalChannel.ts`（注：实际位于 PACK 下，任务描述省略了 PACK 前缀）。
后端：`backend/src/courseware_core/services/claim_verdicts.py:88` `partial_approval_channel`。

五条规则逐条比对，完全一致：

| 规则 | 后端 (claim_verdicts.py) | 前端 (approvalChannel.ts) |
| --- | --- | --- |
| warnings / unbound 非空即拒 | :96 `if report.warnings or report.unbound_assertions` | :7 `v.warnings.length > 0 \|\| v.unbound_assertions.length > 0` |
| schema/layout 不过即拒 | :98 `not report.schema_valid or not report.layout_valid` | :8 `!v.schema_valid \|\| !v.layout_valid` |
| checks 非空且无重复 | :101 `not ids or len(ids) != len(set(ids))` | :10 `ids.length === 0 \|\| new Set(ids).size !== ids.length` |
| partial 非空 | :105 `if not partials` | :14 `partials.length === 0` |
| 全 supported/partial | :107 `not in ("supported","partial")` | :17 `!== "supported" && !== "partial"` |
| 返回 partial 清单 | :110 `return partials` | :22 `return partials` |

前端注释（:4-5）亦声明"服务器 commit 时以权威推导复核，本函数不是放行依据"，与后端 docstring（:89）口径一致，无越权放行风险。

### 2. approved_partial_claim_ids 上限 96 三处一致 — PASS

- `backend/src/courseware_core/models/changes.py:47` `max_length=96`
- `contracts/models.schema.json:1382` `maxItems: 96`（字段块 :1375）
- `contracts/openapi.json:3792` `maxItems: 96`（字段块 :3785）

三处数值一致；changes.py:44-45 注释说明对齐 claim_checks 的 96、规避教师全勾仍 422 死锁（Review N1）。

### 3. 重复核准拒绝四处一致 — PASS

- `backend/src/courseware_core/models/changes.py:49-53` `model_validator` `_approved_ids_unique` 抛 `"approved_partial_claim_ids must be unique"`
- `contracts/models.schema.json:1383` `uniqueItems: true`
- `contracts/openapi.json:3793` `uniqueItems: true`
- `api.md:51` "清单内重复id返回422（与confirm集合语义同先例）"
- `backend/tests/unit/test_generate_service.py:647` `test_duplicate_approved_ids_rejected`（`pytest.raises(ValidationError, match="unique")`）

四处口径一致，模型层/Schema/OpenAPI/文档/测试闭环。

### 4. 定向测试 — PASS

命令：
```
cd PACK/backend && PYTHONPATH=src .venv/bin/python -m pytest \
  tests/unit/test_generate_service.py::TestPartialApprovalCommit \
  tests/contract/test_models_vs_schema.py -q --tb=line -p no:warnings
```

结果：退出码 0，145 passed（TestPartialApprovalCommit 含重复拒绝、全量核准放行、漏核准 409、夹带非 partial 拒绝等；契约测试覆盖 models vs schema 一致性）。

## 结论

放行提交。

第1-4项全部 PASS。前端派生与后端权威推导五条规则同口径、上限 96 三处一致、重复拒绝四处闭环、定向测试退出码 0 全通过。ADR-12 partial 核准通道修复已落地，无阻塞项。
