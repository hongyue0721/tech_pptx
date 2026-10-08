# T09 候选生成·语义核验·教师提交 独立 Review 报告

- 审查会话：干净会话，只审 diff 与契约真源，未修改任何业务代码（仅写本报告）。
- 基线 commit：`069083b`（R00 闭环已提交状态）。审查对象 = 工作树 diff + untracked，导出 `/tmp/t09_full.diff`（2757 行）。
- 实际改动清单（以 diff 为准）：
  - **循环①**：`database.py`（`SCHEMA_VERSION=4`、`changes` 表 DDL 五态/两态 CHECK、列级迁移入口 `_migrate_columns`）、新增 `storage/change_repository.py`（`create_generate_job` 占锁+建 job+锚点同事务、`create`/`get`/`mark_committed`）、新增 `api/routes_changes.py`（GET change）、`errors.py`（`ChangeNotFound`/`ChangeNotCommittable`）、`error_mapping.py`（404/409 两行）、`api.md`（CHANGE_NOT_FOUND 并入 404 组、CHANGE_NOT_COMMITTABLE 并入 409 组）。
  - **循环②**：`database.py`（`jobs.params_json` 内部列）、`job_repository.py`（`get_params`/`accumulate_llm_calls`）、新增 `retrieval/context.py`（轮转预算装配唯一实现）、`plan_service.py`（`_assemble_context` 改调共享装配、`_accumulate_llm_calls` 下沉 repo）、新增 `services/generate_service.py`（511 行：`create_generate_job` 受理门禁、`handle_generate`/`_generate` 批生成+locator+修复+核验+门、`_locate_batch`、`_verify_batch`、`get_change`/`_with_stale`）、`wiring.py`（`generate_handler` + `cached_model_id`）、`dependencies.py`（`get_generate_service`）、`main.py`（挂 changes_router）。
  - **循环③**：`generate_service.commit_change`（stale 根因分流、blocked/committed 拒绝、base/corpus 匹配、`on_committed` 内联 `_mark`）、`version_repository.commit_version`（+`on_committed` 回调，同事务）、`routes_changes.py`（POST commit 201）、`api.md` 错误码行。
  - **文档/测试**：`process.md`（T09 三循环声明）、`samples.py`（+`CANDIDATE_CHANGE`）、`validation-report.*`；新增 `test_change_repository.py`(6)、`test_generate_service.py`(28)、`test_api_changes.py`(3)、`test_api_generate.py`(13)。
- 契约依据：api.md（路由 26/31/32、错误码表 74/78、幂等节 9）、contracts/models.schema.json（CandidateChange/ValidationReport/ClaimVerification/SemanticVerdicts/CommitRequest/DeckVersion/Job enum 与上限）、docs/18（Generator.propose/Verifier.check/VersionRepository.commit 契约、55 短事务）、docs/04（§候选与应用、25「核验A展示B」、41 可执行门）、docs/06（25-31 流程、24 请求预算）、docs/05（§8「不漏项/不重复/不未知ID」、L3 零fact豁免）、AGENTS.md §3/§4/§5/§8。
- 验证命令与结果：
  - `backend/.venv/bin/pytest backend/tests -q` → **474 passed / 0 failed**（22.93s，退出码 0）。
  - `.venv/bin/python tools/validate_pack.py` → **23/23 PASS**（PACK_STATIC_ONLY）。
  - 定向核对：`_row_to_job`（`job_repository.py:242-262`）显式列字段，**不含** `params_json`/`deadline_at`/`operation_ref`/`worker_id`/`request_id`——内部列未污染对外 Job；`on_committed`（`version_repository.py:87-88`）在 `with self._conn` 块内、INSERT 之后提交之前，回调抛异常整体回滚——「版本前进⇔候选committed」真同事务；`CommitRequest.acknowledged: Literal[True]`（`models/changes.py:41`）+ schema `const:true` 双向强制；`handle_generate` 全程不写 `projects.current_version`——生成与应用分离成立。

