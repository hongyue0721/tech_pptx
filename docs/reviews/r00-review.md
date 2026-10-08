# R00 边界收口轮 独立 Review 报告

- 审查会话：干净会话，只审 diff 与契约真源，未修改任何业务代码（仅写本报告）。
- 基线 commit：`3efdc84`（T08 已提交状态）。审查对象 = 工作树 diff + untracked，导出 `/tmp/r00_full.diff`（2675 行）。
- 实际改动清单（以 diff 为准）：
  - **A 组**：`errors.py`（+`ConsentRequired`/`PlanNotConfirmed`）、`api.md`（CONSENT_REQUIRED→409 行 + 幂等锚点恢复句）、`app-prompts/plan.md`（v1→v2）、新增 `llm/prompts.py`（版本化加载唯一事实源）、`plan_service.py`（删硬编码 `PLAN_SYSTEM_PROMPT`、consent 双检、prompt 装配重写）。
  - **B 组**：`main.py`/`wiring.py`（GC 移出 create_app）、新增 `materials/gc.py`、`jobs/worker.py`（`stop` 不谎报、GC 锁后、新增 `_publish` 发布前复核）、`job_repository.py`（+`get_execution_state`）。
  - **C 组**：`plan_service.py`（重复 slide_id 拒绝、有效/接受目标必须内容页覆盖、`confirm_cas`、`get_confirmed_plan_for_generation` 精确接缝替换 `get_current_confirmed_plan`）、`plan_repository.py`（`update`→`confirm_cas`、`create_with_job` 加 `on_committed`）。
  - **D 组**：新增 `jobs/execution_guard.py`（deadline/取消统一收口）、`idempotency_service.py`（`OperationBinder`+锚点恢复）、`idempotency_repository.py`（`bind_operation`+`operation_ref`）、`database.py`（`SCHEMA_VERSION=2`、`deadline_at`/`operation_ref` 列、v1→v2 迁移）、`job_repository.py`（`DEFAULT_DEADLINE_SECONDS=600`、`get_deadline_remaining`）、`material_service.py`/`material_repository.py`（parse 取消检查+stage 上报+deadline 落列）、`error_mapping.py`（CONSENT_REQUIRED 409）。
  - **文档/测试**：`README.md`、`process.md`、`tasks/tasks.json`（T00–T08→DONE+evidence）、`tools/validate_pack.py`（任务状态断言适配）、各测试新增/调整。
- 契约依据：api.md（§通用约定幂等句、错误码表 78、§异步任务 88）、contracts/models.schema.json（Job/JobAccepted/ErrorResponse/stage-status enum）、docs/06（任务总预算 600s、24 次上限）、docs/07 §2（幂等）§worker（单例锁/启动恢复）、docs/18（封面零 fact 豁免、服务端定状态）、AGENTS.md §3/§4/§5/§6/§8。
- 验证命令与结果：
  - `backend/.venv/bin/pytest tests -q` → **421 passed / 0 failed**（10.62s，退出码 0）。
  - `.venv/bin/python tools/validate_pack.py` → **23/23 PASS**（PACK_STATIC_ONLY）。
  - 定向核对：`get_current_confirmed_plan`/`PLAN_SYSTEM_PROMPT`/`_plans.update` 全仓无残留引用；`JobAccepted` 仅 `job_id` 字段、schema `additionalProperties:false` 不含 `deadline_at`/`operation_ref`，对外形状无内部列污染。

---

## BLOCKER

### B1｜锚点占位行被「在飞 TTL」回收，破坏本轮新写入 api.md 的「不二次落 job」承诺

