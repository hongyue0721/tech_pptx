# T04 独立 Review 报告 — SQLite 任务、幂等与版本仓库

- 工程根：`Courseware_Copilot_Demo_Plan_v1`
- 基线 commit：`18f4f6c`（T03）；审查对象：全部未提交改动（`git status` 7 改 + 20 新文件，核心在 `backend/`）
- 审查方式：干净会话，只审 diff 与相关契约，未改动任何仓库代码（本报告除外）
- 契约依据：`docs/07-jobs-and-versioning.md`、`docs/18-core-interfaces.md`、`contracts/models.schema.json`、`contracts/routes.json`、`contracts/openapi.json`、`AGENTS.md`、`tasks/tasks.json`

## 验证执行

- `.venv/bin/pytest tests/ -q` → **206 passed**（与声称一致，退出码 0）
- 自建探针 `/tmp/probe_t04.py`（不入库）实测：
  - PROBE1 `claim_next` 4 线程并发领取同一 queued job → 仅 1 次领取（**单语句 CAS 成立**）
  - PROBE2 `commit_version` 4 线程并发同 `expected_base=0` → 仅 1 行入库、`current_version=1`（**数据无双写**），其余 3 个抛原始 `sqlite3.IntegrityError`（**未映射为 409**，见 N2）
  - PROBE3 `restore` 跨 corpus（目标 v1 corpus=1，项目已升 corpus=2）→ 抛 `CORPUS_CHANGED`（**行为正确，但无显式测试**，见 N12）
  - PROBE4 顺序交错 `claim→request_cancel` → running 仅置 `cancel_requested`（正常路径 OK；但 get 与 UPDATE 之间的 TOCTOU 交错未覆盖，见 B1）

---

## BLOCKER

### B1 — `request_cancel` 的 queued 分支缺 CAS，与 worker 领取竞态导致"锁释放与 job 运行状态不原子"

- 位置：`backend/src/courseware_core/storage/job_repository.py:93-117`（尤其 `:99-110`）
- 问题：`request_cancel` 先在事务外 `self.get(job_id)` 读 `status`，判定 `queued` 后执行
  `UPDATE jobs SET status='cancelled', stage='finished', cancel_requested=1 ... WHERE id = ?`
  与 `UPDATE projects SET active_job_id = NULL ... WHERE active_job_id = ?`。
  该 UPDATE **没有 `AND status='queued'` 守卫**。在单 Worker 架构下 `claim_next` 由 worker 线程执行、`request_cancel` 由 HTTP 线程执行，二者并发：
  1. HTTP 线程 `get` 读到 `queued`；
  2. worker 线程 `claim_next` 把该 job 置 `running` 并开始 `_execute`；
  3. HTTP 线程执行 queued 分支 UPDATE → 把**正在 running 的 job 强改为 `cancelled`**，同时**释放项目锁 `active_job_id`**。
  结果：worker 仍持有该 job 在跑（其快照为 running），跑完 `finalize(succeeded)` 再次覆盖状态；而项目锁在 job 实际仍在运行时被提前释放，随后同项目可被新写任务占用 → **同项目出现两个并发写任务**，破坏 `docs/07 §3`"同项目同一时刻最多一个写任务"与 `§6`"running 置 cancel_requested 并由工作器在边界终止"。锁释放与 job 终态在该交错下不原子。
- 依据：`docs/07 §3`（写入互斥）、`docs/07 §6`（取消状态机）；`tasks.json` T04 验收项 1「单Worker/项目锁」。
- 测试缺口：无任何用例构造"cancel 与 claim 交错"，该竞态路径未被覆盖（详见 N12）。
- 建议修法：queued 分支改为带守卫的 CAS——
  `UPDATE jobs SET status='cancelled', stage='finished', cancel_requested=1, updated_at=? WHERE id=? AND status='queued'`；
  若 `rowcount==0` 则说明已被领取，重读后按 running 分支处理（仅置 `cancel_requested`，不动锁）。释放锁的语句也应并入同一判定，确保"取消生效"与"释放锁"针对的是同一个被确认仍为 queued 的 job。补一条交错/双线程回归用例。

---

## NONBLOCK（进 backlog，不当场全面重构）

### N1 — 创建 queued job 与占用项目锁非原子，存在锁泄漏窗口
- 位置：`backend/src/courseware_core/storage/project_repository.py:48-63`（`acquire_write_lock` 独立事务）；当前无"占锁+INSERT job"同事务编排（`job_service.py` 无 create，`routes_projects.py` 无写路由）。
- 问题：`acquire_write_lock` 与 `JobRepository.create` 各用 `with conn` 独立事务。若崩溃发生在占锁成功、job 落库之前，`projects.active_job_id` 指向不存在的 job，`mark_interrupted_on_startup`（`job_repository.py:69-91` 仅处理 `status='running'`）无法回收 → 项目永久锁死。
- 依据：`docs/07 §3`、`docs/18`（领取/提交各用短事务且不变式自洽）。
- 说明：T04 尚无生产创建路径，属前瞻风险；**T08 接入写路由前必须将"占锁+建 job"合并为单事务**。

