# 异步任务、原子提交与恢复

## 1. 持久化作业

jobs记录id、项目、kind、status、stage、输入revision、base_version、进度明细、request_id、结果引用、错误、创建/更新时间。status为queued/running/blocked/succeeded/failed/cancelled/interrupted；stage独立表示queued/parsing/retrieving/planning/generating/validating/rendering/exporting/previewing/finished。

百分比不伪造。已知分母时可显示“已核验8/12条事实”；未知时显示步骤文字。queued不是started，HTTP202不是任务成功。

FastAPI启动时创建单后台工作器，从SQLite领取queued job；SQLite事务完成领取。对已经running而所属进程不存在的job标interrupted，不自动重放可能收费的LLM调用。可以保留已完成阶段产物供人工重试，但P0不实现复杂断点续跑。

## 2. 幂等

所有创建/生成/编辑/提交/恢复/导出请求带Idempotency-Key。作用域是认证会话+项目+路由；存规范化请求hash和首次响应，保留24小时。相同key+相同请求返回相同对象/任务；同key不同请求返回409 IDEMPOTENCY_CONFLICT。

上传文件hash用来去重，不替代动作级幂等。前端网络超时重发同一key；用户明确再执行生成时用新key。前端不得在轮询失败时偷偷再POST任务。

## 3. 写入互斥

同项目同一时刻最多一个材料入库/计划/生成/修改/提交/恢复写任务。新写入冲突409 PROJECT_BUSY。导出读取不可变快照，可排队但不得读取一半修改中的对象。

每次生成/修改固定corpus_revision；上传新的成功材料会让旧计划过期。不能将旧计划悄悄用于新语料。项目当前资料revision与版本不一致时显示“资料已更新，需重新核验”，正式导出阻止。

## 4. 候选和提交

生成及AI编辑返回candidate_change_id和报告。教师查看候选后POST commit，服务端再次确认base_version与corpus_revision，并检查门禁。事务内分配vN+1并更新current_version。失败只丢弃候选，不影响当前可用版本。

渲染/导出发生在版本提交后；失败时可以从同一版本重新export，不重新调用模型、也不增加Deck版本。

## 5. 撤销与恢复

“撤销上一步”选定前一个已应用版本，通过restore生成新版本。例：v1→v2→撤销=v3（内容来自v1），不是删除v2或回到编号v1。对比时使用semantic_hash，忽略version/created_at等元数据。

## 6. 取消、失败、删除

取消queued job直接cancelled；running则置cancel_requested并由工作器在边界终止。子进程组由工作器管理，超时/取消清理派生进程；不要孤儿Chromium越积越多。

项目删除需确认且无活动任务；清理文件、数据库记录、临时缓存和导出文件。对外返回不透露其他用户项目存在与否。备份保留策略在隐私说明中写清，不宣称“立即从所有备份删除”。

## 7. 产物一致性

ArtifactManifest绑定project_id/version/corpus_revision、renderer_version、font_profile、sha256、size、mime、validation状态和来源类型。

所有预览路径和导出下载都带明确版本。旧版本预览不可用时显示状态，不用V1截图顶替V2。latest便利接口不进入P0，避免下载竞态。
