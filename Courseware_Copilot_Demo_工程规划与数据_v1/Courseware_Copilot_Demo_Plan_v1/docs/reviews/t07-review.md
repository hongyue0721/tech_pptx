# T07 独立 Review 报告｜APP 模型 Adapter 与预算

- 审查会话：干净会话，只审 diff 与相关契约，未修改任何业务代码（仅写本报告）。
- 基线 commit：`d0a0e5e`（T06 已提交状态）。
- 审查范围：`git status` + `git diff` + untracked 新文件。
  - 已跟踪改动：`backend/src/courseware_core/errors.py`（+7 个 LLM 错误族 DomainError）、`process.md`（1.0.12→1.0.13，T07 状态行）、`validation-report.{md,json}`（仅 generated_at 刷新，PACK_STATIC_ONLY，无 T07 实质声明）。
  - 新增运行代码：`backend/src/courseware_core/llm/{__init__,config,budget,adapter}.py`（14/69/65/289 行）。
  - 新增测试：`backend/tests/unit/test_llm_adapter.py`（434 行，30 条）。
- 契约依据：docs/06（重试矩阵、预算、usage unknown、取消、能力探测、日志脱敏）、docs/18（LLMProvider/JobContext 契约）、AGENTS.md §3/§4/§6。
- 验证命令：`backend/.venv/bin/pytest tests --tb=no -p no:warnings` → **345 passed / 0 failed**（9.60s），其中 T07 新增 30 条全绿；`pytest tests/unit/test_llm_adapter.py` 单独 30 passed。与 process.md 声明一致。
- 真实协议 smoke：付费动作，本轮明确不做（已知豁免，不算缺陷）；能力位 `supports_json_mode`/`supports_temperature` 的真值须由 smoke 探测后固化（见 N4）。
- contracts/ 未改动，无新路由，契约一致性确认（错误码 HTTP 映射按 process.md 声明推迟到 T08 接入业务时补，当前无调用方，可接受）。

---

## BLOCKER

### B1｜HTTP 200 但响应体非 JSON（网关/代理故障页）时抛裸 AttributeError，逃逸 DomainError 体系

- 位置：`backend/src/courseware_core/llm/adapter.py:185`（`outcome.body.get("usage")`）、`adapter.py:186-190`（`outcome.body.get("id")`）；根源 `adapter.py:250-253`（`raw.json()` 解析失败时 `body = None`）。
- 问题：`_dispatch` 中 `raw.json()` 抛 `ValueError` 时静默把 `body` 置为 `None`。当供应商前置的网关/WAF/代理返回 **200 状态 + HTML 文本**（超时页、拦截页、网关错误页，真实接入的高概率故障形态）时，`complete_json` 走到 `outcome.body.get("usage")` 抛出裸 `AttributeError: 'NoneType' object has no attribute 'get'`。
- 复现证据（/tmp 探针，MockTransport 返回 `Response(200, text='<html>gateway error</html>')`）：
  ```
  raised: AttributeError | 'NoneType' object has no attribute 'get'
  ```
- 依据条款：
  - AGENTS.md §3「明确异常类型」：AttributeError 不是 typed 异常，HTTP 层（T08 的 error_mapping）无法映射，最终以 500 INTERNAL 形式漏出，违反 docs/18「core 抛结构化 DomainError，由 HTTP/CLI 分别映射」。
  - 本任务验收点即「typed JSON + schema 校验」与错误策略；`ModelOutputInvalid`（"response has no assistant message content"）已为 body 结构异常准备了正确出口，此路径却绕过了它。
  - 真实 smoke 尚未执行，此类网关行为恰是 smoke 要暴露的首要故障形态；不在代码层闭合，smoke 时必现。
- 测试为何没拦住：`ScriptedTransport` 所有脚本步骤均为合法 JSON 响应或异常对象，无「200 + 非 JSON 体」用例。
- 建议修法：在 `complete_json` 中 status==200 分支入口处增加 `if not isinstance(outcome.body, dict): raise ModelOutputInvalid("response body is not JSON", {"stage": stage, "status": outcome.status})`；并补一条回归测试（200 + text/html → ModelOutputInvalid，且 transport.requests == 1 不触发重试）。

---

## NONBLOCK

### N1｜重试 sleep 之后、重试请求发出之前缺 `ensure_active`，取消/deadline 可能被最后一次成功响应吞掉

