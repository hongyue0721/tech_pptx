# T08 独立 Review 报告｜大纲生成与教师确认

- 审查会话：干净会话，只审 diff 与相关契约，未修改任何业务代码（仅写本报告）。
- 基线 commit：`209214c`（T07 已提交状态）。审查对象 = 工作树 diff + untracked。
- 实际改动清单（以 `git status` 为准）：
  - 已跟踪改动：`errors.py`（错误码重构 + PlanNotFound/InsufficientEvidence）、`llm/adapter.py`（错误分型 + unknown-schema 归 ValidationFailed）、`jobs/worker.py`（JobCancelled 统一 + blocked 分支 + details）、`storage/job_repository.py`（_TERMINAL_STATUSES 加 blocked）、`storage/database.py`（plans 表 DDL）、`courseware_api/{main,wiring,dependencies,error_mapping}.py`（三路由接线 + 错误码映射 + plan_handler）、`tests/unit/test_llm_adapter.py`（错误码断言更新）、`process.md`、`validation-report.{md,json}`（仅时间戳）。
  - 新增：`storage/plan_repository.py`、`services/plan_service.py`、`api/routes_plans.py`、`tests/unit/test_plan_service.py`、`tests/contract/test_api_plans.py`。
  - **范围核对**：任务卡列出的 `llm/config.py`、`llm/budget.py`、`llm/__init__.py`、`jobs/__init__.py`、`.env.example`、`docs/reviews/t07-review.md` 实际**不在工作树改动内**（`.env.example` 的 `APP_LLM_*` 已随 T07 入库、无需新增；`jobs/__init__.py` 经 `from courseware_core.jobs.worker import JobCancelled` 间接指向统一后的 `errors.JobCancelled`，无需改）。以实际 diff 为审查依据，不采信清单。
- 契约依据：api.md（路由语义/错误码表/§计划→生成→应用/§通用约定 details 脱敏）、docs/01（FR-04、"缺资料的目标显示缺口；不以模型常识悄悄填平"）、docs/04（ID 服务端生成、corpus_revision 绑定）、docs/05（每页 8 片段/8000 字符、L2 来源、§4 绑定证据、§6 注入防护）、docs/06（第 2 步停在教师确认、24 次预算、重试矩阵）、docs/07（status 含 blocked、写锁、启动恢复、幂等）、docs/18（Planner.create 不自行 confirmed、confirm 校验目标/顺序/引用、缺口必须移出接受范围、模型 Schema 与存储 Schema 不混用）、AGENTS.md §3/§4/§5/§6。
- 验证命令：`backend/.venv/bin/python -m pytest tests` → **383 passed / 0 failed**（10.58s；含 T08 新增 30 条：unit 21 + contract 9；adapter 错误码重构后 38 条仍全绿）。定向 `pytest tests/unit/test_plan_service.py tests/contract/test_api_plans.py tests/unit/test_llm_adapter.py` → 68 passed。与 process.md 声明一致。
- 真实模型 plan 黄金链路：NOT_RUN（负责人预算授权项，T14），Fake provider 走同一代码路径，符合 §4「协议状态机可 mock，真实模型是独立验收项」。
- contracts/ 零改动（`git status --porcelain contracts/ api.md` 空）；三路由与 openapi.json/routes.json 逐字段核对一致（见 h）。

---

## BLOCKER

### B1｜`PLAN_NOT_FOUND` 是未申报的 api.md 错误码表偏离，违反 AGENTS §5 契约同步