### N2 — `commit_version` 并发同 base 抛原始 `IntegrityError`，未映射为 409
- 位置：`backend/src/courseware_core/storage/version_repository.py:41-95`（deferred 事务内 SELECT→INSERT→UPDATE）。
- 问题：PROBE2 证明并发下数据正确（主键 `(project_id,version)` 冲突兜底），但第二个提交抛 `sqlite3.IntegrityError` 而非 `VersionConflict`。一旦 commit 经 HTTP 暴露，将冒泡为 500 而非契约的 409。
- 依据：`docs/18`（版本号服务端权威、CAS 提交）；`AGENTS.md §3`（明确异常类型）。
- 建议：改为显式 CAS——先 `UPDATE projects SET current_version=current_version+1, updated_at=? WHERE id=? AND current_version=? AND corpus_revision=?`，以 `rowcount` 判定冲突后再插版本行。

### N3 — `finalize` 缺状态前置守卫，可越权覆盖终态
- 位置：`job_repository.py:119-155`（`UPDATE ... WHERE id=?` 无 `AND status='running'`）。
- 问题：对非 running（如已 cancelled/interrupted）的 job 调用 `finalize` 会无条件改写终态；重复 finalize 不幂等。与 B1 同族（缺 CAS）。
- 建议：`finalize` 增加 `WHERE id=? AND status='running'`，`rowcount==0` 时按幂等读取返回当前行。

### N4 — running job 的取消仅在领取边界检查一次，框架无取消轮询通道
- 位置：`backend/src/courseware_core/jobs/worker.py:109-136`；`JobHandler = Callable[[Job], Optional[JobResultRef]]`（`:14`）。
- 问题：`_execute` 仅在入口读一次 `cancel_requested`；handler 执行中不复查，签名也未传 `docs/18` 约定的 `JobContext.cancel-check`。若真实 handler 不主动抛 `JobCancelled`，running 中的取消请求（`cancel_requested=1`）不会生效，job 仍 `succeeded`，与 `docs/07 §6`"由工作器在边界终止"未闭环。
- 说明：P0 无业务 handler，框架已提供 `JobCancelled` 协作机制，属"待 handler 接入时补齐取消通道"。

### N5 — 幂等占位行崩溃残留，24h 内同键恒 409 in-flight
- 位置：`idempotency_service.py:48-61`；`idempotency_repository.py:38-47`（`try_reserve` 写 `RESERVED_PLACEHOLDER=-1`）。
- 问题：若进程在 `produce()` 执行中途崩溃，占位行（`response_status=-1`）残留；`_replay_or_conflict:67-70` 对 -1 抛 `IdempotencyConflict`"in flight"，导致该 key 在 24h TTL 内被永久拒绝。`worker._recover_on_startup` 只清 running job，不清 idempotency 占位。
- 依据：`docs/07 §2`（保留 24h 语义应可被新请求推进，而非崩溃后死锁）。
- 建议：占位行使用更短的"在飞 TTL"，或启动/领取时清理超期 -1 行。

### N6 — `IdempotencyConflict` 语义复用：并发同键同请求被误判为"不同请求"
- 位置：`idempotency_service.py:48-54, 64-70`；`errors.py:34-40`（message 固定为"reused with a different request"）。
- 问题：`docs/07 §2` 规定"相同 key+相同请求返回相同对象/任务"。当前对"同键同请求但首个仍在执行"直接抛 409（且 message 声称是不同请求），语义偏差。
- 建议：为 in-flight 与 conflict 区分错误码或 message（如 `IDEMPOTENCY_IN_FLIGHT`/409+Retry-After），避免与"异请求冲突"混淆。

### N7 — 创建项目幂等 scope 命名空间过窄（无认证）
- 位置：`routes_projects.py:29`（project_ref 恒 `"-"`）；`idempotency.py:26-33`（`session_id` 恒 `local`）。
- 问题：`scope = "local|-|POST /projects"`，所有创建项目请求共享同一键空间；多用户/多项目场景下相同 `Idempotency-Key` 会跨项目串扰。
- 依据：`docs/07 §2`（scope=认证会话+项目+路由）。
- 说明：`demoBasic` 认证接入后由 `request.state.session_id` 区分，当前 P0 单用户可接受，需注释固化前提。