---

## BLOCKER

### B1｜一次修复路径下，落库 slides / 核验输入仍用「修复前」的 proposal，与「修复后」的 located claims 错配

- 位置：`services/generate_service.py:205`（`located, failures = self._locate_batch(...)`，`_locate_batch` 仅 `return located, failures`，见 `:328`）、`:338`（修复分支内 `proposal = provider.complete_json(...)` 重新赋值，但这是 `_locate_batch` 的**局部变量**，不回传调用方）、`:215-216`（`self._verify_batch(job, located, proposal.slides, ...)`）、`:241`（`slides.extend(proposal.slides)`）、`:242`（`warnings.extend(proposal.missing_evidence)`）——三处 `proposal` 均为 `_generate` 作用域里**修复前**的原始对象，而 `located` 来自修复后 proposal 的 claims。
- 问题：`_locate_batch` 在 attempt=1 时把 `proposal` 换成模型修复响应，并基于它产出 `located`（修复后 claims）；但 `_generate` 拿不到这个最终 proposal，于是：① 语义核验 `_verify_batch`→`_verify_messages` 的「页面可见文字」分区（title/teaching/illustration）取**修复前** slides，而待核验 claims 取**修复后** located——当模型修复时改动了标题/教学文字（哪怕只是补全引用连带重写页面文字），L3/§8 的 unbound_assertions 检测就基于陈旧页面文字，**漏检新页面里偷塞的未绑定专业断言**；② 落库 `CandidateChange.candidate.slides` 用修复前页、`claims` 用修复后 claim，正是 docs/04:25 明令禁止的「核验了 A、页面展示 B」结构。happy path（无修复，attempt=0 直接 `:328` 返回）两值一致，故不暴露。
- 依据条款：docs/18:39「Generator.propose……不在格式修复时变更教师范围」、docs/05 §8「语义核验输入还必须包含页面标题、teaching/illustration 可见文字」、docs/04:25。AGENTS「修改前自检：是否可能创建出『看起来成功但关系不一致』的数据」——本条恰好制造「claims 已修、slides 未修」的关系不一致候选。
- 影响：B 级。触发条件为「某批 locator 失败→一次修复成功」，即 `test_fake_quote_repaired_once_then_ready` 覆盖的真实路径；该测试用 `bad`/`good` 两个 proposal 的 **slides 完全相同**（仅 quote 不同），结构上掩盖了错配，使缺陷在测试里不可见。一旦真实模型修复响应调整页面文字，候选会以「页/claim 错配」状态被判 ready 并可提交，破坏可信链。
- 建议修法：`_locate_batch` 返回 `(located, failures, final_proposal)`，`_generate` 统一用 `final_proposal.slides`/`final_proposal.missing_evidence` 做核验输入与落库；并补一条「修复响应改动 slides（如新增 teaching 未绑定断言）」的回归测试，断言核验输入与落库页均来自修复后 proposal（当前 bad/good slides 同构的夹具需改为 slides 可区分，否则继续掩盖）。

### B2｜语义核验「重复 claim_id」被静默去重采信首个 verdict，注释谎报记为 not_checked，可致假绿