- 位置：`errors.py:132`（`PlanNotFound` → code `PLAN_NOT_FOUND`）、`error_mapping.py:17`（`"PLAN_NOT_FOUND": 404`）、`tests/contract/test_api_plans.py:203`（断言 GET 未知 plan 返回 `PLAN_NOT_FOUND`）；对照 `api.md:74`。
- 问题：本轮任务背景声明「除 `MODEL_OUTPUT_INVALID`/`MODEL_UNAVAILABLE` 两码外已对齐 api.md 错误码表，两码待负责人批准补行」。但 `PLAN_NOT_FOUND` 是**第三个** api.md 错误码表未收录的码：api.md 第 74 行 404 组只列 `PROJECT_NOT_FOUND / DECK_NOT_FOUND / ARTIFACT_NOT_FOUND`，全文（含 §计划→生成→应用）无 `PLAN_NOT_FOUND`。`grep -n PLAN_NOT_FOUND api.md` 无命中。它已被实现、被契约测试断言、会被 API 消费者 `switch`，却未进规格真源。
- 依据条款：
  - AGENTS.md §5「HTTP 路由/字段/错误/版本改变：改 api.md、OpenAPI、Schema、客户端生成类型和契约测试」——错误码是对外契约，须与代码同提交同步 api.md。
  - api.md 第 3 行「本文件说明业务语义；三者和代码必须同次变更」。
  - 任务卡明确要求核实「除这两码外是否还有偏离」——结论：**有**，即 `PLAN_NOT_FOUND`。Builder 的「仅两码待批」声明不完整。
- 影响：不是运行时 bug（404 语义正确、openapi 以通用 ErrorResponse 承载 404），而是契约文档一致性缺口；若按现状提交，api.md 与代码/测试三方不一致，后续前端/CLI 依 api.md 生成错误处理会漏掉该码。
- 建议修法：在 `api.md` 第 74 行 404 组补 `PLAN_NOT_FOUND`（或并入 `*_NOT_FOUND` 家族并显式点名），与 `MODEL_OUTPUT_INVALID`/`MODEL_UNAVAILABLE` 走同一「负责人批准补行」流程；改后 `validate_pack` 复跑。属一行文档修复，但按 §5 必须先闭合再提交。

---

## NONBLOCK

### N1｜`stale` 为只读派生态、从不落库，且缺面向 T09 的「当前有效已确认计划」读取接缝

- 位置：`plan_service.py:249-254`（`_with_stale` 仅 `model_copy` 返回副本）、`plan_repository.py:83-89`（`get()` 直接返回 DB 原始 `plan_json`）、`database.py:_PLANS_DDL`（status CHECK 含 `stale` 但无任何写路径持久化 `stale`）。
- 问题：语料前进后，`get_plan` 计算返回 `stale`，但 DB `status` 列仍是 `draft`/`needs_material`/`confirmed`。`PlanRepository.get()` 不做该计算。T09 生成若图省事用 `repo.get(plan_id)` 并判 `status=="confirmed"`，会把「语料已前进、实际应 stale」的旧计划当作有效已确认计划消费——即任务卡点名的「假 draft/假 confirmed」。`confirm_plan` 本身不踩坑（它用 `plan.corpus_revision < project.corpus_revision` 的同一比较拒 stale，见 `plan_service.py:268`），但**没有任何接缝强制** T09 走服务层重算。
- 依据条款：docs/07 §3「不能将旧计划悄悄用于新语料」；docs/18「服务端状态由代码计算」；AGENTS.md「不留已知结构性债务给未来」。
- 建议修法：加一个权威读取方法（如 `PlanService.get_confirmed_for_generation(project_id, plan_id)`：加载→重算 stale→非 confirmed 抛 `PLAN_NOT_CONFIRMED`、语料前进抛 `CORPUS_CHANGED`），或在 `PlanRepository.get` 上标注「内部/原始态，消费方禁止直接判 confirmed」并把 stale 判定收敛到唯一入口。当前 T09 未实现，故列非阻塞，但须在 T09 落地前闭合。

### N2｜`handle_plan` 引用允许集合用「检索命中集合」，宽于实际进 prompt 的裁剪子集

- 位置：`plan_service.py:126-135`（`hits_by_goal`=每目标 top-12）、`plan_service.py:150-160`（`permitted` 取自全部 `hits_by_goal`）、`plan_service.py:216-236`（`_assemble_context` 裁剪出 `selected` 才写进 user 消息）。
- 问题：模型只在 prompt 里看到 `selected`（每目标≤8、全局 8000 字符子集），但 grounding 校验 `unknown = evidence_chunk_ids - permitted` 用的是「检索命中全集」。若模型输出一个「命中但未进 prompt」的 chunk_id，校验仍放行。弱化了系统提示词「只能引用给定片段的编号」与 docs/18 `EvidenceLocator`「仅接受当前允许 chunk 集合」的语义。实际风险低（模型难以凭空命中未展示的 ID），但校验基准应等于「给模型看过的集合」。
- 建议修法：`permitted = {hit.chunk_id for _, hit in selected}`（进 prompt 的集合），与 confirm 的项目语料校验分层明确（prompt 级 vs 语料级）。

