# T11 全量偏移 Review 记录（2026-09-21）

- 执行模型：**huaweicloud/qwen3.8-flash**（Task 子代理干净会话，继承主会话模型，显式标注）。
- 范围：非单段 diff——frontend/src 全部 26 文件 + 后端交叉核对，对照四份契约文档（AGENT_01_FRONTEND/FRONTEND_SPEC/API_UI_MATRIX/AGENT_00）+ 仓内真源（api.md/models.schema.json/docs/09）逐条查"实现与契约偏移、文档声明与事实偏移"。
- 基线：HEAD=5475808（审查时工作树干净）。
- 结论：**1 偏移（阻塞）+ 16 偏差（非阻塞）+ 41 项确认无偏移**；历轮 Review 修复项（F2 B1-B3、F3 B1+N1-N6、F4 B1）全部未回退。

## 阻塞项与闭环

| # | 问题 | 闭环 |
|---|---|---|
| O-01 | ReviewPage load 失败路径 `err.message` 直显服务器英文（CHANGE_NOT_FOUND→"candidate change not found"），绕过 describeError 映射，违反 docs/09 §6"按错误码给动作"；同页其余路径均正确，唯此例外 | 改 `describeError(err).message`；浏览器实测无效 change →"找不到这份候选课件，请重新生成。" ✓ |

## 非阻塞偏差处置（13 当场闭环 / 2 待拍板 / 1 backlog）

- D-01 ✓ models.ts `Material.corpus_revision` 对齐 schema nullable（F2 N5 修同接口另两字段时漏项）。
- D-02/D-15 ✓ 文档计数更正：f3 截图声明 6→7 张（docs/09、process.md、tasks.json），f1 枚举"三页"→"四页"（1366 档实含 intake）。
- D-03 ✓ 队列满文案去掉不存在的"删除旧资料"指引，改"新建课题重新组织"（无单份删除接口是契约事实）。
- D-05 ✓ 新增 `composables/useEscapeClose.ts`（单一实现三处消费）：Inspector/目标抽屉/证据抽屉 Escape 关闭+焦点回触发元素；证据抽屉置顶时优先关它（层级正确）。浏览器实测三处 PASS。
- D-07 ✓ 前端补 8 个表外码兜底文案（JOB_NOT_FOUND/EXTRACTION_LIMIT_EXCEEDED/WORKER_ALREADY_RUNNING/ARTIFACT_INTEGRITY/INTERNAL_ERROR/NOT_FOUND/METHOD_NOT_ALLOWED/MALFORMED_SUCCESS），注释声明"api.md 是否补行待负责人拍板"。
- D-08 ✓ 翻页位置承载 URL `?slide=`（FRONTEND_SPEC query 含 slide）：Review/Outline 两页初始化读取+翻页 replace 写回（slide 不入 load 依赖防重读）；修 Outline load 无条件归零破坏恢复的次生 bug；浏览器实测 slide=3/5 恢复+写回 PASS。
- D-09 ✓ Material queued 状态显示"排队中"（不再夸大为"解析中"）。
- D-11 ✓ client.ts 抽 `parseResponse` 公共函数：非 JSON 响应（网关 HTML 502）不再抛 SyntaxError 穿透，按状态码构造兜底；fetchForm 复用（防平行语义）。
- D-12 ✓ 删除零消费者死代码 `composables/useProject.ts`（T03 遗留；三页各有 epoch+abort 加载）。
- D-13 ✓ 创建按钮补 disabled 原因 title（createDisabledTitle 逐项：课题/对象/目标/同意）。
- D-14 ✓ placeholder 中性化（"如：××单元复习与常见误区"），消除对演示课题的字面耦合。
- D-16 ✓ ver-line 不再本地推算"候选 v{base+1}"，改"候选稿未应用 · 基于正式版本 v{base}"（不猜服务端将分配的号）。
- **D-04 待拍板**：兼容入口 `/project/:id` 静态转 materials——API_UI_MATRIX 原文"根据 current_version 和 active_job_id 转入相应页"，docs/09 已自行收窄为"不猜 plan/change"。active_job_id 恢复链实际在 materials 页内生效；current_version 是否应驱动直落审阅页，需哥哥裁定矩阵原意。
- **D-06 待拍板**：`jobsApi.cancel`+`cancelJobKey` 已实现但零 UI 消费者（无取消按钮）。AGENT_01 F3 验收清单含"取消"。cancel 入口是否属 P0 交付范围需哥哥裁定；不做则 docs/09 应显式登记"cancel 未接 UI"。
- D-10 backlog：client 不逐路由断言 201/202（后端 status_code 固定+契约测试兜底，风险低）。

## 确认无偏移要点（41 项摘录）

- 35 错误码与 api.md 表逐码双向 diff 零缺失；"35 码"计数属实。
- types/models.ts 全 interface 字段/枚举/可空性对齐 schema（除 D-01）。
- 幂等头：后端 require 的 8 条路由前端全携带，GET 全不带。
- commit body=候选基线三要素与服务器校验严格一致；blocked 终态语义一致。
- localStorage/sessionStorage/indexedDB/v-html/mock 关键词全 src 零命中；未接路由零请求。
- 5 个 commit 哈希、截图目录、Review 记录、tasks.json 状态全部真实一致（除已修计数）。

## 修复后门禁

typecheck/build/pytest(534)/validate(23/23) 全 exit 0；回归浏览器实测：O-01 中文文案、slide 恢复与写回、三处 Escape+回焦、层级优先。