- 位置：`services/generate_service.py:355-360`（`for c in verdicts.checks: if c.claim_id in checks_map: continue; checks_map[c.claim_id]=c`），对照其上方注释「重复答复视同不可信，保留首个并把该 claim 记为缺失（not_checked 走门）」——代码只 `continue` 跳过后续重复项、**保留首个**，并未把该 claim 记为缺失。
- 问题：docs/05 §8 与 app-prompts/verify.md 均要求「每个指定 claim_id 必须恰好返回一次，不遗漏、不重复、不造新 ID」「每条已使用 claim 必须恰好有一条核验结果，不接受模型漏项、重复项或未知 ID」。当前实现：模型对同一 claim 返回两条（如首条 `supported`、次条 `unsupported`/`conflict`），系统采信**首条 supported** 并据此计入 `claim_checks`，`full_coverage` 与「全 supported」门都判过 → `can_commit=True`。这把「模型不守 Schema（重复项）」直接降级成「可提交」，与本轮反复强调的「可提交标志完全由服务器计算、不采用模型自报、模型 verdict 不得掩盖问题」相悖。漏答路径有 `test_missing_verdict_not_greenwashed` 背书，**重复项路径零测试覆盖**（`test_duplicate_claim_ids_across_batches_block` 测的是跨批 claim id 冲突走 `relations_valid`，非同一批 verdict 列表内重复）。
- 依据条款：docs/05 §8、app-prompts/verify.md、docs/18:43「Verifier……模型只返回 SemanticVerdicts，引用核验不存在时不得把 model verdict 当定位成功」的对称要求（重复项同样不得被采信）。
- 影响：B 级。属可信链核心降级——虽需模型返回重复项才触发，但「不依赖模型守规矩」正是本门禁的存在理由；一旦命中即对未经（一致）支持的内容盖绿并可提交。
- 建议修法：检测到 `claim_id` 重复时，将该 claim 显式标记为「不可信」——例如维护 `dup_ids`，在 `:225-237` 组装 `claim_checks` 时对 `dup_ids` 内的 claim 记 `semantic_status="not_checked"`（reason 注明 duplicate verdict），使其自然走不过门；并补「同批 verdict 重复 claim_id → blocked/not_checked」回归测试（夹具 `verdicts` 需支持构造重复项）。

---

## NONBLOCK

### N1｜`samples.py` SAMPLES 字典 `CandidateChange` 键重复，新增 `CANDIDATE_CHANGE` 常量被旧内联样本覆盖，未进双向契约

- 位置：`backend/tests/contract/samples.py:267-268`——`"CandidateChange": [CANDIDATE_CHANGE],` 之后紧跟原有 `"CandidateChange": [ {...内联...} ]`。Python dict 字面量重复键，后者覆盖前者。
- 问题：本轮意图「新增 CandidateChange 进双向契约」（diff 概要明确），但新常量实际未进入 `SAMPLES`，成为死代码；双向契约测试仍跑旧内联样本（内容近似，覆盖未减，故 `validate_pack` 仍 23/23）。属编辑笔误（漏删旧块或漏改常量），且会误导后续 reviewer 以为新样本生效。
- 建议修法：删除旧内联块、保留 `[CANDIDATE_CHANGE]`（或反之，二选一），让常量真正生效；可加一条「SAMPLES 键唯一性」轻量断言防回归。

### N2｜`layout_valid` 仅比较页数相等，未校验生成 slide_id 集合 == 教师确认计划 slide_id 集合

- 位置：`services/generate_service.py:245-247`（`layout_valid = len(slides) == len(plan.slides) and all(len(s.blocks) >= 1 ...)`）。
- 问题：prompt 要求「slides 必须逐页覆盖这些 id，不得增删页」，但服务端只比 `len`。模型若产同数量但 id 漂移/重命名的页（且 id 唯一、fact 引用合法 claim），`_relations_valid`（`:267` 区）与 `layout_valid` 均过，候选可判 ready——实质偷换了教师确认的页范围（docs/18:39「不在格式修复时变更教师范围」的同类约束在生成主路径未守）。
- 影响：非阻塞。committed 版本页 id 漂移主要影响后续 edit 按 slide_id 引用与版面对齐，不直接制造假引用；但属范围一致性缺口。
- 建议修法：`layout_valid`（或单列 `range_valid`）追加 `{s.id for s in slides} == {s.id for s in plan.slides}` 判定，漂移即 blocked。

### N3｜跨批累加后 `DeckSpec` 构造先于落库，模型越界产过多页/claims 抛未类型化 `ValidationError` → job failed(INTERNAL_ERROR)，本应 blocked

