# T14-fix3 代码 Review 报告

- **执行模型 id（如实标注）**：`tierflow/Qwen3.8-Flash`（opencode 父会话模型；本 Review 未派生子代理，全文由该模型独立完成，未照抄历史 review 的 `huaweicloud/qwen3.8-flash` 标识）。
- **待审范围**：`/tmp/t14-fix3.diff`（261 行，5 文件：worker.py、generate_service.py、test_generate_service.py、test_worker.py、validation-report.{json,md}）。
- **方法（沿用首审教训 G）**：结论前逐一读实际文件核对，不凭 diff 描述臆断。已读：`generate_service.py`(1–655)、`worker.py`(全)、`claim_verdicts.py`(全)、`models/{base,common,deck,evidence}.py`、`edit_patch.py`(relations_valid)、`version_repository.py`(commit_version)、`test_generate_service.py`(g11/TestStructuralRecheck/verdicts 工厂)、`docs/06`、`app-prompts/content.md`、grep `_make_batch_claim_ids_unique`。

## 总体结论

**可提交。** 两个修复的核心逻辑正确、合并边界位置准确、测试改写诚实且断言更严、worker 栈留痕设计合理；可信链未破（无假绿、无静默 ready 损坏）。无阻塞项（B=0）。

附条件建议：
- **N1 随本提交改正**（注释引用了不存在的函数名，属本 diff 引入的事实误导，一行改动）。
- **N2/N3 建议同提交补强或显式登记 backlog**：二者是 `_merge_batch_global_ids` 自称"全局唯一只能服务器保证"这一职责的未闭合面，真实 deepseek 链不触发且被下游门兜住，不阻塞可信链，但与"不留结构性债务"的规范相悖，宜早收。

---

## 逐轴判定

### A｜`_merge_batch_global_ids` 正确性 — 通过（带 N2/N3）

`generate_service.py:376-406`。

- **三侧一致映射**：`renames: dict[str,str]` 以局部 id 为键，claims(`:398-399`)、checks(`:400-401`)、fact 块(`:402-405`) 三处均经 `global_id` 查同一 `renames`，同局部 id 必得同全局 id。✓
- **批内自重复 id（模型同批返回两个 c1）**：经推演 `global_id`——第二次 `c1` 命中 `renames` 缓存（`:389` `if local not in renames`），返回**同值** `c1`，**不改名**。这是**正确设计**：批内重复属模型违反本批唯一性，应由门拦截而非服务器静默改名（改名会掩盖 T12"同 ID 异内容互相掩盖"教训）。下游 `relations_valid`(`edit_patch.py:30` 查 `claim_ids` 唯一) 与 `full_coverage`(`generate_service.py:313`) 均判 False → blocked，不静默坏数据。✓
- **extra_ids（模型返回批外 id）的 checks**：与审查重点前提**不同**——`verdicts_to_checks`(`claim_verdicts.py:39-52`) 在 extra 路径下返回的是**遍历 located** 生成的 `not_checked` 条目，`claim_id` 全为批内局部 id，批外 id 仅进 `reason` 文本，**不产生 dangling check 记录**。故 extra 的拦截经 `semantic_status != supported` 门，**不经** relations 门（见 O1）。改名对 checks 与 claims 同步、`semantic_status` 不变，不破坏 extra 检出。✓
- **dup_ids 路径**：checks 的 `claim_id` 同样源自 located 局部 id（`claim_verdicts.py:56-63`），改名与 claims 一致。✓
- **invalid failures 的 cid**：`generate_service.py:243-249` 收集，cid 不在 located（定位失败），`global_id` 为其新建映射（碰撞时加 `-b{n}`）。语义自洽：该 check 本就指向"未入库的失败 claim"，改名使其与全局命名空间一致，避免跨批重名在 `covered` 列表里假触发 `full_coverage`；其 `not_checked` 仍由 semantic 门拦成 blocked。✓
- **未闭合面**：见 N2（长度契约）、N3（本批 value 冲突）。

### B｜合并边界位置 — 通过

