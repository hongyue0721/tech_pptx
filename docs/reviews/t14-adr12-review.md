# T14 / ADR-12 契约级变更 Review 报告

- 实际执行模型 id：`tierflow/Qwen3.8-Flash`（Qwen3.8-Flash，provider=tierflow）
- 审查会话：干净会话，只审 diff 与契约真源，未改代码
- 待审 diff：`/tmp/t14-adr12.diff`（340 行，ADR-12 partial 教师逐条核准通道）
- 契约真源已逐文件实读核对：`docs/16-risks-and-adrs.md`(ADR-12)、`docs/04-data-model.md`(gate 段)、`api.md`(commit/幂等/错误映射段)、`contracts/models.schema.json`+`openapi.json`(CommitRequest)、`~/Downloads/AGENT_00_CLOSE_GAPS.md`(原保守规则)
- 实现真源已实读核对：`claim_verdicts.py`、`generate_service.py`(commit_change + validation 构造)、`change_repository.py`、`models/changes.py`、`models/evidence.py`、`models/base.py`、`cli/app.py`、`frontend/utils/approvalChannel.ts`、`ReviewPage.vue`、`ValidationPanel.vue`、`idempotency.ts`、`types/models.ts`、`backend/tests/unit/test_generate_service.py`、`plan.py`(confirm 集合语义先例)

## 结论

**需修复后提交。** 门语义、CAS、前后端放行规则、四文档字段一致性、保守维度不放宽等核心正确性均成立；但存在 1 个提交完整性阻塞（B1）与 2 个契约边界/一致性缺陷（N1/N2），修复成本低。O 级进 backlog，不阻断。

---

## 一、正确性确认（逐项核对，无发现部分）

**A. 门三分支互斥完备（generate_service.py:621-652）** — 成立
- 分支1 `status=="ready" AND can_commit`：原路；夹带核准→409 `no partial to approve`（:624-629）。
- 分支2 `NOT分支1 AND channel!=None AND status=="blocked"`：核准通道；精确相等双向校验（:630-644）。
- 分支3 else：committed/discarded/unsupported/conflict/invalid/not_checked/missing_evidence/unbound、ready+!can_commit 一律拒绝（:645-652）。
- `blocked+can_commit=True` 异常组合：正常不可达（status 由 `can_commit?ready:blocked` 同源决定，:364）；矛盾篡改数据下因 can_commit=True 蕴含全 supported→无 partial→channel=None→落 else 拒绝；若同时伪造 claim_checks 含 partial 则进分支2，但仍需精确核准 + :653 结构重算兜底，威胁模型内可接受。
- `ready+!can_commit`：分支1 条件不满足、分支2 要求 status==blocked 不满足→else 拒绝，合理。
- stale 前置分支（:609-620）在 channel 计算之前 raise，不受影响。✓

**B. 放行规则双源一致性（approvalChannel.ts vs claim_verdicts.partial_approval_channel）** — 逐条完全一致
- warnings/unbound 非空→None；schema/layout 不过→None；claim_checks 空或 id 重复→None；无 partial→None；存在非 supported/partial→None。五条规则两实现逐字对齐，无漂移。
- checks 为空→None 语义：edit 候选 blocked+checks 空→channel=None→分支2 不进入→else 拒绝，合理（无 partial 可核准，blocked 源于结构/关系而非 partial）。split ready 候选 can_commit=True→分支1 原路（不查 channel）。✓
- 前端 `partialChecks`（ValidationPanel.vue:462-466）额外过滤 `locator_status==="located"`，后端 channel 不过滤——当前不引入漂移，因 invalid locator claim 的 semantic_status 恒为 `not_checked`（generate_service.py:251），故 partial 集必全 located，渲染集==放行集。依赖隐式不变量，见 O3。

**C. 核准清单精确相等（:634-644）** — 成立
- `unknown=sorted(approved-set(channel))` 非空→409 `unknown_or_not_partial`；`missing=[p for p in channel if p not in approved]` 非空→409 `missing_partial_approvals`；双向闭合。
- 全绿候选+approved 非空→分支1 409（:624），与 api.md"全绿携带核准=载荷矛盾拒绝"一致。
- 重复 id `["clm2","clm2"]`：`set()` 吸收→等价单条核准。与 confirm 先例双标，见 N2。