- 位置：`services/generate_service.py:259`（`deck = DeckSpec(...)`，无 try 包裹），schema `DeckSpec.slides maxItems:16`、`claims maxItems:96`；worker `except Exception → INTERNAL_ERROR failed`（`jobs/worker.py:158-163`）。
- 问题：单批 `ContentProposal` 受 schema 约束（slides≤16、claims≤96），但跨批累加只在最终 `DeckSpec(...)` 才校验。计划≤12 页（`LessonPlan/ConfirmPlanRequest slides maxItems:12`）下现实难越界，但模型若单批违规产 >3 页或多塞未引用 claims，累加可越 16/96 → 构造抛 `pydantic.ValidationError`（非 DomainError），落 worker 兜底 `INTERNAL_ERROR failed`，教师拿不到「blocked 候选+报告」而是 job 失败。可信链未破（不会假绿），属类型化/体验缺口。
- 建议修法：累加后、构造 `DeckSpec` 前做页数/claims 上限守门，越界则截断到计划范围并置 `layout_valid=False`/`relations_valid=False` 走 blocked；或将 `DeckSpec` 构造包 try 转 `ValidationFailed`/blocked 候选。

### N4｜`commit_change` 内联 `_mark` SQL 与 `ChangeRepository.mark_committed` 平行实现（后者仅测试使用）

- 位置：`services/generate_service.py:453-462`（内联 `UPDATE changes SET status='committed', json_set(...)`）与 `storage/change_repository.py:105-118`（`mark_committed` 同语义 SQL）；grep 确认 `mark_committed` 仅被 `test_change_repository.py` 调用，生产路径未用。
- 问题：同一条「ready→committed + 列/JSON 双源同步」逻辑两份实现，违反 AGENTS「复用现有」与「不复制平行语义」；后续若 CAS 条件/列名变更需两处同步，存在漂移面。`_mark` 因需「rowcount==0 即抛 VersionConflict」（而非返回 False）未直接复用，属可调和差异。
- 建议修法：`mark_committed` 增加 `raise_on_noop: bool` 或在 service 内调用 `mark_committed` 后据返回值抛 `VersionConflict`，消除双 SQL；或删 `_mark` 改走 `ChangeRepository` 注入（commit 时 service 已持 `self._changes`）。

### N5｜`_locate_batch` 修复分支重复 `load_system_prompt("content")`

- 位置：`services/generate_service.py:337` 区（修复时再次 `load_system_prompt("content", ...)`），而 `_generate` 开头 `:174` 已加载 `content_ver/content_body`。
- 问题：同版本重复读盘装配，无功能错误但属冗余 IO 与「版本可能两次读不一致」的微小隐患。
- 建议修法：复用 `_generate` 已加载的 `content_body/content_ver`（传入 `_locate_batch`）。

### N6｜`generate_service.py` 511 行超 AGENTS §3 建议区间、且 `handle_generate`/`_generate` 职责偏重

- 位置：`services/generate_service.py`（511 行）。
- 问题：§3 建议 200–400 行、>500 触发评审。本文件聚合受理门禁、批生成、locator+修复、核验、门、读 stale、commit、prompt 装配八类职责，已达阈值（且叠加 B1/B2 修复会更长）。
- 建议修法：按「受理 / worker 生成流水线 / 门与结构校验 / 读取与提交」拆子模块或抽 `Verifier`/`Gate` 协作者（docs/18 本就区分 Generator/Verifier）。非本轮阻塞，但 B1/B2 落修时一并整理更划算。

---

## 契约一致性核对（h）