- 位置：`backend/src/courseware_core/llm/adapter.py:230-234`（`_send` 中 `context.ensure_active()` 在 `self.sleep(...)` **之前**，sleep 后 `continue` 直接回到 `consume(1)` 并 dispatch）。
- 问题：任务卡核查点 2d 要求检查时机覆盖「发请求前、重试间隔后、修复前」。现有检查点：`complete_json` while 顶部（发请求前✓、修复前✓）、`_send` sleep 前（≈重试间隔**前**）。「重试间隔后」缺失。后果有两层：
  1. sleep（最长 5s）期间取消位置位或 deadline 到期，重试请求仍会发出（多一次计费风险 + 多扣一次预算）；
  2. 更重要的：取消在最后一次请求飞行期间置位且该请求成功返回时，`complete_json` 在 `return TypedCompletion(...)` 前无任何 `ensure_active`，**取消被正常返回值静默吞掉**。
- 缓解：窗口小（单次调用至多 2 请求 + 5s 退避）；T08 worker 在步骤边界复查取消位可兜底。但 docs/06「检查取消位并停止后续步骤」的库级语义不应依赖调用方补救。
- 建议：将 `ensure_active()` 移到 `sleep(...)` 之后（sleep 前查本就无意义），并在 `complete_json` 的 `return` 前补一次 `ensure_active()`；相应调整 `test_cancel_before_repair` 类似思路补「取消于请求飞行中置位」用例。若负责人认为「取消后完成的结果由调用方丢弃」是既定语义，则在 budget.py 注释固化该边界，交 T08 落实。

### N2｜JobContext 缺 docs/18 契约列出的 project/revision/trace 字段