- 位置：`idempotency_service.py:73-75`（`_stale` 命中即 `delete` 占位、早于恢复判定）、`idempotency_service.py:114-123`（`_stale` 对 `RESERVED_PLACEHOLDER` 一律按 `INFLIGHT_TTL_SECONDS=60` 判定，**不区分 `operation_ref` 是否已锚定**）、`idempotency_service.py:103-108`（锚点恢复仅在占位行尚未被回收时生效）；对照 `api.md:9`「同键同载荷重试返回 202 与原 `job_id`（找回，不重执行、不二次落 job）」、`idempotency_service.py:55-57` 类注释「既不 409 死等也不重执行产生第二个资源」。
- 问题：R00-D 把锚点恢复加在 `_replay_or_conflict`，但**没有同步修 `_stale`**。`execute()` 的执行顺序是「先 `_stale` 判定并 `delete`，再 `_replay_or_conflict`」。于是：
  1. 进程在 `create_with_job` 事务提交（job 行 + `operation_ref` 锚点已落库）与 `store_response` 之间崩溃 → 占位行 `response_status=RESERVED(-1)` 且 `operation_ref=job_id`；
  2. worker（另一进程）把该 queued job 跑完 `succeeded` 并释放项目锁；
  3. 客户端在 **>60s** 后同键重试 → `_stale` 见 RESERVED 且 age>60 → **删除带锚点的占位行**（锚点随之丢失）→ `try_reserve` 重新占位 → **重新执行 `produce`** → 再次 `create_with_job`：
     - 若原 job 已成功、锁已释放 → 锁 CAS 通过 → **落下第二个 plan job、生成第二份 plan**——正是锚点机制声明要杜绝的「二次落 job」；
     - 若原 job 仍排队（锁未释）→ 返回 `409 PROJECT_BUSY`——同样违背 api.md「返回 202 与原 job_id」的无条件承诺。
- 依据条款：AGENTS.md §5「HTTP 路由/字段/错误/版本改变须与代码同提交同步 api.md」——本轮把「不二次落 job」写进契约真源，实现却只在 ≤60s 窗口内兑现；AGENTS.md「修改前自检：兜底是否只覆盖一个明确场景 / 业务一致性优先于看似健壮的技术兜底」。`INFLIGHT_TTL` 的 60s 回收是 T04-N5 针对**无锚点**占位（produce 中途崩溃、业务未提交）的设计，R00-D 引入「已提交未应答」的有锚点占位后未把该类别从 60s 回收中豁免，属本轮集成遗漏。
- 影响：触发需「崩溃落在 commit→store_response 的窄间隙」+「重试晚于 60s」两个条件叠加，happy path 不受影响；但一旦命中即产生**重复业务资源/错误状态码**，且与本轮新增的对外契约句直接矛盾，后续前端/CLI 依 api.md 实现重试逻辑会踩坑。测试仅覆盖 ≤60s 即时恢复（`test_api_plans.py:1441` 崩溃恢复、`test_idempotency_service.py:1668` 跨进程恢复，created_at 均为「当下」），**>60s 有锚点回收路径零覆盖**。
- 建议修法：在 `_stale` 中把「`RESERVED` 且 `operation_ref` 非空」视为**业务已提交**（等价成品响应），按 24h `TTL_SECONDS` 过期而非 60s 在飞窗口；即 `if record.response_status == RESERVED_PLACEHOLDER: return (record.operation_ref is None and age > INFLIGHT_TTL_SECONDS) or (record.operation_ref is not None and age > TTL_SECONDS)`。同步补一条「推进 clock>60s 后同键重试仍凭锚点返回 202+原 job_id、不重执行」的回归测试（unit 用注入 clock、contract 用故障注入）。属小修，但按 §5 契约一致性必须先闭合再提交。

---

## NONBLOCK

### N1｜迟到的取消竞态会留下「已提交但无 result_ref」的孤立 draft plan

- 位置：`plan_service.py:216`（`self._plans.insert(plan)` 在 handler 末尾提交）→ `worker.py:164-182`（`_publish` 读到 `cancel_requested` 则 `finalize(cancelled)`、不写 `result_ref`）。
- 问题：取消在 `guard_active`（模型调用/入库前）能干净收口；但若取消落在 `insert(plan)` 之后、`_publish` 读状态之前的极窄窗口，则 plan 行已提交而 job 被记 `cancelled`、`result_ref` 为空 → 产生一张无 job 指向的 draft/needs_material 孤立计划。
- 影响：低危。T09 生成经 `get_confirmed_plan_for_generation` 需 `confirmed`+精确 `plan_id`+语料匹配，孤立 draft 不可达、不污染版本层；仅属数据卫生。
- 建议修法：`_publish` 取消分支或 handler 取消收口时删除本次新插入的 plan 行；或在 docs/07 明确「cancel 竞态窗口下可能残留不可达 draft plan，属可接受」。

### N2｜`set_stage` 缺 running/所有权守卫，stale worker 可改写他人或已恢复 job 的 stage