- **错误码同提交**：`api.md:74` 404 组并入 `CHANGE_NOT_FOUND`、`:78` 409 组并入 `CHANGE_NOT_COMMITTABLE`（含「候选 blocked/已提交/核验未全过，不得应用」释义），与 `errors.py:169-183`、`error_mapping.py:18/35`（404/409）同 diff 落地 ✓；schema `ErrorResponse.code` 自由串无需改 enum；`validate_pack` 23/23 通过（openapi 以通用 ErrorResponse 承载，路径 `/generations`、`/changes/{id}`、`/changes/{id}/commit` 已在 `openapi.json:1017/1576/1686`）。
- **对外形状对齐 schema**：`CandidateChange`（status 五态 enum、`additionalProperties:false`）↔ `changes` 表 CHECK 五态一致；`DeckVersion` 由 `commit_version` 服务端分配 version（候选拟议 `base+1` 仅作占位、`version_repository.py:70` 以 CAS 重算覆盖，对齐 docs/18:45）；`ValidationReport.can_commit` 纯服务端计算（`generate_service.py:232-238`），不取模型自报 ✓；`model_id=None`/`raw_result_sha256=None` 与 schema `anyOf null` 一致、不写假值 ✓；`prompt_version=f"{content_ver}+{verify_ver}"` 落 `minLength1/maxLength80` ✓。
- **内部列不污染对外 Job**：`jobs.params_json`（v4）、`deadline_at`/`operation_ref`（v2）均经 `_row_to_job` 显式字段映射排除；`Job` schema `additionalProperties:false` 不含三者；受理 INSERT（`change_repository.py:921-938`）写 params_json，执行侧 `get_params` 按 job 精确取参、不猜 ✓。
- **stage 序列在 enum 内**：generate 用 `retrieving`/`generating`/`validating`（`generate_service.py:172/186/347` 区），三者均在 DB CHECK（`database.py:35-37`）、Pydantic `JobStage`、schema enum 三处一致；`test_stage_progression_and_verify_after_content` 断言 content 调用时 stage=generating、verify 时=validating，非停在 queued ✓。
- **可信链（除 B1/B2 外）**：假引用→`_locate_batch` 产 `failures`→`:208-213` 记 `locator_status=invalid/semantic=not_checked`→不进 `_verify_batch` 模型队列（`:215` 仅传 located，`test_fake_quote_survives_repair_blocks_candidate` 断言 `verify_claims` 0 次）→门不过→blocked ✓；漏答→`:225-231` not_checked→blocked ✓；unbound→`:238 not unbound` 阻断 can_commit ✓；零 fact 批 `_verify_batch` 返 None 不调模型（docs/18:43）✓；`can_commit=false` 在 `commit_change:435` 与路由双重拒（`ChangeNotCommittable`），`test_blocked_candidate_409`/`test_blocked_candidate_cannot_commit` 双向背书 ✓；教师 `acknowledged` 强制 `Literal[True]`，false→422（`test_unacknowledged_422`）✓。
- **并发与事务**：`commit_change` 把候选状态迁移作为 `on_committed` 注入 `commit_version` 的 `with self._conn`（指针 CAS→INSERT deck_versions→`_mark` 同事务，回调抛 `VersionConflict` 整体回滚）——「版本前进⇔候选 committed」原子成立，无「版本已前进但候选仍 ready」中间态；并发双 commit 输家在指针 CAS `WHERE current_version=expected_base`（`version_repository.py:52-59`）或 `_mark WHERE status='ready'`（`generate_service.py:454-461`）任一 rowcount=0 处被拒，`test_concurrent_commit_same_change_exactly_one_wins` 用 `threading.Barrier(2)`+临时 SQLite 验证「恰一方成功、deck_versions 恰一行、changes=committed」，非长 sleep ✓；受理「占锁+建 job+锚点」同事务（`change_repository.py:905-940`），崩溃不留指向不存在 job 的锁 ✓。
- **stale 语义**：`_with_stale`（`:283-291`）仅对 ready/blocked 且基线落后计算 stale、`model_copy` 不改库（与 plans 同语义）；committed/discarded 不漂移（`test_committed_history_never_goes_stale`）✓；commit 拒绝根因分流：stale 下 corpus 前进→`CorpusChanged`、版本被推进→`VersionConflict`（`:422-433`），`test_corpus_advanced_marks_stale_on_read` 背书 ✓。
- **预算与成本**：`GENERATE_CALL_BUDGET=24`（docs/06:31），最坏 4 批×(content+修复+verify)=12 < 24，含重试余量充足；`accumulate_llm_calls` 在 `handle_generate` 的 `finally`（`:170`）记账 `context.budget.used`，异常路径不漏记；真实 adapter 将 `BudgetExceededError` 转 `BudgetExceeded`(BUDGET_EXCEEDED) DomainError（`adapter.py:240/309-310`）→ worker failed 类型化 ✓；deadline/取消守卫在每次模型调用前 `guard_active`（`:171/185/346` 区），`test_cancel_before_model_call`/`test_expired_deadline_before_model_call` 断言 `provider.calls==[]`（不烧钱）✓。
- **迁移安全**：`SCHEMA_VERSION=4`，新库 DDL 含 `params_json`/`changes` 表；老库 `init_db` 走 `row[0] < SCHEMA_VERSION → _migrate_columns`（PRAGMA 幂等检查后 `ALTER ADD COLUMN params_json`，可空、不重写数据）+ `UPDATE version=4`，`changes` 表由 `CREATE IF NOT EXISTS` 补齐 ✓。
- **分层规范**：`courseware_core` 无 FastAPI 依赖（`generate_service` 仅 sqlite3/Pydantic/内部模块）；`GenerateService` 组合 `PlanService(conn)` 消费权威接缝，`plan_service` 不反向 import `generate_service`，无循环；`retrieval/context.py` 抽取后 `PlanService._assemble_context` 行为逐行等价（同轮转/同双闸常量注入），plan 回归 474 全绿未破 ✓。