### N8 — `claim_next` 不校验项目锁一致、不按 kind/项目过滤
- 位置：`job_repository.py:52-67`（`WHERE status='queued' ORDER BY created_at`）。
- 问题：领取不核对 `projects.active_job_id == job.id`，依赖"创建时占锁"不变式；该不变式被 N1 破坏时，同项目可能并发两 job（违反 `§3`）。
- 建议：领取时联表校验 `active_job_id` 指向本 job，或至少在不变式破坏时显式失败而非静默执行。

### N9 — artifacts 表缺 version 外键；删除项目不清理磁盘文件
- 位置：`database.py:82-99`（`version` 仅 `CHECK>=1`，无 `REFERENCES deck_versions`）；`project_repository.py:43-46`（`delete` 仅删行，FK CASCADE 删指针行但不删文件）。
- 问题：可写入指向不存在版本的 artifact 指针（`docs/07 §7` 要求绑定 version）；项目删除后 `ArtifactStore` 落盘文件成为孤儿（`§6` 要求清理文件）。读取方向安全（无指针即不读），但空间/一致性 GC 缺失。
- 建议：`ArtifactStore` 增 `delete/cleanup_by_project`；`delete_project` 编排调用；`version` 列加 FK 或在服务层校验存在性。

### N10 — `content_sha256` 的 DB CHECK 弱于 schema pattern
- 位置：`database.py:75`（`GLOB '[a-f0-9]*' AND length=64`）。
- 问题：`GLOB '[a-f0-9]*'` 仅约束首字符，未逐字符校验，弱于 `models.schema.json` 的 `^[a-f0-9]{64}$`。SQLite 无递归 GLOB，属已知限制；实际值由 `version_repository.semantic_hash` 生成不致脏，但约束表达与契约非严格等价（维度 D 关注项）。
- 建议：注释标注"逐字符校验由 Pydantic 层保证"，或入库前 `assert re.fullmatch`。

### N11 — cancel 路由以 job_id 充当幂等"项目"分量
- 位置：`routes_jobs.py:30-32`（`project_ref=job_id`）。
- 问题：`docs/07 §2` scope 第二分量定义为"项目"；cancel 路径无 project 上下文，以 job_id 代理。行为可辩护（job 唯一），但与 scope 定义字面不符。
- 建议：注释固化"cancel 以 job 为作用域"的决策依据。

### N12 — 测试覆盖缺口（竞态与关键拒绝路径未固化，1 处断言过宽）
- 位置：
  - `test_job_repository.py` 无 `request_cancel×claim_next` 交错用例（B1 未覆盖）；
  - `job_repository.py:53` 注释声称"并发下只有一个 worker 能拿到"，但无多线程 `claim_next` 测试固化（PROBE1 仅证成立，未入库为回归）；
  - `test_version_repository.py` 无 `restore` 跨 corpus 拒绝用例（PROBE3 证行为正确，未固化）；
  - `test_idempotency_service.py` 未覆盖 `RESERVED_PLACEHOLDER` in-flight 分支（`idempotency_service.py:48-54,67-70`）；
  - `test_artifact_store.py:72-75` `pytest.raises(Exception)` 断言过宽，应精确 `ProjectNotFound`。
- 依据：`AGENTS.md §4`（不得降低断言、关键路径须测）。
- 说明：现有 206 条**无假绿**（sqlite/线程/flock/TestClient 均真实执行、断言具体），缺口为"未覆盖"而非"假装覆盖"。

### N13 — 500 路径日志堆栈脱敏不足
- 位置：`main.py:39`（`logger.exception(...)` 记录完整 traceback）。
- 问题：`AGENTS.md §6` 要求日志脱敏；完整堆栈可能含内部路径/变量。响应体已正确收口为 `INTERNAL_ERROR`（`test_error_500.py` 验证），仅日志侧需收敛。
- 建议：异常日志降级为类型+摘要，或经统一脱敏器输出。

### N14 — `artifact_store.put` 空捕获重抛 + rename 后未 fsync 父目录
- 位置：`artifact_store.py:76-101`（`except sqlite3.Error: raise` 无实际动作）；`:74`（`os.replace` 后未 `fsync` 目录）。
- 问题：空 try/except 仅表意图、不改变行为（噪音）；极端崩溃下 rename 元数据可能未持久化（"文件先于指针"顺序本身正确，验收项满足）。
- 建议：移除空 except 或改为记录后重抛；rename 后对父目录 `os.open(O_DIRECTORY)+fsync`（POSIX 增强）。

---

## 维度 D 专项核对结论