- 位置：`job_repository.py:203-214`（`UPDATE jobs SET stage=? WHERE id=?`，无 `status`/`worker_id` 守卫）；对照 `finalize`（`job_repository.py:156-168` 带 `WHERE ... AND status='running'`）与 `claim_next` 的 CAS。
- 问题：handler 内多次 `set_stage`（`plan_service.py:139/173/201`、`material_service.py:174`）不校验该行仍归本 worker、仍 running。若进程重启后 `mark_interrupted_on_startup` 已把 job 置 `interrupted`，而旧线程尚未消亡仍调 `set_stage`，会把 `interrupted` 终态行的 stage 改回 `retrieving/planning` 等，造成「终态+非终态 stage」的不自洽快照。
- 影响：低危。`_publish` 会因 `status!=running`/`worker_id` 不符而放弃 finalize，状态机不被破坏；仅 stage 观测字段可能被脏写。
- 建议修法：`set_stage` 加 `AND status='running' AND worker_id=?`（rowcount=0 静默忽略），或注释声明 stage 为尽力上报、终态后写入无害。

### N3｜`OperationBinder` 恢复码硬编码 202，与「受理型 202」隐式耦合，缺防误用约束

- 位置：`idempotency_service.py:26-28`（`_RECOVERED_ACCEPT_STATUS=202`）、`idempotency_service.py:106-108`（恢复固定返回 202）。
- 问题：`binder` 现传给**所有** `produce(binder)`（含 201 项目创建、200 confirm/cancel 路由），但恢复响应恒为 202。若未来某非 202 路由调用 `binder.bind(...)`，崩溃恢复会返回与首次受理不同码的响应，破坏「同形同码」。当前仅 `create_plan_job` 接 binder，无现实缺陷。
- 建议修法：`bind` 时一并记录/校验受理状态码（由 produce 声明），或在 `OperationBinder` 文档与断言中限定「仅 202 受理型可 bind」。

### N4｜materials 上传路由未接锚点，崩溃恢复仍走 409/重执行（已登记 backlog）

- 位置：`routes_materials.py:84`（`produce(binder)` 未调用 `binder.bind`）；`process.md` R00 行 backlog「materials 上传路由幂等锚点（仅 plans 受理接入 binder，T09 前评估）」。
- 问题：与 plans 不同，上传受理崩溃后无锚点可恢复，>60s 重试会重执行 `upload`（依赖 SHA 去重与项目锁收敛，未必产生重复 material，但无 202 找回）。本轮明确只给 plans 接锚点。
- 影响：非本轮遗漏（已在 process.md backlog 显式登记，T09 前评估）。
- 建议修法：T09 前统一给全部 202 受理型路由接 `binder.bind`，或在 api.md 标注「当前仅 plans 锚定」。

### N5｜docs/06「600 秒可配置」仅 `JobRepository` 构造参数可配，三处落点引用常量未走配置注入

- 位置：`job_repository.py:73-74`（`DEFAULT_DEADLINE_SECONDS=600`）、`material_repository.py:264-267` 与 `plan_repository.py:39-42`（直接 `JobRepository.DEFAULT_DEADLINE_SECONDS` 硬引常量）。
- 问题：docs/06:19 称「项目任务总预算 600 秒…均为可配置工程上限」。实现里 `JobRepository(conn, job_deadline_seconds=)` 可配，但 parse/plan 仓储各自直引类常量，未注入同一配置值；若将来改 env/配置，三处需各自同步，存在漂移面。
- 影响：低危（当前三处值一致、测试 `test_deadline_seconds_configurable` 仅覆盖 `JobRepository` 路径）。
- 建议修法：由依赖注入下发同一 deadline 值到 `create_with_job`/`create_with_job(material)`，消除常量直引。

### N6｜`plan_service.py` 495 行逼近 AGENTS §3 评审阈值

- 位置：`services/plan_service.py`（495 行）。
- 问题：AGENTS §3 建议 200–400 行、>500 触发评审。本轮又叠加 consent 门禁、prompt 装配、覆盖校验、CAS、生成接缝，逼近上限。
- 建议修法：T09 前若继续增长，按「受理 / worker 执行 / confirm / 门禁与校验」拆子模块或抽校验器。非本轮阻塞。