---

## 总体结论

**需修复后复审（不可直接提交）**。B1（修复路径页/claim 错配、核验输入陈旧）与 B2（重复 verdict 被采信致假绿）均直接触及 T09 核心约束「可信链不可降级」，且各自存在被同构夹具/缺测掩盖的真实触发路径，须先红后绿闭合再提交。N1–N6 进本轮 backlog（N1 为明显编辑笔误，建议随 B 一并即修）。除 B1/B2 外，受理门禁、并发同事务 CAS、stale 读路径、预算/守卫、契约形状与文档同步整体自洽，474 全绿 + validate_pack 23/23 为客观基线。

---

## 闭环记录（复审，2026-09-20）

- 复审基线：工作树 diff vs `069083b`（含 untracked）。验证命令与结果：`backend/.venv/bin/pytest backend/tests` → **478 passed / 0 failed**（18.31s，净增 4 条回归）；`.venv/bin/python tools/validate_pack.py` → **23/23 PASS**。逐条读 diff + 新增回归核验真伪，未轻信声明。

### B1｜修复路径同版本落库 — 已闭合 ✓
- 证据：`_locate_batch` 现返回 `(located, failures, final_proposal)`（`generate_service.py:363`），`_generate` 以 `located, failures, proposal = self._locate_batch(...)`（`:211`）接收，使核验输入（`:225 proposal.slides`）、落库 slides/warnings（`:259-260`）全部取自修复后最终 proposal。
- 回归 `test_repair_proposal_slides_are_the_ones_persisted`（`test_generate_service.py:614`）：`good.slides[0].title` 改为「NVIC分组（修复后）」与 bad 夹具默认标题「NVIC分组」**显式区分**（`:621`），断言落库=修复后标题。旧实现下 slides 取自 bad 原始 proposal → 标题为「NVIC分组」≠断言 → **必红**。原「bad/good slides 同构掩盖」缺陷已用差异化夹具消除。
- prior 上下文：`generate_messages.py:34-38` 将上轮 `prior.model_dump` 追加进 user 消息——内容为模型自身上轮输出（claims/slides/missing_evidence），不含教师材料原文/Key/路径，且 quote 本就随 selected 片段进过 prompt，**无新增敏感泄露面**，符合 docs/06:37「一次带校验错误的修复」语义。✓