### N3｜`PlanSlide.evidence_chunk_ids` 允许为空，confirm 不校验每页至少一条证据

- 位置：`contracts/models.schema.json` `PlanSlide.evidence_chunk_ids` `minItems:0`、`models/plan.py:22`（`default_factory=list`）、`plan_service.py:153-160` 与 `309-321`（空集合减任何集合恒为空→放行）。
- 问题：schema/Pydantic 双保证「slide 数≥1、accepted≥1、acknowledged 恒 true、title≤40/purpose≤240/layout 枚举」，但**证据非空无约束**。一张 `evidence_chunk_ids=[]` 的页可被 handle_plan 生成、被 confirm 接受并流入 T09。与 docs/05 §4「定义/数值/参数/API 行为必须绑定证据」、PRD「不以模型常识悄悄填平」存在张力——空证据页正是「无来源正文」的合法通道。
- 依据条款：docs/05 §3 L1（引用是否存在）/L2（来源属于项目）、§4。
- 建议修法：在 confirm（教师接受范围这一 L4 门禁）对每页断言 `evidence_chunk_ids` 非空，返回 `ValidationFailed`；或在 schema 将 `PlanSlide.evidence_chunk_ids` 提为 `minItems:1`（需评估封面/纯标题页是否豁免，若豁免则用 layout 条件约束）。属契约层设计选择，非硬 bug，故非阻塞。

### N4｜失败/取消路径不累计 `jobs.llm_calls`，费用观测口径与注释「如实累计」不符

- 位置：`plan_service.py:177-179`（`insert`→`_accumulate_llm_calls`→`return`）、`plan_service.py:190-196`；`worker.py:126-144`（cancelled/failed 分支不调 accumulate）。
- 问题：`_accumulate_llm_calls` 仅在 `insert` 成功后执行。当 provider 已发出真实请求后因 `ValidationFailed`（引用未知 chunk）、`ModelUnavailable`/`ModelTimeout`/`ModelRateLimited` 等失败，或 `JobCancelled` 取消时，`attempts` 从未写入 `jobs.llm_calls`，该列停在 0。`blocked`（全 unsupported）在 provider 调用**之前**抛出、确为 0 次，正确。故仅「已消耗模型调用但未记账」的 failed/cancelled 口径失真，与 `plan_service.py:191` 注释「如实累计」相悖。
- 影响：不影响状态机正确性与门禁，属成本可观测性缺口（docs/06 计费/预算审计口径）。
- 建议修法：把 attempts 累计与 handler 结果解耦——在 provider 返回或抛出时都记录已消耗次数（如让 `TypedCompletion`/异常携带 attempts 并在 worker finalize 前统一落库，或 handler 用 try/finally 累计）。

### N5｜confirm 对「已 confirmed 计划 + 不同 slides/新幂等键」静默返回旧计划

- 位置：`plan_service.py:275-277`（`if plan.status == "confirmed": return plan`，早于 slides/accepted 重校验）。
- 问题：HTTP 幂等层只拦「同键同请求→缓存、同键异请求→409」。教师/客户端用**新键**对已确认计划提交**不同**内容时，走到 `confirm_plan` 因 `status=="confirmed"` 直接返回旧计划，**忽略**新 `request.slides`/`accepted_goal_indices`，返回 200。语义上「确认即不可变、要改就重开 plan job」可接受，但对携带差异载荷的请求返回 200+旧内容会掩盖误用，前端可能以为改动生效。
- 建议修法：区分「同请求幂等重放」与「不同请求改已确认计划」——后者返回 409（如 `VERSION_CONFLICT`/新增语义）或显式 `ValidationFailed`，而非静默 200。

### N6｜契约/单元测试断言缺口（blocked 未断言「无 plan 行」、幂等未做 DB 计数、真实 adapter 惰性构造无测试）

