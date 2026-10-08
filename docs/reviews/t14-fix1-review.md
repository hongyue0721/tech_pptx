# T14-fix1 独立 Review（干净会话，仅审 diff + 契约）

- **执行模型**：qwen3.8-flash（实际 model id：`aliyun/qwen3.8-flash`）。
  说明：任务书预期为 huaweicloud Qwen3.8-Flash，但本会话实际加载的模型 id 为 `aliyun/qwen3.8-flash`，二者同源模型、不同 provider 标注；按"以诚实无知为荣"如实标注，不冒充未运行的 provider。
- **待审 diff**：/tmp/t14-fix1.diff（417 行，已确认应用至工作树：`git status` 显示 plan.py / generate_service.py / useOutlineFlow.ts / OutlinePage.vue / content.md / api.md / models.schema.json / 三个测试文件为 M）。
- **审查时间**：2026-09-22
- **工程真源核对**：AGENT_00_CLOSE_GAPS.md（豁免判据=教师计划 layout、missing_evidence 保守门、双射纪律）、api.md、contracts/models.schema.json、contracts/openapi.json、docs/04:41（可执行门）、app-prompts/{content,verify,audit}.md。

---

## 结论先行

**需修复后提交。** 四个修复对"教师 Web 主链路"本身正确且方向对（越域不参门、集合真值、prompt v5 澄清、双源消除），但"业务真值=集合"的收口**跨面不一致**（B1），且**契约四文档同步缺 openapi.json**（N1，违反 AGENTS §5 与本次任务 G 轴自身验收口径）。B1 是本次修复立论的直接未尽事项，属结构性债务，按仓库"严禁最小修复/根因闭合"规范不得推迟。其余为 N/O，可进 backlog 但 N1/N2 建议随本提交一并处理。

---

## B（阻塞）

### B1 — 集合真值未在 confirm CAS 与 CLI "原样确认" 路径闭合
- 文件：`backend/src/courseware_core/services/plan_service.py:313-315`、`backend/src/courseware_core/cli/app.py:191-196`、`backend/src/courseware_core/models/plan.py:46-55`
- 问题：本次修复的立论是"accepted_goal_indices 业务真值=集合"，并在三处落地——Web 读侧归一化（`useOutlineFlow.ts:72` `[...new Set()]`）、写侧 validator 拒重（`plan.py:50`）。但同一份历史脏 plan（`[0,0,1,2,3]`，仅存在于已 confirmed 计划）经 **CLI 原样确认**路径时，收口是反的：
  1. `cli/app.py:191-196` 的"按原样确认"缺省分支把**存储真值** `plan.accepted_goal_indices` 直接喂进 `ConfirmPlanRequest(...)`。`LessonPlan` 无 uniqueItems（读不炸，符合预期），但 `ConfirmPlanRequest` 的新 validator 会在**构造期**抛未捕获的 `pydantic.ValidationError`（非 DomainError），CLI 崩溃/未定型 500 形态，而非幂等返回。
  2. 即便先行去重，`plan_service.py:313-315` 的已确认 CAS 仍用 **list 相等**：`request.accepted_goal_indices == plan.accepted_goal_indices` → `[0,1,2,3] == [0,0,1,2,3]` 为 False → 走 `ValidationFailed("plan already confirmed with different content; re-plan to change scope")`，对"集合相同、仅历史重复"的载荷**误拒**。这正是审查轴 B 担心的死锁/误拒，在 CLI 面成立（Web 面因 `confirmAndGenerate` 以 `!isConfirmed` 为门，`useOutlineFlow.ts:184`，不会重放 confirm，故 Web 无此触发）。
- 影响定性：无数据损坏、无门绕过、Web 主链路不受影响；但"集合真值"在 CLI/存储回读面未闭合，且能触发未定型崩溃与误拒，与本 diff 自我声明的收口目标矛盾，属结构性债务。
- 建议（择一或组合，须跨面一致）：
  - CAS 改集合语义比较：`set(request.accepted_goal_indices) == set(plan.accepted_goal_indices)`（slides 侧若也认集合语义可一并评估，但 PlanSlide 是有序教学设计，list 比较合理，仅 goal_indices 集合化）。
  - CLI 原样确认分支对 `plan.accepted_goal_indices` 做读侧归一化（`sorted(set(...))`），或在进入严格模型前先对已 confirmed 计划短路幂等返回，避免把存储脏数据回灌到写侧严格校验器。
  - 二者需与 Web `resetFromPlan` 的归一化口径统一，杜绝"Web 归一、CLI 崩溃"的双标。

---

## N（非阻塞，建议随本提交处理）