**D. mark_committed_tx from_status（change_repository.py:132-151 + generate_service.py:673-678）** — 成立且为必需改动
- 旧硬编码 `WHERE status='ready'` 会使 blocked 候选 commit 恒 rowcount=0→VersionConflict→**核准通道形同虚设**；现参数化 `from_status=change.status`（ready|blocked），CAS 带原值。
- 并发双 commit 竞态：两请求同读 blocked 候选→均过门→`commit_version` 同事务内 `_mark` 执行 `UPDATE ... WHERE status='blocked'`，赢家 rowcount=1，输家 rowcount=0→False→raise VersionConflict→回滚整个提交。推理正确。
- `mark_committed` 自管版不传 from_status→默认 "ready"（:130），仅 test_change_repository.py 调用，ready→committed 语义不变。✓

**E. CLI（cli/app.py:22, 35-38）** — 成立
- 空串 `""`→split→`[""]`→strip 过滤→`[]`；`"clm1, clm2"`→`["clm1","clm2"]` 空格容错。✓
- getattr 双重冗余见 O5。

**F. 前端门与幂等（ReviewPage.vue:135-140,166-176,235 + idempotency.ts:59-66）** — 成立
- `canApply` blocked 分支=`allPartialsApproved`（channel 非空且每个 id 均在 approved），approved⊆channel（toggleApprove 只 toggle partialChecks==channel）→等价于服务器"精确相等"。前后端门同规则。
- commitKey 并入 approved（sort().join）与"409 不消耗键"**不冲突**：门拒绝发生在 commit_version 事务之前（:621-652 早于 :680），409 不落版本/占位，同键重放=重新执行；补核准改变 approved→改变键=新意图，二者正交。推演：409 后改勾选→新键→重新执行（正确，本就是新意图）；409 后不改勾选重试→同键→因未落占位重新执行（正确，按当前数据重判）。
- 换候选清核准/同候选重读保留：load 内 `if(change.value?.id!==ch.id) approvedPartials=[]`（:235）置于 epoch 检查（:233）之后，仅最新 load 生效；watch(changeId)→load 驱动。竞态安全。
- ValidationPanel `approvable?/approved?` 可选；`approvalOpen=status==="blocked" AND approvable?.length>0` 双条件，非 blocked 视图（ready 候选 channel=None）不渲染核准区。✓

**G. 契约四文档一致性** — 字段定义一致
- api.md:51 描述、models.schema.json:1375-1383、openapi.json:3785-3793、`CommitRequest.approved_partial_claim_ids: list[ShortId] max_length=16`、samples.py 第二样本：items `minLength1/maxLength128`==ShortId(max128)，`maxItems16`==pydantic `max_length=16`，required 数组三处均不含新字段（可选，default 空）。四文档对齐。
- ADR-12 **仅动 partial 一维**核对：channel 对 warnings(含 missing_evidence,generate_service.py:290)/unbound/schema/layout/非(supported|partial) 逐维拦截，invalid/not_checked/unsupported/conflict/missing_evidence/unbound 一律不放宽；与 AGENT_00:18"P0 保守非空 blocked，修改策略须写 ADR"一致，ADR-12 即该 ADR，docs/04 gate 段修订已显式声明覆盖原"存在 partial 则不准应用"。✓
- 16 上限文档缺口见 O2；CHANGELOG/process 见 O6。

**H. 测试质量（test_generate_service.py:613-350 新增 7 条）** — 断言无放宽、构造真实
- `_mixed_verdicts`+`multi_proposal(2页)`+`plan_slides(2)` 真实产出 blocked partial-only 候选（clm1 supported+clm2 partial→can_commit False→blocked→channel=[clm2]）。
- 正向 commit 验证 from_status=blocked CAS（:248）；漏核准/夹带核准/unsupported/missing_evidence/全绿夹带/结构重算篡改 6 条反例均 raises ChangeNotCommittable，部分断言 details 键。`test_structural_recheck_not_bypassed_by_approval` 证核准只过报告门、:653 结构重算原样生效。无降低断言、无跳过。
- 遗漏场景见 N1、O4。

---

## 二、发现清单