- 位置：`test_api_plans.py:404-419`（blocked e2e）、`test_api_plans.py:155-170`（幂等重放）、`wiring.py:26-40`（`resolve_provider` 惰性构造真实 adapter + 缺配置→`ModelProtocolError`）。
- 问题：
  1. blocked e2e 断言了 `status=="blocked"`、`error.code=="INSUFFICIENT_EVIDENCE"`、后续 materials POST 非 409（锁释放✓），但**未断言 `plans` 表零行 / `result_ref` 为空**——「blocked 不落 plan」这一关键不变式仅靠代码走查背书。
  2. 幂等重放比对 `r1.json()==r2.json()`（同 job_id）是「不重复建 job」的合理代理，但**未做 `SELECT COUNT(*) FROM jobs`** 直接证伪「第二次是否偷偷插了 plan job」。
  3. 生产真实 adapter 路径（`build_worker_handlers(plan_provider=None)`→`resolve_provider`→`LLMConfig.from_env`）无任何测试触达；缺 `APP_LLM_*` 时的 `ModelProtocolError` 落 `failed` 也无测试。
- 依据条款：AGENTS §4「先写失败用例、断言真实、不为过关降断言」。
- 建议修法：补断言 `assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]==0`；幂等重放加 job 行计数；加一条「env 缺 APP_LLM_* → plan job failed 且 code=MODEL_PROTOCOL_ERROR」的 wiring 级测试。

### N7｜错误码重构的文档/注释漂移（`ModelConfigError` 等旧名残留）

- 位置：`llm/adapter.py:9`（模块 docstring 仍写「400/404/不支持参数：ModelConfigError」）、`docs/t07-protocol-smoke.md:15`（「adapter 分类 ModelConfigError」）、`process.md` T07 历史行（含 `ModelConfigError`/`JobDeadlineExceeded`）。
- 问题：类已重命名/合并（`ModelConfigError`→`ModelProtocolError`、`JobDeadlineExceeded`→并入 `ModelTimeout`、unknown-schema→`ValidationFailed`），但上述文档/注释未同步。`t07-protocol-smoke.md` 是已入库文件、本轮未改，属重构应连带而未连带的 §5 同步遗漏。功能无碍（运行不读 docstring），但误导后续维护者。
- 建议修法：`adapter.py` docstring 与 `t07-protocol-smoke.md` 用新码名回填；process.md T07 行可加注「（T08 已重构，见 T08 行）」保留历史同时消歧。

### N8｜`CANCELLED`→409 为死映射，与 api.md「job 终态」定性需对齐

- 位置：`error_mapping.py`（`"CANCELLED": 409`）、`errors.py:128`（`JobCancelled.code="CANCELLED"`）。
- 问题：取消经 `POST /jobs/{id}/cancel`→200 Job（queued 直接 cancelled；running 置 cancel_requested 由 worker 边界终止），异步终态经 GET Job 体现，**没有任何同步路由会抛 `JobCancelled` 到 HTTP**。故 `CANCELLED:409` 当前不可达。api.md 第 84 行把 `CANCELLED` 归「job 终态」，未赋 HTTP 码。映射本身无害（防御性），但与 api.md 定性有出入。
- 建议修法：保留亦可，但在 api.md 补一句「CANCELLED 若同步出现按 409」或在映射处注释「防御性、异步路径不触发」，避免被误读为既有 HTTP 语义。

### N9｜上下文轮转「预算不足即 return」欠填 + 测试子串歧义断言

- 位置：`plan_service.py:231-232`（`if budget - len(hit.text) < 0: return selected`）、`test_plan_service.py:265-266`（`f"chk{i}" in flat`）。
- 问题：`CHUNK_MAX_CHARS=1200 < 8000`，故首个片段总能进，**不会**清空上下文（无「全空 prompt」隐患）；但遇到第一个放不下的大片段即 `return`，而非 `continue` 尝试更小片段，利用率/后位目标公平性次优。测试侧 `"chk1" in flat` 同时命中 `chk10`/`chk11`，`included<=8` 计数偏大（本例侥幸通过）。
- 建议修法：`return`→`continue`（或按剩余预算挑可容纳片段）；测试断言用带分隔符的精确匹配（如 `f"【片段 chk{i}｜" in flat`）。

### N10｜教师材料正文原样拼入 user 消息的 prompt 注入面（登记为已知 P0 风险）

