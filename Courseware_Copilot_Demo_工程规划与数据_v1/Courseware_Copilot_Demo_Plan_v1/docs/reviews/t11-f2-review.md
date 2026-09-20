# T11-F2 独立 Review 记录（2026-09-20）

- 审查方式：干净会话子代理（只读），审工作区 diff（含 5 个新文件全文）+ 契约真源（AGENT_01_FRONTEND F2 节、api.md 错误码/幂等节、docs/09、models.schema.json、后端 plan_service/idempotency_service 实际行为）。
- 基线：cc59a90（F1 提交）之上的未提交工作区改动。
- 结论：3 阻塞 + 7 非阻塞；主链诚实度（无伪成功、confirm→generate 串行、类型对齐、无 mock/localStorage）CLOSED。

## 阻塞项与闭环

| # | 问题 | 闭环 |
|---|---|---|
| B1 | 轮询 404/401 异常停止不通知消费者：generating 永久 true 卡"生成中"，且"正在自动重试"文案与已停止事实相反 | useJobPolling 增加 onHalted 回调；useMaterialIntake/useOutlineFlow 复位 generating 并如实显示停止原因；statusText 的"自动重试"分支加 isPolling 条件 |
| B2 | attempt 只存内存，刷新后归零 → 首击撞旧幂等键重放旧 failed job，违背"终态后新意图换键"承诺 | 语义重构：attempt 由 URL query `pa` 承载（与"URL 存精确定位"设计一致）；job 终态即"该键意图已消费"attempt+1 并写回 URL；受理前抛错（结果未知）不走终态路径=同键恢复承诺保持。浏览器实测：重放旧 job→pa 前进→再击新 job→刷新→点击仍新 job（非重放） |
| B3 | 上传在飞时跨项目切换：epoch 失配路径跳过 uploading 复位 → 永久死锁；旧项目队列项残留污染新项目 | restoreJob 开头复位 uploading、在途项（uploading/parsing）降级回 pending（File 仍在本地，键含 projectId 不与旧项目互撞） |

## 非阻塞项处置（全部当场闭环，无推迟）

- N1 tick 对 AbortError 直接 return，不再瞬写 pollError（visibility 补拉闪现"读取失败"）。
- N2 PAYLOAD_TOO_LARGE 文案改为"文件数量或大小超出限制"（后端对超份数也复用此码）。
- N3 toggleGoal 取消引用的预检去掉 title 豁免——后端 outside 检查覆盖全部 slides，豁免会换来 422，预检必须同口径。
- N4 OutlinePage 主按钮 disabled 逐项给出原因 title（stale/busy/未勾选审阅/零接受目标）。
- N5 Material.pdf_pages/usable_pages 契约实为 nullable（$defs 核对 anyOf null）：models.ts 类型对齐 `number | null`，模板 null 显示"—"；enqueueFiles 入队即按剩余额度（服务器已入库+本地在队）截断并提示。
- N6 failed 队列项不再阻断"生成大纲"（服务器语义：失败资料不阻碍 plan），阻断条件改为仅 pending/uploading/parsing 在途项。
- N7 process.md "36 码"更正为 35（与 ERROR_COPY 逐码核对）。

## Reviewer 确认 CLOSED 的检查项

a 伪成功/假状态、e confirm→generations 严格串行（confirm 失败 return 注释与实现一致；blocked 候选如实跳审阅）、g 契约类型逐字段对齐（除 N5 一处，已修）、h 无硬编码演示数据/localStorage、i Vue 响应性（深拷贝隔离编辑、ref 解包、Set 拷贝）。

## 留痕

- 修复后复验：typecheck/build 退出码 0；后端 pytest 524 不回归（本轮零后端改动）；validate_pack 23/23。
- B2 场景浏览器实测链：点击→202 重放原 job（log job_61d8）→footer 如实显示旧失败→pa=1→再击→新 job_52f9→终态 pa=2→reload→再击→新 job_84670f→pa=3。"结果未知同键恢复"由 POST 抛错路径保证（不走 handleSettled，attempt 不动）。