- 位置：`backend/src/courseware_core/llm/budget.py:43-51`。
- 问题：docs/18「JobContext 含 deadline/cancel-check/call-budget/**project/revision/trace**」。实现只有前三者。任务卡验收点只列了前三者，且 T07 尚无调用方，空字段无意义，故不算阻塞；但 T08 上下文组装接入时若遗忘，trace/usage 落库（process.md 已列 T08 待办）将缺挂载点。
- 建议：T08 接入时补齐三字段（可为 Optional），或在 budget.py 注释明确「project/revision/trace 由 T08 按契约补齐」，防止契约静默缩水。

### N3｜`LLMConfig.max_attempts` 是死配置：可从环境变量读取但 adapter 从不使用

- 位置：`backend/src/courseware_core/llm/config.py:26`（默认 2）、`config.py:68`（`APP_LLM_MAX_ATTEMPTS` 入 env）、对照 `adapter.py:224`（`retry_budget = 0 if network_retry_used else 1`，重试配额硬编码）。
- 问题：运维设 `APP_LLM_MAX_ATTEMPTS=5` 期望更多重试，实际无效——「看起来可配置实际是常量」的误导性配置。docs/06 规定临时性失败「至多一次」重试，该值本不应开放配置。
- 建议：二选一当场修：① 删除 `max_attempts` 字段与 env 读取（YAGNI，规范即硬约束）；② 接线为 `retry_budget = max_attempts - 1` 并注释「docs/06 规定至多一次，故默认 2；调大须先改规范」。推荐 ①，同时更新 `test_from_env_reads_app_llm_variables`。

### N4｜能力位 `supports_json_mode`/`supports_temperature` 不在 from_env 中，smoke 结论无法落为配置

- 位置：`backend/src/courseware_core/llm/config.py:58-69`（from_env 未读能力位，恒默认 True）。
- 问题：docs/06「temperature、response_format 均按探测结果发送」。smoke（待授权）若发现供应商不支持 json_object 或 temperature，当前只能改代码关闭，与环境变量驱动的其余配置不对称；demo 换供应商时易踩。
- 建议：from_env 增加 `APP_LLM_SUPPORTS_JSON_MODE`/`APP_LLM_SUPPORTS_TEMPERATURE`（缺省 True），并在 smoke 后把实测结论写入 env 样例文档。

### N5｜`CallBudget.consume` 非线程安全，与 docs/06「单次模型并发最多 2」存在竞态隐患

- 位置：`backend/src/courseware_core/llm/budget.py:24-27`（check-then-increment 无锁）。
- 问题：两个线程共享同一 `CallBudget` 时可能双双通过 `count > remaining` 检查，实际请求次数超出预算上限。T07 当前无并发调用方（单 worker 串行），不构成现行为缺陷；但 docs/06 允许单次模型并发 2，T08 若并行调用 stage，预算语义即被破坏。
- 建议：T08 引入并发前加 `threading.Lock`，或在 budget.py 注释固化「单线程假设，并发接入前须加锁」，防止静默超支。

### N6｜测试盲区：无 assistant content 分支、403、Retry-After 非数字格式、5xx 两次耗尽无直接用例

- 位置：`backend/tests/unit/test_llm_adapter.py`。
- 问题：以下分支仅靠代码走查确认，无测试固化：
  1. `_extract_content` 返回 None → "response has no assistant message content"（`adapter.py:192-196`）；
  2. 403 → ModelAuthError（只测了 401，`adapter.py:174` 同一行覆盖，风险低）；
  3. Retry-After 为非数字（如 HTTP-date）→ ValueError → 回落 0.5s 默认退避（`adapter.py:246-249`）；
  4. 503 两次 → ModelUnavailable（只测了 429 两次，同路径）。
- 建议：低成本各补一条（约 20 行），优先 1 与 3——它们是独立分支而非同行覆盖。另可顺带断言 `Retry-After` 头为病态值（如 "nan"）时不抛异常（`time.sleep(nan)` 会 ValueError，属外部头注入的防御性边界）。

### N7｜类型标注小缺口：`_validate` 的 model 参数与 `_domain_from_internal` 返回类型无标注

- 位置：`backend/src/courseware_core/llm/adapter.py:277`（`def _validate(self, content: str, model):`）、`adapter.py:281-284`（返回类型缺标注，参数可收窄为 `Exception` 联合类型）。
- 问题：AGENTS.md §3「Python 使用类型标注」。模块内其余函数标注完整，此两处属遗漏。
- 建议：补 `model: type[BaseModel]` 与 `-> DomainError`（或具体联合类型），一行成本。

---

## 结论

- **阻塞 1 项（B1）**：200 + 非 JSON 响应体的裸 AttributeError 逃逸，须修复并补回归测试后，T07 方可提交。
- **非阻塞 7 项（N1–N7）**：N1（重试间隔后取消检查缺失/取消可被吞）建议当场低成本修（两处检查点移动）；N3（max_attempts 死配置）建议当场删或接线；N2/N4/N5 为 T08 接入前的契约与并发预留，进 backlog 并在 process.md 记录；N6/N7 测试与标注补齐，低成本可随 B1 一并处理。
- 重试矩阵核心语义（至多一次、配额跨修复共享、401/403 与 400/404 区分不重试、Retry-After 封顶 5s）、预算语义（按实际 HTTP 请求扣减、发请求前拦截、修复请求同受预算约束）、usage unknown（None 非 0）、repr/str 不泄 api_key、contracts/ 零改动、文件行数（65–434 行）均审查通过。
- process.md 1.0.13 状态行与实测一致（345 全绿、smoke 待授权、未做项如实列明），无虚报。
- 修复 B1（建议连同 N1/N3/N6/N7）后，T07 可进入「真实协议 smoke 预算授权」流程；smoke 属独立验收项，其结论（能力位真值、Retry-After 实际行为）回填 N4。

---

## 修复闭环记录（2026-09-19，Builder）

- **B1 已修**：`complete_json` status==200 分支入口加 `isinstance(outcome.body, dict)` 守卫→ModelOutputInvalid；回归用例 `test_200_with_non_json_body_raises_model_output_invalid_no_retry`（先红复现裸AttributeError，修后绿，断言不触发重试）。
- **N1 已修**：`_send` 中 `ensure_active` 移到 sleep 之后（退避期间取消/deadline置位拦截重试请求）；`return TypedCompletion` 前补 `ensure_active`（取消不被成功响应吞）。回归用例2条（`test_cancel_during_retry_backoff_blocks_second_request`、`test_cancel_during_flight_not_swallowed_by_success`，均先红后绿）。
- **N3 已修（方案①删除）**：`max_attempts` 字段/构造参数/env读取/repr/.env.example 的 APP_LLM_MAX_ATTEMPTS 全链路移除；重试配额由代码常量语义（至多一次）承担，符合 docs/06 硬约束。
- **N4 已修（接线）**：`from_env` 读取 `APP_LLM_SUPPORTS_TEMPERATURE`/`APP_LLM_SUPPORTS_JSON_MODE`（缺省true），.env.example 补样例并注明"smoke探测后固化"；用例 `test_from_env_capability_flags`。
- **N6 已修**：补4条盲区用例——缺content分支、403、Retry-After非数字回落0.5s、503两次→ModelUnavailable。
- **N7 已修**：`_validate` 补 `model: type[BaseModel] -> BaseModel`、`_domain_from_internal` 补 `-> DomainError`。
- **N2 注释固化**：JobContext docstring 注明 project/revision/trace 由 T08 补齐（防契约静默缩水）。
- **N5 注释固化**：CallBudget docstring 注明单线程假设、T08 并发前须加锁。
- 回归：pytest **353全绿**（adapter 38条）、validate_pack 23/23、frontend build 绿。contracts/ 零改动确认。
