# T03 交付物独立 Review 报告与修复闭环

日期：2026-09-18 晚；Reviewer：干净会话子代理（只审 diff 与契约，未改文件）；修复执行者：Builder 会话。
结论：**修复后可提交**（3 个阻塞问题全部闭环，非阻塞按批准处理或进 backlog）。

## 阻塞问题与修复

| # | 问题 | 契约依据 | 修复 | 验证 |
|---|---|---|---|---|
| B1 | Pydantic 系统性丢失 array items 元素级约束（15 处：11 个字符串元素长度、3 个 int 元素 0—7、1 个 maxItems=5） | models.schema.json 各 items 约束；T03 验收"类型与契约对齐" | base.py 新增 ShortId/GoalIndex/GoalText/AssumptionText/WarningMessage/MissingEvidenceNote 元素约束别名，替换 15 处 list[str]/list[int]；IllustrationBlock.evidence_refs 补 max_length=5 | 探针先证"Pydantic 接受/Schema 拒绝"→修复后 19 条新用例全绿 |
| B2 | 契约测试对 items 约束是盲区（INVALID_CASES 无一覆盖元素级） | AGENTS.md 测试纪律 | 先补 `test_items_constraint_violation_rejected_by_both` 19 条（先跑确认 19 FAILED 且失败点在 Pydantic 侧），再修 B1 转绿——严格"先失败用例后实现" | 138 passed |
| B3 | 未注册路由 404/405 返回 `{"detail":...}`，违反统一错误形状 | api.md 第11行"错误统一为 {error:{...}}" | error_mapping.py 注册 StarletteHTTPException handler（401→UNAUTHORIZED、404→NOT_FOUND、405→METHOD_NOT_ALLOWED、413→PAYLOAD_TOO_LARGE、5xx→INTERNAL_ERROR、其余→VALIDATION_ERROR） | 新增 2 条 API 用例，错误体经 jsonschema 验证 |

## 非阻塞处理

- **N1（已修）**：错误 handler 的 request_id 改为非空 fallback 生成，且全部经 `ErrorResponse/ErrorDetail` Pydantic 模型构造后 dump（不再手拼 dict 绕过校验）。
- **N2（已修）**：client.ts 路径参数 `encodeURIComponent(projectId)`。
- **N5（已修）**：useProject 增加 `unauthorized` 状态（api.md 前端规则"401 停止并提示鉴权"），WorkspacePage 对应展示。
- **N4（已修）**：.gitignore 补 `.playwright-mcp/`（Playwright 输出目录，避免以未跟踪态混入分发视角扫描）。
- **N6（已修）**：process.md 措辞与实际一致（B1 修复后"44 类型对齐"结论成立，并记录 review 轮次）。
- **N3（backlog）**：BaseHTTPMiddleware 极端异常路径下响应头可能缺 X-Request-ID、500 handler 无直接测试覆盖——T04 引入后台 worker 时一并补故障注入测试。
- **N7（backlog，需负责人决断）**：契约自身小瑕疵——`ClaimProposal.kind`、`SemanticVerdicts.checks[].status` 的 enum 缺 `"type":"string"`。改 schema 触发 OpenAPI/api.md/fixtures 同步链，P0 影响为零（Pydantic Literal 已严于 schema），留待 T15 文档同步轮统一处理。

## Reviewer 独立验证记录（只读）

- `pytest` 119 passed（修复前）；分层 grep 证实 courseware_core 无 FastAPI/HTTP 依赖；SQLite PRAGMA 真实设置；前端两路由/TS strict/无 v-html/Pinia；版本记录与 uv.lock 一致；openapi 自动导出与实现一致；`git ls-files` 分发视角含新交付物 176 文件。
- 检查点 A–I：D/E/F/G/I PASS；A/B/C/H 发现上述 B1/B2/B3/N1/N6 问题，均已闭环。

## 修复后最终回归（Builder，2026-09-18 晚）

- `backend/.venv/bin/pytest` → **140 passed**（119 原有 + 19 items 用例 + 2 路由级错误形状用例），退出码 0。
- `frontend npm run build`（vue-tsc strict + vite）→ PASS。
- `tools/validate_pack.py` → 23/23 PASS（见 validation-report.md 时间戳）。