### N1 — openapi.json 未同步 uniqueItems，契约两文件分歧
- 文件：`contracts/openapi.json:3350`（`ConfirmPlanRequest.accepted_goal_indices`，实测无 `uniqueItems`）vs `contracts/models.schema.json:964`（已加 `uniqueItems:true`）。`git status` 未含 openapi.json，确认本 diff 未触。
- 问题：AGENTS §5 明确"字段/错误改变须同提交改 api.md、OpenAPI、Schema"。本次把 accepted_goal_indices 收紧为集合语义（422 VALIDATION_ERROR），api.md 与 models.schema.json 已改，openapi.json 未改，导致同一约束在两份对外契约里一处声明一处沉默。`validate_pack.py` 只校验 openapi 的路由/引用一致性，不校验字段级 `uniqueItems`，故 23/23 PASS 不能证明 openapi 已同步。
- 影响：运行期由 Pydantic 权威强制，无功能/安全缺口；但任务 G 轴"契约四文档同步完整性"未闭合。
- 建议：openapi.json 的 `ConfirmPlanRequest.accepted_goal_indices` 补 `"uniqueItems": true`，与 models.schema.json 对齐。（PlanSlide.goal_indices 维持不加 uniqueItems 是有意为之，见下）
- 附带确认（合规项）：`PlanSlide.goal_indices` 在 models.schema.json 与 openapi 均无 uniqueItems，而 Pydantic 侧 `ConfirmPlanRequest` validator 拒其重复——属"Pydantic 严于 Schema"，正是 `test_models_vs_schema.py` 方向2（第 97-101、152-156 行范式）允许的口径，不构成契约违例，处理得当。

### N2 — epoch 重建在"取消被拒"路径丢失键盘焦点（可访问性）
- 文件：`frontend/src/pages/OutlinePage.vue:185`（`:key="'goal-'+c.goal_index+'-'+goalToggleEpoch"`）、`useOutlineFlow.ts:113`（blockers 命中时 `goalToggleEpoch.value += 1`）
- 问题：双源消除的正确做法（数组为单一事实源 + 拒绝翻转时强制重建回写 :checked）成立；但 `:key` 变化会**销毁并重建** `<input>`，被拒后焦点掉回 body。键盘用户对"仍被页面引用"的目标按空格取消→被拒→焦点丢失，且共享 epoch 会连带重建整组 checkbox（≤8，性能可忽略，但焦点影响真实）。
- 建议：拒绝分支重建后用 `nextTick` 将焦点还原到对应 goal 的 input（模板 ref 数组按 goal_index 定位），或改用命令式回写 `el.checked = isGoalAccepted(i)`（不重建节点、不丢焦点）。功能正确性不依赖此项，故 N 不 B。

---

## O（观察 / backlog）

### O1 — toggleGoal 缺口目标 reject 分支为死代码
- `useOutlineFlow.ts:101-104`：`if (!goalAcceptable) { epoch+=1; return }`。但缺口/冲突目标 checkbox 在 `OutlinePage.vue:188` 已 `:disabled="...|| !goalAcceptable(...)"`，disabled 控件不触发 `@change`，该分支经 UI 不可达。作为纵深防御可保留，但建议加注释说明"disabled 已挡，此为旁路兜底"，否则误导后续维护者以为可达。

### O2 — audit 提示词内"必审 id 列表"与"可见文字"两序不一致
- `generate_messages.py:99`（`"、".join(required_ids)`，现来自 `_audit_batch` 的 `sorted(required_audit_ids)`，`generate_service.py:498`）与 `:94`（`visible` 按 `batch_slides` 原序过滤）。修复后 id 清单为 sorted 序、可见文字为批序，两序不再一致；且这属模型输入变化但未随 audit prompt 版本留痕（audit.md 仍 v2）。集合不变、指令为"每页恰好返回一次"，语义风险低，且 sorted 相较旧"模型乱序直传"反而更可复现——记录为观察，不要求回退。

### O3 — verify 通道仍向模型喂豁免页可见文字
- `verify_messages`（`generate_messages.py:70`）遍历**全部** `batch_slides`（含豁免 title 页）拼可见文字，而服务端随后把 title 页的 unbound 过滤掉（`generate_service.py:256-258`）。消息侧与过滤侧不对称：模型被要求审、审了又被丢。audit 通道已正确只喂 required（`:94`）。建议 verify 通道同样只喂 required 页可见文字，省 token 且避免诱导模型在豁免页产噪声。（当前无安全后果，过滤兜底正确。）

### O4 — content-v5 "返回空数组"措辞的权衡评估（判定：低风险，非 B/N）
- `content.md:5`：missing_evidence 收窄为"你计划写入的内容找不到支持才报"，并"没有此类缺口就返回空数组"。评估：missing_evidence 是"想写而无据"的**自报**，保守门"非空即 blocked"（`generate_service.py:279-280`）方向是"多报更易 blocked"，v5 减少的是 T14 实测的**过度上报假 blocked**；真实编造/无据断言仍由 claim 证据解析 + verify/audit 的 unbound 通道兜底，未受影响；audit.md:13 亦保留"宁可如实报告、不为显得宽松而漏记"。故"返回空数组"不构成过门隐瞒的实质入口。
- 残留软风险：模型可能把"确需写入却无据"错误归类为"已声明边界"以躲非空门。建议补一句显式封口："若你确实计划写入某条内容而片段无支持，仍必须写入 missing_evidence，不得为通过核验而隐瞒"。属文案加固，非缺陷。

