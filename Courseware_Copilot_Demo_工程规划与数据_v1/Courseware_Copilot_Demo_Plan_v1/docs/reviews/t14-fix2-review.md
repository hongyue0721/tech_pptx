# T14-fix2 轻量复审（干净会话，仅审修复闭环 diff）

- **执行模型**：本会话实际加载 model id 为 `tierflow/Qwen3.8-Flash`（Qwen3.8-Flash 同源）。按"以诚实无知为荣"如实标注，不照抄首审的 `aliyun/qwen3.8-flash` provider 串、不冒充未运行的 provider。
- **待审范围**：/tmp/t14-fix2.diff（634 行，含首审前部分）。本次**只审首审后新增闭环部分**（B1/N1/N2/content-v5 封口 + 对应红测）；`generate_service.py` 的 `_required_audit_ids` 域过滤、audit sorted 序属首审 C/O 轴已审内容，不重复判定。
- **审查时间**：2026-09-22
- **核对方式**：逐项读实际文件 + 复跑定向测试（退出码判定），不轻信描述。

---

## 结论先行

**放行提交。** B1 三处修复真实落地且逻辑闭合，集合真值在 CAS / CLI 回灌 / Web 读侧 / 模型规范形四处口径统一（均 `sorted(set())`），且 `slides` 保持 list 严格未引入新误放行面；三条红测断言均可红于旧实现（CLI 例、CAS 重放例、content 封口例），守卫例诚实为"防过度放行"非红-on-old；N1/N2/O 封口均与声称一致；定向测试复跑 EXIT=0。无阻塞项。

---

## 逐项判定

### 1. B1 三处修复落地与逻辑闭合 — PASS
- **规范形单源**：`models/plan.py:9-13` `normalize_goal_indices = sorted(set(indices))` 纯函数，读侧/回灌侧共用。✓
- **CAS 集合比较**：`services/plan_service.py:314-319` — `request.slides == plan.slides`（list 严格，顺序=教师演示意图）**AND** `set(request.accepted_goal_indices) == set(plan.accepted_goal_indices)`。✓
- **CLI 回灌归一**：`cli/app.py:43` 导入 `normalize_goal_indices`；`:192-205` 缺省"按原样确认"分支对 `accepted_goal_indices` 与每页 `slides[i].goal_indices`（经 `model_copy(update=...)`）**双侧归一**后再构造 `ConfirmPlanRequest`。脏存储 `[0,0]`→`[0]`，不再构造期抛未捕获 `ValidationError`。✓
- **新误放行面核查（清单1 关键）**：accepted 同集合但 slides 异 → `request.slides == plan.slides` 为 False → 整体条件 False → 仍 `raise ValidationFailed`（`:320`）。accepted 异集合 → set 不等 → 拒。唯一放宽是 accepted"顺序不同/历史重复但同集合"按重放返回，正是"业务真值=集合"的意图（accept 范围是无序集合，非序列），与 `slides` 有序教学语义区分得当，符合首审 B1 建议。**未引入放行漏洞。**✓
- **跨面口径统一**：Web 读侧 `useOutlineFlow.ts:70` `[...new Set(...)].sort` 与后端 `sorted(set())` 一致，杜绝首审"Web 归一、CLI 崩溃"双标。✓

### 2. 红测三例真红-on-old（清单2）— PASS
- **例1（CAS 重放）** `test_plan_service.py::TestConfirmPlan::test_confirm_replay_on_dirty_confirmed_plan_uses_set_semantics`：先干净 confirm（落库 accepted=[0]），再 `UPDATE plan_json` 把 accepted 改脏为 [0,0] 构造脏 confirmed，用干净 request 重放断言 `status=="confirmed"`。旧实现 list 相等 `[0]==[0,0]` False → 抛 `ValidationFailed` → **必红**；新实现 set 相等 → 重放返回 → 绿。✓
- **例2（守卫）** `...test_confirm_replay_still_rejects_different_slides`：同 accepted、`model_copy` 改 slides title → 断言 `pytest.raises(ValidationFailed)`。新实现 slides list 不等 → 拒。✓ 此例新旧皆绿，属"防 set 比较过度放行"的**守卫断言**，非红-on-old，与任务书"守卫"措辞一致，无夸大。✓
- **例3（CLI 原样确认）** `test_cli_errors.py::test_plan_confirm_as_is_normalizes_dirty_stored_indices`：DB 注入脏 draft（accepted=[0,0]、slide goal_indices=[0,0]），`run_cli plan confirm` 原样确认，断言 `rc==0`、落库 `accepted==[0]`、`slides[0].goal_indices==[0]`。旧实现把 `[0,0]` 直喂 `ConfirmPlanRequest` → validator 抛未捕获 `ValidationError` → CLI 崩 → **必红**；新实现回灌归一 → 绿。✓
- **DB 构造核 rowcount**：`test_cli_errors` INSERT 后 `assert cur.rowcount == 1`；`test_plan_service` UPDATE 后 `assert cur.rowcount == 1`。两处脏数据注入均校验，避免"静默注入失败致测试空过"。✓
- **复跑证据**：`PYTHONPATH=src .venv/bin/python -m pytest <上述节点 + TestConfirmRequestSetInvariants + test_app_prompts_content.py> -q` → **14 passed，EXIT=0**。✓