### B1（阻塞·提交完整性）approvalChannel.ts 未纳入待审 diff，但 ReviewPage.vue 已 import
- 位置：`frontend/src/pages/ReviewPage.vue:21` `import { partialApprovalChannel } from "../utils/approvalChannel"`；目标文件 `frontend/src/utils/approvalChannel.ts` 为 **git untracked（`??`）**，**不在** `/tmp/t14-adr12.diff` 内。
- 问题：待审 diff 作为提交单元不自洽——若严格按此 diff 提交，`approvalChannel.ts` 缺失，前端 `typecheck/build` 与运行时 import 均断裂（process.md 门禁含 frontend build 绿）。
- 已核对：小岳额外实读该文件，五条规则与后端 `partial_approval_channel` 逐条一致（见 B 项），**功能本身无缺陷**；B 仅指提交集/diff 完整性。
- 建议：将 `approvalChannel.ts` 纳入提交集（`git add` 后重生成 diff 或确认提交含之），确保 diff 自洽可独立构建。

### N1（需修复·契约边界）approved_partial_claim_ids 上限 16 与 claim_checks 上限 96 不对称，合法大 partial 集候选死锁
- 位置：`models/changes.py:44` `Field(default_factory=list, max_length=16)`；`contracts/models.schema.json:1382`/`openapi.json:3792` `maxItems:16`；对照 `ValidationReport.claim_checks max_length=96`（changes.py:14）与 `generate_service.py:350 claim_checks[:96]`。
- 问题：`partial_approval_channel` 返回的 partial 清单长度仅受 claim_checks(≤96) 约束，可达 17~96。当某候选 partial 数 >16 时：教师全勾→前端发送 >16 个 id（ReviewPage.vue:166-172 发 `approvalChannel` 全集）→ pydantic 在**请求解析阶段 422 VALIDATION_ERROR**（载荷超限），而非可解释的"通道不支持"；若限制在 ≤16 则 `missing_partial_approvals` 恒非空→409。两条路都走不通→该 blocked 候选**永远无法经核准通道提交**，且 422 错误归因误导（教师看不到"格式错"的真实原因）。
- 评估：T14 真实链 33~37 claims 稳定 1~2 partial，触发概率低；但契约上限不对称是**合法输入被拒之门外**的真实缺陷，属契约级变更应闭合的边界，非"最小修复"可豁免。
- 建议（二选一使边界自洽）：①将 `approved_partial_claim_ids` 上限对齐 `claim_checks`（max_length=96 / maxItems:96），与 ADR/api.md 同步；②或在 `partial_approval_channel` 显式 `if len(partials)>16: return None`（通道对超大 partial 集关闭，候选维持 blocked 并给可解释原因），同时 api.md/ADR 声明该上限依据。当前"pydantic 16 + channel 无上限"两头不对齐是根因。

### N2（需修复·契约一致性/集合语义双标）重复核准 id 被服务层静默吸收，与 confirm 集合语义"重复→422"先例不一致
- 位置：`generate_service.py:634` `approved = set(request.approved_partial_claim_ids)`（重复被吸收→`["clm2","clm2"]` 等价 `["clm2"]`）；`CommitRequest.approved_partial_claim_ids` 无 unique 约束（changes.py:44 无 validator、schema/openapi 无 uniqueItems）。
- 先例对照：`ConfirmPlanRequest._goal_indices_are_sets`（plan.py:54-61）对 `accepted_goal_indices`/`slide.goal_indices` 重复 `raise ValueError`→422；schema `uniqueItems:true`（models.schema.json:964）；api.md:6-7 明文"均为集合语义，重复索引返回 422 VALIDATION_ERROR"。
- 问题：同为"教师逐条确认的集合语义 id 清单"，confirm 入口强制 unique 拒重复，partial 核准入口静默吸收——契约双标，违反 AGENTS.md"复用现有为荣""避免创建看似成功但关系不一致的数据"。吸收本身不引入未审内容（功能安全），但行为未文档化且与既有先例分叉。
- 建议：与 confirm 对齐——`CommitRequest.approved_partial_claim_ids` 加 pydantic unique 校验（field/model validator）+ schema/openapi `uniqueItems:true`，使重复→422 VALIDATION_ERROR；服务层 `set()` 保留作纵深防御即可。若团队明确接受"核准集重复吸收=等价单条"，则须在 api.md/ADR 显式声明该语义（当前完全未提），否则视为缺陷。（注：前端 toggleApprove 用 includes 判重不会产生重复，CLI `--approve-partial "clm2,clm2"` 会，入口校验可一并挡住手误。）