- **create_app 默认路径不启动后台线程**：`main.py:61-63,67-73` — `worker_handlers is None` 时 `worker=None`，lifespan 不 `start()`。✅ 通过（建议补一条"默认 None 不建线程"的回归）。
- **RequestIDMiddleware 捕获 Exception 后 ServerErrorMiddleware 二次处理**：`main.py:34-47` 在 `ServerErrorMiddleware` 内侧收口，异常被消化为 500 JSONResponse，不再冒泡；`test_error_500.py` 验证最终 500 形状含 `request_id` 与 `X-Request-ID` 头，未被纯文本覆盖。✅ 通过。
- **幂等占位行与 204（body None）存储/重放一致**：`idempotency_service.py:60`（`json.dumps(None)='null'`）+ `routes_projects.py:48-50` + `idempotency.py:63-64`（`body is None → Response(status)`）；重放 `response_status=204≠-1 → json.loads('null')=None → 204`。✅ 一致（崩溃残留隐患见 N5）。
- **jobs 表 CHECK 与 schema enum 逐一对应**：kind/status/stage 三组枚举、`llm_calls BETWEEN 0 AND 24`、`base_version>=0`、`corpus_revision>=0`、`cancel_requested IN(0,1)` 与 `models.schema.json` 完全对齐。✅ 通过（`result_ref/error` 存 JSON 由 Pydantic 校验，可接受）。
- **deck_versions/artifacts 与 docs/07 §4/§7 字段落点**：`artifacts` 表覆盖 §7 全部字段（project_id/version/corpus_revision/renderer_version/font_profile/sha256/size/mime/validation_status/source_type）；`deck_versions` 覆盖 §4 提交/恢复所需字段。✅ 落点齐全（version 外键缺失见 N9）。

---

## 结论

**需修复后提交。**

- 阻塞项 1：B1（`request_cancel` queued 分支缺 CAS，与领取竞态破坏项目锁互斥与取消状态机，且无测试覆盖）——必须修复并补交错回归用例后方可提交。
- 其余 14 项为非阻塞，建议记入 backlog：N1/N2/N3/N8 与并发/事务边界正确性相关，应在 T08/T09/T12 接入写路由与 commit 路由前一并原子化；N5/N6/N7 为幂等语义细化；N9/N10/N11/N12/N13/N14 为契约/测试/日志/健壮性收敛项。
- 验收四项对照：① 单Worker/项目锁——flock 单例与仓储层 CAS 已实现并测通，但 B1 竞态使"项目锁"在取消路径上不正确，**未达 DONE**；② 幂等同键与冲突——达成；③ 重启 interrupted——达成；④ 原子文件与数据库指针一致——落盘顺序与读取校验达成，删除/外键清理见 N9。整体因 B1 判为 PARTIAL，修复后可提交。

---

## 修复闭环记录（Builder 2026-09-19，先失败用例后修复）

- **B1 已修**：`request_cancel` 全 CAS 化（queued UPDATE 带 `AND status='queued'` 守卫，rowcount=0 落 running 置标志分支；锁释放仅随"确认仍为 queued"的取消发生）。回归：`test_cancel_vs_claim_race_keeps_lock_invariant`（双线程 barrier 交错 ×20 轮，断言"running 必持锁 / cancelled 必放锁"不变式）。
- **N3 已修**：`finalize` 加 `AND status='running'` 守卫，终态不可覆盖、重复调用幂等返回当前行（`test_finalize_terminal_job_is_idempotent_no_override`）。
- **N2 已修**：`commit_version` 改显式 CAS（条件 UPDATE 移动指针→rowcount 判冲突→再插版本行），并发同 base 失败方得 VersionConflict 而非 IntegrityError（`test_concurrent_commit_same_base_maps_to_version_conflict` 4 线程 barrier）。
- **N5 已修**：占位行在飞窗口 `INFLIGHT_TTL_SECONDS=60`，崩溃残留超窗可被同键请求接管；新鲜占位仍 409 in-flight（`test_stale_placeholder_is_reclaimed`/`test_fresh_placeholder_conflicts_as_in_flight`）。
- **N12 已修**：多线程 claim 单赢家回归入库（`test_concurrent_claim_next_single_winner`）；restore 跨 corpus 拒绝用例入库；`raises(Exception)` 收紧为 `ProjectNotFound`。
- **N13 已修**：500 路径日志降为异常类型+request_id，不落完整堆栈。
- **N14 已修**：移除空 except 噪音；os.replace 后 fsync 父目录。
- **N7/N11 已修（注释固化决策前提）**：P0 单用户 scope 前提、cancel 以 job_id 代理项目分量的依据写入代码注释。
- **进 backlog（本轮不当场重构）**：N1/N8（占锁+建 job 同事务编排，T08 写路由接入前）、N4（handler 取消轮询通道，业务 handler 接入时）、N6（in-flight 独立错误码）、N9（artifacts version 外键+删项目清磁盘）、N10（sha256 逐字符 DB CHECK，Pydantic 层已保证）。

**修复后回归**：`.venv/bin/pytest tests/` **213 passed**（+7 条竞态/回归用例）退出码 0；`tools/validate_pack.py` 23/23；frontend `npm run build` PASS。B1 修复后验收项①"单Worker/项目锁"达成，四项全达。
