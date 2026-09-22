# 工作流与实际 CLI 契约（已实现，T13）

入口：`python -m courseware_core.cli`（PYTHONPATH 指向仓库 backend/src，
解释器用仓库锁定 venv）。CLI 与 Web 使用同一套 service、worker、验证门与
Schema——命令只是第二入口，不是平行实现。

输出信封：stdout 恒为单个 JSON
`{"ok": bool, "command": str, "payload": {...}}`；
失败时 `payload.error = {code, message, request_id, details}`（api.md 形状，
错误码复用，不造 CLI 私有语义）。
退出码：0 成功；1 业务拒绝（含 job blocked/failed，根因在 payload.error）；
2 用法错误（参数/请求文档非法，code=USAGE_ERROR）；
3 数据目录被占用（code=WORKER_ALREADY_RUNNING）；4 内部错误。

data-dir：Skill 独立演示目录（`--data-dir DIR` 或环境变量 `CC_DATA_DIR`），
布局 `app.db + materials/ + artifacts/ (+ exports/)`。CLI 与 Web worker 抢
同一把 flock 独占锁——把 CLI 指向运行中 Web 服务的目录会立即得到
WORKER_ALREADY_RUNNING，不存在绕过服务边界改同一 SQLite 的窗口。

命令（`--data-dir` 除 doctor 外均必填）：

- `doctor`：环境自检（依赖可用性、APP_LLM_* 是否配置——只报布尔与模型名，
  绝不输出 Key；带 `--data-dir` 时探测锁状态 available/held）。
- `project create --request FILE`：CreateProjectRequest JSON → Project。
- `material add --project ID --file FILE`：真实 PDF 解析 job（内联执行到
  终态）；同内容重传返回 duplicate=true 零新 job。
- `plan create --project ID --corpus-revision N`：计划 job → LessonPlan
  （含服务端覆盖判定；全目标 unsupported=blocked+INSUFFICIENT_EVIDENCE，
  不烧模型调用）。
- `plan confirm --project ID --plan ID --corpus-revision N [--request FILE]`：
  教师明确同意后调用；缺省=按服务器计划原样确认，`--request FILE` 提交
  教师调整版（slides/accepted_goal_indices）。
- `deck generate --project ID --plan ID --base-version N --corpus-revision N`：
  候选生成 job → CandidateChange（ready/blocked 由验证门决定，blocked 附
  报告，不盖绿）。
- `change show --project ID --change ID`：候选 diff 与核验报告。
- `change commit --project ID --change ID --base-version N --corpus-revision N`：
  教师同意才应用；blocked/结构不过/版本漂移一律拒绝。
- `deck show --project ID [--version N]`：正式版本 DeckSpec（构造 reorder
  前的稳定 slide id 来源）。
- `deck edit --project ID --request FILE`：EditRequest JSON；自由文本走
  模型路径（受云处理告知门），结构化 `{"action":"reorder","slide_ids":[...]}`
  为确定性路径（零模型调用）。
- `deck restore --project ID --request FILE`：RestoreRequest JSON →
  新版本（restored_from 溯源，历史不可变）。
- `deck export --project ID --version N [--out-dir DIR]`：只读快照渲染 job →
  复制 `courseware-vN.pptx` 与 `evidence-report-vN.json` 到 out-dir
  （默认 data-dir/exports），附 artifact id 与 sha256；损坏版本显式
  EXPORT_FAILED 拒绝，不静默任选。

job 类命令（material/plan/generate/edit/export）在 CLI 进程内临时启动与
Web 完全同一个 JobWorker（锁、启动恢复、GC、CAS 领取、发布复核全复用），
等待本命令 job 到达终态后退出；worker 会顺带领取该 data-dir 中的积压
queued job（与 Web 启动语义一致）。

注意：所有命令（含 `change show`/`deck show` 等只读命令）都会在独占锁下
先执行启动恢复（遗留 running→interrupted 并释放项目写锁）——读命令也会
写库，这是防上次进程崩溃把项目永久卡在 PROJECT_BUSY 的有意语义。
`plan confirm` 的 `--corpus-revision` 与 `--request` 文件内值冲突时显式
拒绝（USAGE_ERROR），不静默任胜。