### 3. N2 焦点还原实现（清单3）— PASS
- `useOutlineFlow.ts`：`toggleGoal` 改签名去掉 `checked` 入参，以 `isGoalAccepted(goalIndex)` 派生当前态（单一事实源，不信任事件携带的 DOM checked）；两条拒绝分支（不可接受 `:537`、blockers 命中 `:547`）`goalToggleEpoch.value += 1`；正常勾选/取消不增 epoch。✓
- `OutlinePage.vue:63-71`：`onGoalToggle` 先记 `goalFocusIndex = goalIndex` 再调 `toggleGoal`；`watch(goalToggleEpoch, async)` 默认**非 immediate**，仅 epoch 值变化时触发，`nextTick` 后 `querySelector('.goal-list input[data-goal-index="..."]')?.focus()`。✓
- **watch 触发面**：`goalToggleEpoch` 仅在 `toggleGoal` 内 +1，而 `toggleGoal` 仅由 `@change="onGoalToggle"` 驱动 → epoch 变化必伴随一次 `onGoalToggle` 先赋值 `goalFocusIndex` → 无"epoch 变但焦点索引陈旧"错焦。✓
- **正常勾选焦点天然保持**：勾选/取消成功路径 epoch 不变 → `:key` 不变 → Vue 不重建 `<input>` → 焦点原地保持，watch 不触发。✓
- **goalFocusIndex 生命周期**：组件 `setup` 作用域 `let`，随组件卸载回收；`watch` 在 `setup` 顶层注册，Vue 3 自动随 scope 销毁停止，**无 watch/焦点监听泄漏**。✓（轻微冗余：焦点还原后未将 `goalFocusIndex` 复位为 null、watch 内 `null` 守卫在当前调用链几乎不可达——属无害纵深防御，不影响正确性，见"附观察"。）
- **选择器有效性**：`OutlinePage.vue:197` 确为 `<ul class="goal-list">` 包裹 goal input，`:data-goal-index` 已绑定（diff `:603`），选择器命中。✓

### 4. N1 openapi.json 仅加 uniqueItems 无漂移（清单4）— PASS
- `contracts/openapi.json:3365-3374`：`ConfirmPlanRequest.accepted_goal_indices` 在 `minItems:1/maxItems:8` 后新增 `"uniqueItems": true`，归属正确（同块 `required` 含 `acknowledged`，非 LessonPlan/PlanSlide）。✓
- `contracts/models.schema.json:955-964`：同字段同位置 `uniqueItems:true`，两契约对齐。✓
- `git diff --stat`：openapi.json 与 models.schema.json 各 `3 +-`（1 删逗号行 + 2 增），仅此一处，**无其他字段/路由漂移**。✓
- 与首审 N1 附带确认一致：`PlanSlide.goal_indices` 维持不加 `uniqueItems`（Pydantic 严于 Schema，方向2 允许口径），未误改。✓

### 5. content-v5 封口句与锁测字面量一致（清单5）— PASS
- `app-prompts/content.md:1` 版本 `v4→v5`；正文含封口句"…**确需写入却没有支持时仍必须上报，不得为过核验门而隐瞒**"。✓
- `test_app_prompts_content.py::test_content_prompt_defines_missing_evidence_scope` 断言 `"仍必须上报" in body and "隐瞒" in body`，字面与 prompt 一致；版本锁 `test_content_prompt_version_bumped` 收紧为 `content-v5`。封口句为 v4 所无 → 锁测红-on-old，属真回归锁，无断言放宽。✓

### 6. 门禁证据（清单6）— PASS
- 定向测试复跑 EXIT=0（见项2）。全量按任务书不重跑，采信声称（pytest 692 exit 0 / typecheck·build 0 / validate 23/23）；`validation-report.{json,md}` diff 仅刷新 `generated_at` 时间戳，passed=23/failed=0 未变。✓

### 7. 首审执行模型标注留痕（清单7）— PASS
- `docs/reviews/t14-fix1-review.md:3-4`：如实标注实际 model id `aliyun/qwen3.8-flash`，并明示"任务书预期 huaweicloud 但本会话实际为 aliyun，同源不同 provider，不冒充未运行的 provider"。留痕诚实，无冒充。✓

---

## 附观察（不阻塞，进 backlog 即可）

- **O-A**：N2 的 `goalFocusIndex` 焦点还原后不复位、watch 内 `null` 守卫在当前调用链不可达——无害冗余防御。可加一行注释说明"null 分支为旁路兜底"，避免后续维护者误判可达性（与首审 O1 同类）。
- **O-B**：O 封口三项（toggleGoal disabled 死代码分支、audit sorted 序、verify 喂豁免页可见文字）本次 `generate_messages.py`/`useOutlineFlow` 未触（`git status` 无 `generate_messages.py M`），与"进 backlog 不修"声称一致，未见偷偷扩大或缩小改动面。✓

---

## 复审轴小结

| 项 | 判定 | 关键证据 |
|----|------|----------|
| 1 B1 落地+闭合 | PASS | plan.py:9-13 / plan_service.py:314-319 / cli/app.py:43,192-205 |
| 2 红测真红+rowcount | PASS | 三例逻辑推演 + 定向 EXIT=0 + 两处 rowcount==1 |
| 3 N2 焦点 | PASS | useOutlineFlow.ts:537,547 / OutlinePage.vue:63-71,197 |
| 4 N1 openapi | PASS | openapi.json:3365-3374 / models.schema.json:955-964 |
| 5 content-v5 封口 | PASS | content.md:1 + 锁测断言字面一致 |
| 6 门禁证据 | PASS | 定向复跑 EXIT=0 |
| 7 执行模型留痕 | PASS | t14-fix1-review.md:3-4 |

**最终结论：放行提交。**
