# T12 后端（restores + edits）独立 Review 记录

日期：2026-09-21；审查对象：T12 loop②③④ 未提交 diff（restores 段已先行提交 47291d7，本轮审 edits 全量后端 diff）。

**执行模型声明：两轮审查均由 Task 子代理干净会话执行，实际运行模型 huaweicloud/qwen3.8-flash（Reviewer 首行自证）。**

## 首轮审查发现与处置

| 级别 | 发现 | 处置 |
|---|---|---|
| B1 | edits 写候选前缺 guard_writable（Q08 同规则）：取消/deadline 落在"最后核验完成→写库"窗口会留 ready 孤儿候选（worker publish 只收口 job 不回滚候选） | 模型路径写库前加 guard_writable；确定性路径加 get_execution_state 实况复查；红测=verify 出队回调置取消位→JobCancelled→changes 零行。闭环 |
| N1 | 模型产出 reorder 时 affected_slide_ids 恒空（内容不变→changed 为空），与确定性路径口径不一致误导审阅 | affected 并入 moved_slide_ids 位置比较去重；红测 reorder 全移动页入 affected。闭环 |
| N2 | 模型按"未变可复用其 id"回写既有 claim 时，其 chunk 不在本批允许集合→误判 locator 失败→假 blocked | _resolve_patch_claims 对同 id 且 text/kind 一致条目权威复用跳过 locator；绕过核对：同 id 异内容仍被引擎 _merge_claims 拒绝或 locator 拦截，无静默放行。闭环 |
| N3 | split 超 DeckSpec 上限时 DeckSpec.model_validate 抛 ValidationError 冒泡成 INTERNAL_ERROR | try/except→ModelOutputInvalid（typed 收口）；补溢出红测。闭环 |
| N4 | EDIT_CALL_BUDGET=6 按"实际 HTTP 请求"口径最坏误伤（3 逻辑调用×(1+重试+修复)=9） | 上调至 9，注释写明口径。闭环 |
| N5 | wiring edit_handler 预注入 provider 时 model_id 丢失（与 generate_handler 口径不一致） | 改经 provider_factory 同源解析（provider 与 model_id 一次取出）；确定性路径惰性不触发。闭环 |
| Q1 | 模型路径产出 reorder 是否有意允许 | 是：api.md:55"重新排序可走同一路径"为允许项，自由文本 reorder 经模型属设计内；N1 修复后 affected 正确上报。确认非偏移 |

## 轻量复审（修复 diff 单独送审，同模型标注）

六项修复逐项判定**闭环**；定向测试 49 passed。新增两项 N 级当场处理：
- N6：确定性路径无 deadline 检查点属成本语义豁免（deadline=模型预算，无模型调用无成本可保护；版本一致性由 handle_edit 入口 CAS 复查兜底）——修复声明中"publish 收口 deadline"论据与代码不符，注释已按事实改正。
- N7：N3 缺结构溢出红测——已补（16 页 deck split→ModelOutputInvalid）。

## 总体判定

放行。三分流（EDIT_UNSUPPORTED/INSUFFICIENT_EVIDENCE/模型错误 failed）、非目标页构造性不变、T09 可信链复用等价性（claim_verdicts 迁移逐条比对）均获审查背书；generate 侧重构无回归（全量 615 collected exit 0、validate 23/23）。

## 未做/边界（如实声明）

- 真实模型 edit 链路 NOT_RUN（本轮无模型调用授权，归 T14 黄金链）。
- 前端消费（编辑输入/移动按钮发结构化指令/恢复按钮+acknowledged 确认/候选 kind=edit 审阅）= loop⑤。
- edits 的 blocked 候选（引用定位失败等）浏览器五态验证随 loop⑤ 一并做。
