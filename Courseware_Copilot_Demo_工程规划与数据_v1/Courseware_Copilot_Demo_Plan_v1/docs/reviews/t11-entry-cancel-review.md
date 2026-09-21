# T11 收尾轮（D-04 兼容入口 + D-06 cancel UI）独立 Review 记录（2026-09-21）

- 执行模型：**huaweicloud/qwen3.8-flash**（Task 子代理干净会话，继承主会话模型，显式标注）。
- 审查对象：本轮未提交 diff（useJobPolling cancel 状态机、useMaterialIntake generate 终态跳转+暴露、useOutlineFlow 暴露、两页取消按钮、router+WorkspaceEntry、docs/09 同步）。
- 契约对照：API_UI_MATRIX cancel/兼容入口行、AGENT_01 F3"取消"、api.md cancel=200 协作式、后端 routes_jobs/job_service/job_repository 实际实现。
- 结论：**1 阻塞 + 2 非阻塞**；A cancel 语义、C generate 跳转一致性、D 按钮呈现、E 回归、F 诚实边界 CLOSED。

## 阻塞与闭环

| # | 问题 | 闭环 |
|---|---|---|
| B1 | 恢复路径（URL/服务器 active job）下 parse job 终态只清 URL 不 `loadMaterials()`——刷新时首读拿到 parsing 旧态，轮询到终态后列表永远"解析中"（plan/generate 分支离开页面不受影响，唯 parse 留本页）。正常上传路径由 runUploadLoop 兜底，恢复路径无此兜底，缺口真实 | parse 终态分支补 `await loadMaterials()`（幂等 GET+epoch 保护，正常路径多刷无害）。**浏览器实证**：构造可控时序（job 挂 running 使页面持续轮询→翻 DB 真值 material ready/succeeded→轮询捕获终态）→ 列表自动收敛"文本就绪"、URL job 清除 ✓（修复前同构造实测卡"解析中"） |

## 非阻塞与处置

- N1（已闭环）：docs/09 路由行与 §5 未反映兼容入口新分支与取消按钮 → 本轮已更新（兼容入口三分支 + cancel 语义段）。
- N2（真值纠偏+纪律再证）：Reviewer 指出"服务器过滤 ghost active_job_id"的代码依据不成立（GET project 直读 DB 行值）。**破案**：我此前构造 ghost 时 `PID=$(SELECT id FROM projects WHERE current_version=1)` 匹配到 2 行、多行变量代入 WHERE 致 **UPDATE 0 行生效**——ghost 从未写入，"服务器返回 null"是 DB 本来就是 null。教训：多行结果集严禁直接进变量；UPDATE 后必须 `SELECT changes()` 验证生效行数（本轮 B1 构造起已程序化核对）。前端行为不受影响：active_job_id 真值非空时留 materials、轮询 404 有诚实归宿。

## 诚实边界（PARTIAL 声明）

- cancel **API 层语义 live 实测 PASS**：上传 36 页 PDF→立即 POST cancel→200 Job（对已终态 job 原样返回、无害）；终态 job 幂等重放语义与后端 CAS 一致。
- cancel **UI 点击全链未 live**：parse job 实测 0.34s 完成（36 页），按钮窗口 <1s 人不可靠点击；requestCancel 状态机（isPolling 门、cancelling 复位、同键重试）经代码 Review CLOSED；**完整点击链留 T14 generate 黄金链（分钟级窗口）补验**——不声称已实测。
- 兼容入口 active_job_id 分支：真实 running job 窗口太短未 live 抓到；分支逻辑=两条件真值判断+404 归宿已 Review，B1 恢复链已实证。

## 修复后门禁

typecheck/build/pytest(534)/validate(23/23) 全 exit 0；B1 构造实验浏览器 PASS；构造数据（probe 项目 66d9fd0c、material/job 状态翻转）已恢复真值、active_job_id 清理核对 changes()=1。