- 位置：`plan_service.py:206-214`（`【片段 …】{hit.text}` 直接拼接）。
- 问题：材料文本属低信任数据，可含「忽略上述指令/输出固定内容」等诱导语，改变模型对 grounding 的遵从。本轮未做定界/转义。按 docs/05 §6，运行期 LLM 无 shell/web/file-write 工具、动作全由类型化服务执行，爆炸半径受限；且 grounding 由服务端 coverage/引用校验兜底。故**非本轮缺陷**，按任务要求登记为 P0 风险记录，黄金链路（T14）需带变体注入样本实测。

---

## 契约一致性核对（h）

- 三路由逐字段：`POST /projects/{id}/plans`→202 `JobAccepted`、`Idempotency-Key` required（`routes_plans.py:19`、`openapi.json:657-675`、`routes.json:44-50`）；`GET .../plans/{plan_id}`→200 `LessonPlan`、无 key（`routes_plans.py:43`、`openapi.json:777-812`、`routes.json:51-57`）；`POST .../plans/{plan_id}/confirm`→200 `LessonPlan`、`Idempotency-Key` required（`routes_plans.py:52`、`openapi.json:887-921`、`routes.json:58-64`）。全部一致。
- 错误码映射 vs api.md：`MODEL_AUTH_ERROR/MODEL_PROTOCOL_ERROR`→502（api.md:80✓）、`MODEL_RATE_LIMIT/MODEL_TIMEOUT`→503（api.md:81✓）、`INSUFFICIENT_EVIDENCE`→422（api.md:79「422或job.blocked」✓）、`BUDGET_EXCEEDED`→422（api.md:82✓）；**偏离**：`MODEL_OUTPUT_INVALID`/`MODEL_UNAVAILABLE`（已申报待批）、`PLAN_NOT_FOUND`（**未申报**，见 B1）、`CANCELLED`→409（api.md 定性为 job 终态，见 N8）。`error_mapping.py:77` 兜底 `.get(code,500)`——所有新码均已显式映射，不触发 500 兜底。
- 状态机四态闭合：`draft`/`needs_material`（handle_plan 产出，`plan_service.py:169`）→`confirmed`（confirm，`:325`）；`stale` 读时派生（`:252`）。`needs_material` 与 `stale` 同时满足时 **stale 覆盖显示**（`_with_stale` 无条件在语料前进时改写）。`create_with_job` 占锁+建 job 单事务、`corpus_revision` 必须等于项目当前值否则 `CORPUS_CHANGED`（`:86`）。模型 Schema（`PlanProposal`）与存储 Schema（`LessonPlan`）分离：status/id/project_id/corpus_revision/coverage/accepted 全服务端填、模型自评 `coverage_notes` 被忽略（`test_plan_service.py:229-241` 背书），符合 docs/18 §模型输出与服务端状态。

---

## 专项独立结论

### ①「JobCancelled 双类统一」——统一正确，收口自洽

- 基线缺陷核实成立：T04 `worker.py` 曾以局部 `class JobCancelled(Exception)` 捕获，而 T07 `adapter` 抛 `errors.JobCancelled(DomainError)`——**两个同名不同类**。基线下 adapter 取消会漏过 `except JobCancelled` 落入 `except DomainError`→误判 `failed`。该缺陷此前潜伏（T07 adapter 未接入任何 job handler），T08 首次把 adapter 接进 plan handler 才暴露。
- 统一后三条路径逐一验证正确：
  1. worker 取消（`_execute` 起始 `if job.cancel_requested` 或 handler 协作式抛 `JobCancelled`）→ `except JobCancelled: finalize("cancelled")`（`worker.py:126`），job 终态 `cancelled`、释放锁、不重放。✓
  2. adapter 取消（`budget.ensure_active`→`CancelledError`→`_domain_from_internal`→`errors.JobCancelled`，`adapter.py:309-310`）。✓
  3. HTTP 映射：`JobCancelled.code="CANCELLED"`，`error_mapping` 有 `CANCELLED:409`（但异步经 GET Job 体现，409 为防御性死映射，见 N8）。✓