### O1（非阻塞·语义健壮性）applyChange 发送 approvalChannel 全集而非教师勾选集
- 位置：`ReviewPage.vue:166-167` `const approved = ch.status==="blocked" ? [...(approvalChannel.value ?? [])] : []`。
- 问题：载荷与 commitKey 用的是**服务器派生 partial 全集**，非 `approvedPartials`（教师实际勾选）。当前 `canApply`（:140）要求 allPartialsApproved 才启用按钮，能发时两者相等，**功能正确、无未审放行**；但语义上"用服务器集替代教师逐条意图"，与 ADR-12"核准集并入键=补核准新意图"存在张力（前端只在勾全时发，键恒=全集，并入效果被弱化）。若未来 canApply 门放宽，发全集会替教师核准未勾项。
- 建议：发送 `approvedPartials`（教师勾选集）而非 `approvalChannel`，忠实表达逐条意图并让键真正反映勾选变化。

### O2（非阻塞·文档）16 上限依据未写入 ADR/api.md
- 位置：`docs/16` ADR-12 文本、`api.md:51` 均未提 `maxItems/max_length=16`；仅 schema/openapi/pydantic 有。
- 建议：随 N1 修复一并说明上限取值依据（与 claim_checks 对齐或通道关闭阈值），避免读者以为 16 是随意数。

### O3（非阻塞·防漂移注释）渲染集与放行集对齐依赖隐式不变量
- 位置：`ValidationPanel.vue:462-466` partialChecks 过滤 `located` vs `claim_verdicts.py:103-104` channel 不过滤；不变量源 `generate_service.py:251`（invalid→`not_checked`）。
- 建议：在 partial_approval_channel 或前端注释固化"invalid locator claim 恒 not_checked，故 partial 集必全 located"不变量，防未来允许 invalid 携带 partial 语义时前端隐藏该条→教师无法核准→死锁。

### O4（非阻塞·测试覆盖）缺以下场景测试
- `test_all_supported_with_stray_approval_rejected`（:322）仅 assert raises，未断言 details.reason/`unknown_or_not_partial`，无法防"实现改错原因仍过测试"（对照 test_missing/test_approving 已断言 details，应统一）。
- 缺：重复核准 id（呼应 N2）、并发 blocked 双 commit CAS(from_status=blocked 输家回滚)、committed/discarded 带核准走 else、edit 候选 blocked+checks 空走 else。
- 建议：至少补并发 blocked CAS 与重复 id 两条红测，锁死 D/N2 行为。

### O5（非阻塞·CLI 冗余）
- 位置：`cli/app.py:22` `str(getattr(ns,"approve_partial",""))`。argparse 已注册该参数且 `default=""`（:36），ns 必有该属性且为 str，`getattr` 默认值与 `str()` 均冗余。
- 建议：简化为 `ns.approve_partial.split(",")`（保留 strip 过滤）。无害，可顺手。

### O6（非阻塞·文档同步）process.md 未记 ADR-12
- 位置：diff 不含 `process.md`/`CHANGELOG.md` 更新；`CHANGELOG.md` 现状仅 1.0.0 一条（项目惯例逐任务记于 process.md）。
- 建议：按 AGENTS.md §5"契约/字段改变与代码同一次提交更新文档、每轮更新 process.md"，在 process.md 当前任务/已完成节补 ADR-12 条目（门语义变更、from_status CAS、前后端通道、四文档同步、T14 背景数据）。CHANGELOG 是否记按项目惯例（仅大版本）可不动，但 process.md 应补。

### O7（非阻塞·形状一致）分支1 与分支2 的 unknown_or_not_partial 载荷形状不一致
- 位置：`generate_service.py:628`（分支1 直接给原始 `request.approved_partial_claim_ids`，未排序/去重）vs `:635-638`（分支2 给 `sorted(approved-set(channel))`）。
- 建议：统一为 sorted list，便于前端/日志按同一形状消费。小瑕疵。

---

## 三、修复优先级

1. 提交前必改：B1（纳入 approvalChannel.ts）、N1（上限对齐或通道关闭+文档）、N2（unique 校验或显式声明吸收语义）。
2. 建议同轮带：O2（随 N1）、O6（process.md 同步，AGENTS.md §5 硬要求）。
3. backlog：O1、O3、O4、O5、O7。

核心门语义、CAS 原子性、前后端放行规则一致性、保守维度不放宽、四文档字段一致性均经实读核对成立，方向正确；上述 B/N 为边界闭合与提交完整性问题，修复后即可提交。
