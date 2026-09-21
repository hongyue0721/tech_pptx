# T11-F3 独立 Review 记录（2026-09-21）

- 执行模型：**huaweicloud/qwen3.8-flash**（Task 子代理干净会话，继承主会话模型；按红线纪律显式标注）。
- 审查方式：只读子代理，审工作区 diff（ReviewPage.vue 改动 + ValidationPanel/EvidencePanel/EvidenceDrawer/textOffset 新文件全文）+ 契约真源（AGENT_01_FRONTEND F3 节、api.md commit/evidence/deck 与错误码、models.schema.json $defs、后端 routes_changes.py/generate_service.commit_change/idempotency_service.execute/locator.py 实际行为）。
- 基线：a8106df 之上的未提交工作区改动。
- 结论：**1 阻塞 + 6 非阻塞**；A 伪成功、B 幂等、C 偏移换算、D 契约对齐、E Vue 正确性、F 未接能力诚实、G 缺失占位、H 布局逐项判定，主干诚实度 CLOSED。

## 阻塞项与闭环

| # | 问题 | 闭环 |
|---|---|---|
| B1 | `evidenceRevision` 无条件 change 优先：正式版本视图 URL 残留 change 时，证据锚回旧候选 revision——补资料提交 v4 后从旧标签切 v4 看新 chunk → `get_evidence(rev=旧)` → 404 EVIDENCE_NOT_FOUND 伪失败（正式内容报"依据找不到"）。契约要求"精确 project/revision/chunk"，锚定应随展示对象 | 改为 `currentDeck.corpus_revision`（候选视图=candidate 自身 revision 与 change 等价；正式视图=deck 自身）。浏览器回归：v1 视图"查看原文"正常高亮、无错误 ✓ |

## 非阻塞项处置

- N1（当场闭环，方案与 Reviewer 建议同向不同实现）：footerText 曾把 applyError 置于服务器态之前，并发提交 409 后 footer 与 committed/stale 真值错位。改为 **footer 只呈现服务器态**，应用失败临时提示仅在 stage 区展示；applyError 生命周期=开始下一次尝试清/路由参数变化清（409 内部 load 不误清，保留"最近一次尝试失败"事实）。
- N2（当场闭环）：discarded 状态曾归因"未通过核验"（实为主动丢弃）。changeState/applyDisabledReason 补 discarded 分支"候选已丢弃"。
- N3（当场闭环）：正式版本视图 checks Tab 曾渲染残留候选的核验报告（报告与所看版本错位）。改 `v-if="change && isCandidate"`，正式视图如实显示"正式版本没有独立核验报告"。浏览器回归 ✓。
- N4（当场闭环）：窄屏 ver-nav 与 inspector-toggle 双 `margin-left:auto` 均分空间。加 `.ver-nav + .inspector-toggle { margin-left: 8px }`。
- N5（当场闭环）：ValidationPanel 直接渲染服务器英文 status 枚举。加 STATUS_LABEL 中文映射（就绪待应用/未通过核验/已应用/已丢弃/已过期）。
- N6（**backlog**）：EvidenceDrawer chunkCache 无容量上限。P0 语料规模（≤5 资料/项目、单会话常驻）无实际风险，扩展时加 LRU；不为此引入依赖。

## Reviewer 确认 CLOSED 的检查项（要点）

- A：commit 只信 201+重读、409 重读基线不乐观改写、canApply 完全服从服务器 status+can_commit（后端 `ready⇔can_commit` 落库一致性确认）。
- B：commitKey 稳定同键重试与服务器"失败回滚占位可重执行/成功缓存可回放"语义自洽；scope `{project}|{change}` 对齐。
- C：码点切片与后端 `locator.py` Python `str.index/len` 语义严格对齐；无 indexOf 第一处误高亮；quote 不一致诚实告警路径存在（后端 quote 唯一性保证实际恒等）；epoch+abort 防旧回包。
- D：claim_checks/unbound_assertions(含 reason)/printed_page_label/三 gate/model_id/prompt_version/checked_at 逐字段与 schema 一致。
- E/F/G：props/emit 类型正确、无 export/preview/edit 请求、导出保持 disabled、缺失 claim 占位不崩溃。

## 留痕

- 本 Review 记录本身即"执行模型标注"纪律的第一份交付物（2026-09-20 哥哥抓到 F2/prompt 两次 Review 未标注的口子后固化）。