### B2｜重复 verdict 不采信 — 已闭合 ✓
- 证据：`_verify_batch:394-402` 重复 `claim_id` 时 `checks_map.pop(c.claim_id)` + `duplicate_ids.add`，`:232-240` 对 dup_ids 内 claim 记 `not_checked`（reason "duplicate verdicts"）。三次及以上重复：pop 后第三次虽重入 checks_map，但 `_generate:232` 先判 `in dup_ids` → 仍 not_checked，**无残留采信路径**。
- 回归 `test_duplicate_verdicts_never_greenwash`（`:629`）：首 supported 次 unsupported，断言 `claim_checks[0].semantic_status=="not_checked"` 且 `status=="blocked"`。旧实现保留首条 supported → can_commit True → ready → **必红**。✓
- 误伤核查：正常 `verdicts(*ids)` 每 id 一次 → dup 集合空 → 不触发；漏答走 `checks_map.get is None` 分支、重复走 dup 分支，二者互斥。既有正常路径测试全绿佐证**不误伤**。✓

### N1–N5 处置 — 接受 ✓
- **N1**：`samples.py` 重复键与 `CANDIDATE_CHANGE` 死常量已彻底删除（grep 全仓无残留），SAMPLES 仅余唯一 `CandidateChange` 内联登记，双向契约覆盖未减、validate_pack 23/23。✓
- **N2**：`layout_valid` 增 `{s.id for s in slides}=={s.id for s in plan.slides}`（`:266`）；回归 `test_slide_id_set_must_equal_plan_ids`（`:651`，ps1→ps999）旧实现仅比 len → ready，新 → blocked，**必红**。✓
- **N3**：`DeckSpec` 构造包 `try/except ValidationError → ModelOutputInvalid`（`:281-298`）；`ModelOutputInvalid` 为 DomainError（`errors.py:114`）、worker `except DomainError→failed`、`error_mapping:46` 同步 502，与 api.md:83「MODEL_OUTPUT_INVALID 502或job.failed」一致。回归 `test_model_overflow_pages_fails_typed_not_internal`（`:665`，12 页×每批 16 页累加越界）旧实现抛裸 ValidationError → `pytest.raises(ModelOutputInvalid)` 不匹配 → **必红**。✓
- **N4**：`ChangeRepository.mark_committed_tx`（`change_repository.py:110-124`）单一 SQL 实现，`mark_committed`（自管事务）与 commit 的 `_mark`（`generate_service.py:496`，同事务）均委托之，双源漂移面消除。✓
- **N5**：修复分支复用 `_generate` 已加载的 `content_body/content_ver`（`:369-373`），二次 `load_system_prompt` 消除。✓

### N6｜506 行 — 接受（附条件）
- messages 装配已外置 `generate_messages.py`（纯函数），`generate_service.py` 降至 506 行，职责收敛为「受理门禁 + 批生成编排 + 门 + 读取/提交」。按 AGENTS §3「>500 仅触发评审、不机械拆成碎片」，**接受**当前状态：再硬拆会把批循环（locator→修复→核验→门）的强时序内聚切散、反损可读。条件：若后续 edit 链路或门规则继续膨胀，优先外置「门与结构校验」而非编排层。

### flake 治本 — 接受
- `conftest.py` session autouse `_warm_tokenizer` 预热 jieba 词典首载，**未放宽** e2e 10s 等待窗口，属消除冷启动竞态的正确定位，不掩盖真实超时。✓

### 复审结论
**可提交**。B1/B2 真实闭合且回归在旧实现下均必红；N1–N5 闭合、N6 与 flake 治本接受；prior 上下文无敏感泄露、dup 处理不误伤正常路径，未见修复引入的新问题。可信链「假引用进不了候选、模型 verdict 不掩盖定位/重复失败、can_commit=false 进不了 commit、生成与应用分离」四项核心约束本轮全部闭合且有差异化回归背书。