- `except` 顺序正确：`JobCancelled`/`InsufficientEvidence` 均为 `DomainError` 子类，置于 `except DomainError` **之前**（`worker.py:126→128→135`），无被基类抢先吞没。
- `jobs/__init__.py` 经 `from …worker import JobCancelled` 间接再导出统一类，无悬空；全仓 `grep` 无残留 `JOB_CANCELLED`/`JobDeadlineExceeded`/`ModelConfigError` 的**代码**引用（仅 docstring/文档漂移，见 N7）。
- 结论：**统一到位、语义正确、无回归**（383 全绿含 worker/adapter/jobs 既有测试）。唯一附带项是 `CANCELLED:409` 死映射的文档定性（N8），不影响正确性。

### ②「blocked 收口」——终态自洽，无错误重放、无卡锁

- `blocked` 已入 `_TERMINAL_STATUSES`（`job_repository.py:10`）且 `jobs` 表 status CHECK、`Job` Pydantic 枚举均含 `blocked`（`database.py:33`、`models/jobs.py:10`）——写库/回读/序列化全链路无 IntegrityError 风险。
- 四个交互点逐一核对：
  1. 启动恢复 `mark_interrupted_on_startup` 只动 `status='running'`（`job_repository.py:87`），`blocked` 为终态→**不被误标/不重放**。✓
  2. `claim_next` 只领 `status='queued'`（`:70`），`blocked` 永不回 `queued`→**不被错误重放**。✓
  3. 项目锁释放：`finalize` 在 `status='running'` 守卫内同事务置 `blocked` 并 `active_job_id=NULL`（`:149-166`）；handler 于 running 态抛 `InsufficientEvidence`→worker `finalize("blocked")`（`worker.py:128-134`）→**锁必释放**。契约测试 `test_api_plans.py:413-420` 实测 blocked 后 materials POST 非 409，背书释放。✓
  4. 取消接口 `request_cancel` 两段 UPDATE 均以 `status='queued'`/`'running'` 为 CAS 守卫（`:114/:126`），对 `blocked` 行 rowcount=0→原样返回，**不会把 blocked 改回或二次改态**。✓
- `blocked` 与 `failed` 严格区分：`InsufficientEvidence` 单独分支置 `blocked`+`INSUFFICIENT_EVIDENCE`，其余 `DomainError` 置 `failed`（`worker.py:128` vs `:135`），符合 api.md:59「资料不足=blocked、模型/网络错误=failed，两类不能混淆」。且 `blocked` 在 provider 调用**之前**判定（`plan_service.py:119-124`），不烧模型调用（`test_plan_service.py:214` `provider.calls==[]` 背书）。
- 残留（非阻塞）：blocked/failed 时 `plan` 不落库这一不变式**代码正确但测试未直接断言**（N6-1）；`blocked` 的 `error.details` 携带 `gap_goals`（目标 index，非材料正文），无内容泄漏（见安全核对）。
- 结论：**blocked 作为终态在恢复、领取、锁、取消四条路径全部自洽**，无重放、无卡锁、无与 failed 混淆。

---

## 安全核对（g）

- `ValidationFailed` details 仅 `unknown_chunk_ids`/`slide_id`/`outside_goal_indices`/`unknown_goal_indices`（`plan_service.py:157-160,291-320`），`InsufficientEvidence` details 仅 `gap_goals`（index）——均为 ID/下标，**不含教师材料正文**。✓
- `ModelProtocolError`（缺 `APP_LLM_*`）message 来自 `LLMConfig.from_env` 的 `ValueError`（「base_url and model are required」/「unsupported protocol」），`repr/str` 已固定 `api_key=***`（`config.py:45-54`）——**不回显 Key**。`float(env)` 失败信息仅含超时数字串，非敏感。✓
- 供应商原始响应体不入 `details`（adapter 仅记 `status`/`stage`/`attempts`/截断的 `error[:500]` 校验信息）。✓
- 符合 api.md §通用约定「details 不含 Key、任意绝对路径或原始供应商敏感响应」。

## 原子性核对（d）