- `_verify_batch`(`:250`)、`_audit_batch`(`:268`) 均在 `_merge_batch_global_ids`(`:280`) **之前**调用，消费 `located` 的**局部 id**；`batch_checks` 在 `:242-265`（改名前）构建。✓
- 三处 `extend`（`claim_checks` `:283`、`claims` `:284`、`slides` `:285`）均在 `:280` 改名**之后**，入库为全局 id。✓
- **repair 路径**：`_locate_batch` attempt=1(`:419-463`) 在 `:230` 调用，早于 `:280` 改名，`proposal` 全程局部 id，未被污染。✓
- **illustration 块**：`IllustrationBlock` 无 `claim_id` 字段(`deck.py:20-24`)，`_merge` 仅 `if block.type == "fact"` 才访问 `.claim_id`(`:404-405`)，无 `AttributeError`，不受影响。✓

### C｜`used_claim_ids` 累积语义 — 通过

`used_ids.update(renames.values())`(`:406`) 跨批累积前批全部全局 id；本批无碰撞时 `new = local` 原样(`:390`)，`-b{batch_no}` 后缀仅碰撞时加(`:391-392`)，`batch_no = bi + 1` 从 1 起(`:281`)。✓（N3 是本批内 value 冲突边角，不否定跨批累积语义。）

### D｜测试改写诚实性 — 通过

- `test_duplicate_claim_ids_across_batches_renamed_unique`(`:464-498`)：verify 队列用**局部 id** `verdicts("clmX",...)`/`verdicts("clmX")`(`:479`)。**推演"改名前置"实现**：若 located 在 verify 前已改名为 `clmX-b2`，则 `map_verdicts(expected_ids={clmX-b2})` 把模型返回的 `clmX` 判为 extra → 整批 `not_checked` → `can_commit False` → status blocked → 断言 `:490 status=="ready"` **必红**。回归防线真实。✓ 断言较原版**更严**（id 唯一 `:487`、`clmX-b2` 存在 `:488`、relations True `:489`、fact 引用集合==ids `:497`、checks 集合==ids `:498`），无放宽。✓
- `test_cross_batch_duplicate_claim_ids_renamed_not_masked`(`:1278-1304`)：verify 队列局部 id(`:1292`)；断言改名后**两条不同内容各自保留**（`texts["clm1"]`/`texts["clm1-b2"]` `:1301-1302`）+ `s4.blocks[0].claim_id=="clm1-b2"`(`:1304`)，正面锁死 T12 吞并教训不再发生。期望从 blocked 改为 ready 是**设计变更**（跨批碰撞不再 blocked 而是改名）的如实反映，非放宽。✓
- `test_worker_unexpected_exception_logs_traceback`(`test_worker.py`)：`caplog.at_level(ERROR)` 断言 traceback 含异常消息与 `RuntimeError`，红于"无 `LOG.exception`"的原实现。✓

### E｜worker `LOG.exception` — 通过（带 O2）

`worker.py:173-176`。`DomainError`/`InsufficientEvidence`/`JobCancelled` 走独立分支(`:157-169`)不记栈，仅未预期异常记栈，范围合理；级别 ERROR、格式带 job 上下文，合理。泄露评估见 O2。

### F｜契约面 — 通过（带 N2）

- `docs/06`：grep 全文仅 4 处批次/claim 泛述，**无**"模型负责全局唯一 id"残留表述，无需同步。✓
- `app-prompts/content.md`：示例用局部 id `c1`(`:9`)，**未要求**模型产全局唯一 id，与"模型只见本批、各自 c1 编号 + 服务器改名"设计一致，无矛盾表述需同步。✓
- claim id 长度契约：`Claim.id`/`ClaimVerification.claim_id`/`FactBlock.claim_id` 均 `max_length=128`(`evidence.py:23,37`、`deck.py:12`)，改名事后赋值不重校验，见 N2。

### G｜首审教训沿用 — 已执行

全程读实际文件核对；其中两处 diff 描述与实现不符已据实修正：审查重点 A2"relations 门检出 extra"（实为 semantic 门，见 O1）、注释 `_make_batch_claim_ids_unique`（实为 `_merge_batch_global_ids`，见 N1）。

---

## 编号发现

### N1｜注释引用不存在的函数名 — `generate_service.py:206`
- 问题：注释"（见 `_make_batch_claim_ids_unique`）"，但全仓仅 `_merge_batch_global_ids`(`:377`) 有定义，`_make_batch_claim_ids_unique` 经 grep 确认**只出现在这一行注释**，无任何定义。误导维护者按不存在符号检索。
- 建议：改正为 `_merge_batch_global_ids`。属本 diff 引入的事实错误，建议随本提交一行改正。