### N7｜真实模型 prompt v2 语义效果仍 NOT_RUN，仅 Fake+单测背书（登记项）

- 位置：`app-prompts/plan.md`（v2 新增「缺口目标不安排页、内容页覆盖有效目标」规则）、`process.md` 诚实声明「真实模型 T08 大纲黄金链路 NOT_RUN」。
- 问题：v2 提示词的语义遵从（模型是否真的不为缺口目标排页、是否真覆盖有效目标）由服务端 `_require_valid_goals_covered`/`_require_evidence_on_content_slide` 兜底，但**模型实际产出质量**未经真实链路验证。符合 §4「协议状态机可 mock，真实模型是独立验收项」。
- 建议修法：T14 黄金链路带缺口/注入变体样本实测。登记项，非本轮缺陷。

---

## 契约一致性核对（h）

- **CONSENT_REQUIRED→409**：补 `api.md:78` 错误表；`error_mapping.py:34-35` 映射 409；`errors.py:147-159` 定义。schema `ErrorResponse.code` 为自由串（`models.schema.json:138-142`，无 enum），无需改 schema；openapi 以通用 `ErrorResponse` 承载 409，`validate_pack` 23/23 通过。受理门禁 `plan_service.py:93` + 执行复核 `:125`，consent=false 时 `provider.calls==[]` 有单测（`test_plan_service.py:1984/1995`）与契约测（`test_api_plans.py:1483/1504`）双向背书。
- **幂等锚点恢复 202 形状**：恢复体 `{"job_id": operation_ref}` 与 `JobAccepted`（`models/jobs.py:26-27` 仅 `job_id`）一致；对外 `Job` schema `additionalProperties:false` 且不含 `deadline_at`/`operation_ref`（`models.schema.json:1498-1608`），`_row_to_job`（`job_repository.py:216-238`）显式映射忽略内部列——**内部列未污染对外形状**。唯 B1 所述恢复**码值**正确、**可达性**受 TTL 回收破坏。
- **deadline 归 MODEL_TIMEOUT**：`execution_guard.guard_active`（`execution_guard.py:43-49`）与 `adapter._translate`（`adapter.py:311-314`）映射一致（`DeadlineExceeded→ModelTimeout`、`Cancelled→JobCancelled`），两路不漂移；`ModelTimeout`/`JobCancelled` 均 DomainError，worker `except JobCancelled→cancelled`、`except DomainError→failed`（`worker.py:145-157`），deadline 耗尽落 `MODEL_TIMEOUT→job.failed`，符合 api.md:88「异步任务阶段错误经 GET Job 体现」。tz/monotonic：deadline 以 aware UTC 落库、`get_deadline_remaining` 处理 naive→utc 再换算 `time.monotonic()+remaining`（`job_repository.py:187-201`、`execution_guard.py:35-40`），时钟不回拨。
- **stage 序列三方对齐**：DB CHECK（`database.py:35-37`）、Pydantic `JobStage`（`models/jobs.py:12-23`）、schema enum（`models.schema.json:1535-1546`）均含 `queued/parsing/retrieving/planning/generating/validating/rendering/exporting/previewing/finished`；本轮新写入的 `retrieving/planning/validating`（plan）、`parsing`（parse）全部在 enum 内，`test_stage_progression_is_real`/`test_parse_reports_parsing_stage` 断言真实进度非停在 `queued`。
- **600s/24 次**：`DEFAULT_DEADLINE_SECONDS=600`（docs/06:19）、`CallBudget max_calls`（PLAN_CALL_BUDGET=4 单逻辑调用、jobs.llm_calls CHECK 0–24 对应 docs/06:31）一致。
- **封面豁免**：`_content_covered_goals` 排除 `layout=="title"`（`plan_service.py`）、`_require_evidence_on_content_slide` 豁免 title，与 docs/18:43「零 fact 封面无需语义模型 / 不冒充覆盖」一致；`test_confirm_accepts_normal_cover_plus_content_slide` 证不误伤。
- **confirm CAS 竞态**：`plan_repository.confirm_cas`（`:103-116` `WHERE id=? AND status!='confirmed'`）+ `plan_service.py:394-410` 重读裁决（同载荷=重放 200、异载荷=ValidationFailed），后写不覆盖先写；`test_concurrent_confirm_divergent_payloads_no_last_write_wins` 用 `threading.Barrier(2)`+临时 SQLite 验证「恰一方成功、落库=成功方」，非长 sleep。T08-N5「静默返回旧计划」已闭合（`:327-338` 异载荷显式拒）。
- **迁移安全**：新库 DDL 已含 `deadline_at`/`operation_ref`；老库 `init_db` 三分支（空→INSERT version=2 / `version<2`→`_migrate_v1_to_v2` PRAGMA 检查后 `ALTER ADD COLUMN`（可空、元数据操作不重写数据）+ `UPDATE version=2` / 否则 no-op）；`test_database_migration` 断言迁移后列齐、既有行原样保留、`operation_ref` 默认 NULL、version=SCHEMA_VERSION。`SCHEMA_VERSION=2` 语义清晰。
- **测试纪律（§4）**：未见删负例或放宽断言过关；`test_title_slide_without_evidence_allowed` 改为「title 封面（空引用）+ concept 内容页」，原验证点「封面无引用不被 `_require_evidence_on_content_slide` 误伤」保留，同时满足新覆盖规则，**未稀释**；e2e parse 等待窗 5s→10s（`test_api_materials.py:1372-1374`）仅放宽冷启动异步收敛窗口，`ready`/`succeeded` 断言未动，符合注释；并发/取消测试用 `Event`/`Barrier`+`wait_until` 轮询（`test_worker.py:2330+`、`test_plan_service.py:2169+`），非固定长 sleep；`FakeProvider` 新增 `context`/`on_call` 字段向后兼容，既有断言全绿；崩溃注入落在契约层（`test_api_plans.py:1441` 手工把占位退回 RESERVED 保锚点）。
- **分层/规范（§3）**：`courseware_core` 不依赖 FastAPI（`OperationBinder` 在 core，`courseware_api/idempotency.py` 单向引用）；`execution_guard` 置于 `jobs/` 被 `services/*` 与 `worker` 共享，方向单一无环；`plan_repository`/`material_repository` 引 `JobRepository` 取 deadline 常量，`JobRepository` 不回指仓储层，无循环依赖。注释普遍说明「为什么」（锁序、单调时钟、锚点原子性、CAS 裁决），符合 §3。