### O5 — 测试与校验覆盖面（含对审查轴 F 的精确澄清）
- `TestUnboundDomainFilter` 三例：例1（audit 通道豁免页 unbound 被滤→ready）、例2（verify 通道豁免页 unbound 被滤→ready）在**旧实现必红**（旧 `unbound.extend(batch_unbound)` / `return ok, list(audit.unbound_assertions)` 不过滤→非空→blocked，与断言 ready 冲突），是真回归；例3（内容页 unbound 仍 blocked）在新旧实现**均通过**，属"防过度过滤"的护栏断言，不是红-on-old——记录以免把"三例全红过"当事实。
- 锁测字面量与 content.md v5 实际文本逐条核对一致："逐字连续子串""不得改写""省略标点""找不到支持""不是缺口，不得上报""返回空数组"均在文；版本锁 `content-v5` 为收紧非放宽。无断言放宽。
- `TestConfirmRequestSetInvariants` 两例（accepted 重复、slide goal_indices 重复）match="unique"，与 `plan.py:51,54` 抛错文案一致；`error_mapping.py:93-109` 将 `RequestValidationError` 统一映射为 422 `VALIDATION_ERROR`（message 落 `details.fields[].message`），与 api.md 新增"重复索引返回 422 VALIDATION_ERROR"一致（轴 D 错误形态确认通过）。
- 契约测试未新增"schema `uniqueItems` 拒绝重复"的方向用例（仅 Pydantic 单测覆盖模型侧）；建议补一条 `INVALID_CASES`（accepted 含重复）以双向锁住 schema 收紧。`validate_pack` 23/23 为静态文档/契约检查，不含 pytest、不校验 openapi 字段级一致，勿当作 N1 已同步的证据。

---

## 各审查轴逐项判定

- **A（toggleGoal 派生正确性）**：状态组合全覆盖（未接受&可接受→加；未接受&不可接受→拒[死代码见 O1]；已接受&被引用→拒+epoch；已接受&无引用→删）。`:checked` 单向绑定 + 拒绝翻转靠 epoch 重建回写数组真值，根因（Vue diff 跳过未变绑定）命中。readOnly/disabled 交互正确（disabled 不触发 change，readOnly 由 `canConfirmAndGenerate` 再挡）。唯一实质问题=N2 焦点。通过（带 N2）。
- **B（resetFromPlan 归一化 × confirm CAS）**：见 **B1**。Web 面因 `!isConfirmed` 门不重放 confirm，无触发；CLI 面 list-相等 CAS 误拒 + 构造期未定型崩溃。需修。
- **C（_required_audit_ids 域过滤）**：无放行漏洞。required 源自 `batch_slides`（模型输出）减 plan-title-exempt，故模型造的未知页 id 必落入 required（其 unbound 被**保留**、参门），且 `layout_valid`（`generate_service.py:296-301`）独立拦增删换页→候选 blocked，域过滤不制造 ready 后门；豁免真值取 plan layout，模型自报 layout 不能自豁免/自去豁免（符合 AGENT_00 硬规则）。required 为空（全封面批）时 verify 全滤 + audit 返回 None 合理（该批无可审内容页；且缺内容页由 layout_valid 兜拦）。audit_messages 的 required 由批序改 sorted 序见 O2（集合不变、低风险）。通过（带 O2）。
- **D（Pydantic validator）**：`ContractModel` 仅 `extra="forbid"`、非 frozen，`model_validator(mode="after")` 返回 self 兼容；错误经 `error_mapping.py` 定型为 422 `VALIDATION_ERROR`。`LessonPlan`（存储模型）无 uniqueItems/无 validator，读历史脏 `[0,0,1,2,3]` 不炸（确认通过）。唯 CLI 把存储脏数据回灌 `ConfirmPlanRequest` 会炸——归入 **B1**。通过（带 B1）。
- **E（content-v5 一致性/隐瞒风险）**：与 audit.md/verify.md 口径不冲突（missing_evidence 自报通道 ≠ unbound 审计通道；audit 仍"宁可如实报告"）。权衡判定低风险，见 O4。通过（带 O4）。
- **F（测试质量）**：例1/例2 真红-on-old、例3 为护栏（非红-on-old，O5 澄清）；锁测字面量与 prompt 一致、无放宽。通过。
- **G（契约四文档同步）**：api.md ✓、models.schema.json ✓、content prompt ✓；**openapi.json ✗（N1）**；docs/04:41 门语义未描述"越域 unbound 不参门"细化（可选补注，未列单独发现）；`docs/t13-skill-golden-chain.md:39` 的 `content-v4` 属历史实测留痕，不改。需补 N1。

---

## 修复清单（提交前）
1. **B1**：CAS 改集合比较 + CLI 原样确认读侧归一化/短路，跨面统一"集合真值"。
2. **N1**：openapi.json `ConfirmPlanRequest.accepted_goal_indices` 补 `uniqueItems:true`。
3. **N2**：拒绝翻转后还原焦点（或命令式回写 checked，弃 :key 重建）。
4. （建议）O5：契约测试补 schema-uniqueItems 双向用例；O1/O3/O4 文案与喂料对称性进 backlog。