- provider 成功→`insert plan`（短事务）→`_accumulate_llm_calls`（短事务）→`return`→worker `finalize succeeded`（另一连接短事务）。模型调用与落库跨连接非同一事务：若 insert 失败→异常→`failed`（模型已消耗、不落 plan，符合「失败不落 plan」，但 attempts 未记账= N4）；若 insert 提交后进程崩溃于 finalize 前→重启 `mark_interrupted` 置 interrupted+释锁，遗留一条无 result_ref 的 orphan draft plan（P0 无断点续跑，可接受）。blocked/failed/cancelled 均在 insert 前抛出→**plan 不落库一致**。✓
- 长事务规避：provider 调用不包在 `with self._conn` 内，读用 SELECT（不开写事务），符合 docs/18:55「调模型不持有长 SQLite 事务」。✓

---

## 结论

- **阻塞项 1 个**：B1 `PLAN_NOT_FOUND` 未申报的 api.md 错误码表偏离（须补 api.md 行或并入 NOT_FOUND 家族并走批准流程，与两枚待批码同标准；一行文档修复）。
- **非阻塞项 10 个**：N1 stale 派生态无 T09 权威读取接缝（结构性、T09 前须闭合）、N2 grounding 允许集合宽于 prompt 子集、N3 空证据页可被确认、N4 失败/取消不累计 llm_calls、N5 confirm 对差异载荷静默返回旧计划、N6 blocked/幂等/真实 adapter 测试断言缺口、N7 错误码重构文档漂移、N8 CANCELLED:409 死映射定性、N9 轮转欠填+测试子串歧义、N10 prompt 注入面（登记 P0 风险）。
- 状态机四态、confirm 校验链（缺口移出/目标范围/引用∈语料/stale 拒确认/幂等重放）、未确认不生成（`PLAN_NOT_CONFIRMED` 码 + 状态机，消费方在 T09）、契约三路由与 openapi/routes 逐字段一致、blocked 收口、JobCancelled 统一——核心验收**达成**；真实模型黄金链路 NOT_RUN（T14 授权项）。
- 建议：先闭合 B1（api.md 同步）再提交；N1/N3/N4 纳入 T09 开工前的必修 backlog，其余进 backlog 择机。


---

## 修复闭环记录（2026-09-19，Builder）

- **B1 已修**：api.md 错误码表补 `PLAN_NOT_FOUND`（404 组）、`MODEL_UNAVAILABLE`（503 组）、`MODEL_OUTPUT_INVALID`（502 组）三行——同提交文档同步义务（AGENTS §5），后两码 Builder 已在本轮开工声明。
- **N1 已修**：新增 `PlanService.get_current_confirmed_plan(project_id)`——T09 生成门禁的权威接缝（stale 只读计算不落库，直接读表会拿假 confirmed）；测试 `test_get_current_confirmed_plan_seam`。
- **N2 已修**：grounding 允许集合从"检索命中全集"收紧为"实际进 prompt 的裁剪子集"；测试 `test_slide_referencing_hit_but_trimmed_chunk_rejected`。
- **N3 已修**：非 title 页必须 ≥1 证据（生成与确认两路径），title 封面按 docs/18"零fact封面"豁免；测试两条。
- **N4 已修**：`llm_calls` 记账移入 finally 按 `context.budget.used`（实际HTTP请求数）累计，失败/取消路径同样记账；FakeProvider 现真实消耗预算；测试 `test_llm_calls_accumulated_on_failure`。
- **N5 已修**：confirm 对已 confirmed 计划仅认同载荷重放，异载荷 ValidationFailed 拒绝（防教师意图被静默吞掉）；测试 `test_confirm_divergent_payload_after_confirmed_rejected`。
- **N6 已修**：blocked e2e 补"plans 表零行"断言；幂等重放补"plan job 计数=1"断言。
- **N7 已修**：adapter docstring 与 t07-protocol-smoke.md 的 ModelConfigError 表述更新为新码名（保留历史注记）。
- **N8 已修**：error_mapping CANCELLED:409 加注释定性（同步路径缺省兜底，当前无同步抛出点）。
- **N9 已修**：裁剪测试改用带分隔符标记计数，消除 chk1⊂chk10 子串歧义。
- **N10 登记不修**：教材文本可含"忽略上述指令"类注入面——P0 风险登记（process.md），缓解=输出必过 Schema+引用必∈prompt 子集+教师门禁；语义层防护属 T09 核验与 T15 安全审计。
- 复验：pytest 389 全绿（36 条 T08）、validate_pack 23/23、frontend build 绿。