### N2｜改名事后赋值不重校验 id 长度契约 — `generate_service.py:398-405`
- 问题：`ContractModel` 仅 `extra="forbid"`、**无** `validate_assignment`(`base.py:24-25`)，故 `claim.id = global_id(...)` 等事后赋值不触发 Pydantic 校验；`DeckSpec` 构造 `revalidate_instances` 默认 never，也不重查 `Claim.id` 长度；`commit_version` 用 `model_copy`+`model_dump_json`(`version_repository.py:70,84`)，**不做 `model_validate`**。链条叠加：若模型产接近 128 字符的局部 id 且发生跨批碰撞，`-b{n}`/`x` 后缀可使其**超过契约 `max_length=128`** 并静默入库（changes 与 deck_versions 两处都不拦）。
- 影响：真实 deepseek 产 `c1` 量级 id 不触发；但 `_merge_batch_global_ids` 自称"全局唯一只能服务器保证"的不变量应含"仍合法"，当前未闭合。
- 建议：`global_id` 分配 `new` 后断言 `len(new) <= 128`（超限时拒绝该候选或按既定策略截断——截断策略须先写契约，勿静默）；或 `_merge` 后对受影响 deck 做一次 `model_validate` 兜底。

### N3｜`global_id` 仅查 `used_ids` 不查本批已分配值 — `generate_service.py:388-396`
- 问题：碰撞判断 `if new in used_ids` 只看前批累积集，不看本批 `renames.values()`。本批内两个**不同**局部 id（如 `c1` 与 `c1-b2`），当 `c1` 因前批碰撞被改成 `c1-b2`、而 `c1-b2` 不在 `used_ids` 中原样保留时，二者映射到**同一全局 id** → `claims` 出现重复。
- 影响：被下游 `relations_valid`(`edit_patch.py:30` 查 `claim_ids` 唯一) 兜成 blocked，**不产生假绿/静默 ready 损坏**；但函数自身未达成"保证全局唯一"的目的，与 AGENTS"不留结构性债务"相悖。真实模型产带 `-b` 的局部 id 概率极低。
- 建议：`if new in used_ids or new in renames.values():` 一并纳入判断（或分配后检测 value 冲突再 `+x`）。

### O1｜审查重点 A2 前提与实现不符（非 bug，建议澄清）— `claim_verdicts.py:39-52`
- 背景表述"extra_ids 的 checks 记录改名后 dangling 语义…relations 门仍可检出"与实现不符：extra 路径不生成 dangling check，批外 id 仅入 `reason`，extra 经 `semantic_status=not_checked` 门拦截，**不经** relations 门。改名不破坏该检出（checks 与 claims 同步、status 不变）。功能正确，建议注释/背景文档澄清，避免后续维护者据"relations 门检出 extra"误判。

### O2｜`LOG.exception` 随栈输出异常消息的理论泄露面 — `worker.py:173-176`
- 格式化参数仅 `job.id/kind/project_id`（内部 id，无凭据）。但 `LOG.exception` 必然随 traceback 输出异常 message 本身；若第三方 provider adapter 把响应体/请求头拼进异常 message（httpx 默认不含 body/key，风险低），有泄露面。AGENTS §6 要求日志脱敏。
- 建议：确认所用 adapter 的异常 message 不携响应体/key；若无法保证，考虑只记 `exc_info` 而对 message 做脱敏。当前范围（仅未预期异常记栈）合理，可接受。

### O3｜文档同步未随本 diff — `process.md`/`CHANGELOG.md`
- 本 diff 仅更新 `validation-report.{json,md}` 时间戳（23/23 不变，无实质内容变化）。AGENTS §5"每轮均更新 process.md""CHANGELOG 只记录真正发生的变更"。T14 两修复属行为变更（跨批 id 由 blocked 改为改名、worker 栈留痕）。
- 建议：提交时同步登记 process.md/CHANGELOG.md（若 builder 在另一提交补则可接受）。

---

## 复核命令（供 builder 自验）
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_generate_service.py::TestHandleGenerate::test_duplicate_claim_ids_across_batches_renamed_unique backend/tests/unit/test_generate_service.py::TestStructuralRecheck -q`
- `PYTHONPATH=backend/src pytest backend/tests/unit/test_worker.py -q`
- 回归防线自证：临时把 `_merge_batch_global_ids` 调用上移到 `_verify_batch` 之前，上述两 generate 测试应转红（证明改名前置被锁死）。