## 总体结论

**需修复后复审（B1 闭合后可提交）。** 本轮 A/B/C/D 四组收口方向正确、契约对齐度高、测试增量诚实（421 全绿、validate_pack 23/23、并发用同步原语、无降断言）。唯一阻塞项 **B1**：R00-D 把「不二次落 job」写进 api.md 契约，但 `_stale` 的 60s 在飞回收未豁免「已锚定」占位行，使锚点恢复只在窄时间窗内成立、超窗即重执行产生重复资源或错误状态码，属本轮引入的契约—实现不一致，且对应路径零测试覆盖。修 `_stale`（已锚定按 24h TTL）+ 补 >60s 恢复回归测试即可闭合。N1–N7 进 backlog，其中 N4/N7 为本轮已显式登记的遗留项。

---

## 闭环记录（Builder，2026-09-20）

- **B1 已修复（红→绿）**：`IdempotencyService._stale` 对"占位且 operation_ref 已锚定"豁免 60s 在飞窗口、按 24h TTL 管理（业务已提交事实不因窗口过期而消失）；新增回归 `test_anchored_placeholder_survives_inflight_window`（>60s 同键重试仍 202 找回原 job、零重执行）与 `test_anchored_placeholder_still_expires_after_24h`（24h 后按既有契约回收重执行，边界不扩大）。
- **N2 已随修（红→绿）**：`set_stage` 加 `status='running'` 守卫，stale worker 迟到上报对终态行 no-op（行不存在仍 JobNotFound）；新增 `test_set_stage_does_not_dirty_write_terminal_row`。
- **N1/N3/N5/N6/N7 进 backlog**：N1（不可达低危）、N3（bind 契约注释已述，防误用约束 T09 评估）、N5（deadline 注入配置，T09）、N6（plan_service 拆分，T09 前评估）、N7（真实模型黄金链路 T14 实测，登记 NOT_RUN）。
- 修复后全量：`pytest backend/tests` **424 passed 退出码 0**；`validate_pack.py` **23/23**；frontend build 不回归（本轮未触前端）。
