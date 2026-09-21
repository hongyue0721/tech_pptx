# api｜HTTP接口契约 v1.0.0

规范文件：`contracts/openapi.json`；数据类型：`contracts/models.schema.json`。本文件说明业务语义；三者和代码必须同次变更。路由实现状态以 `process.md` 当前记录为准：T04–T09 与 F00 只读接口（deck/evidence）已挂载；T12 restores 已挂载；previews/exports/artifacts/edits 仍为目标契约，未挂载前不对外提供。

## 通用约定

前缀 `/api/v1`；JSON UTF-8。时间为带时区的ISO8601 UTC。ID为不透明字符串，由服务端产生。成功响应直接返回类型化对象，不套模糊success/data多层。

受保护演示采用同源HTTPS与网关Basic Auth；本地模式只绑定127.0.0.1。公网无鉴权禁止启动。请求含 `X-Request-ID` 可回传，但服务器必须验证长度/字符；没有则生成。变更操作必须带 `Idempotency-Key`（1—128字符），作用域与行为见任务文档。受理型操作（202 JobAccepted）的幂等占位与业务资源同事务锚定：若"业务已提交、响应未缓存"时进程中断，同键同载荷重试返回 202 与原 `job_id`（找回，不重执行、不二次落 job）；占位无锚点且在飞窗口内返回 409 IDEMPOTENCY_CONFLICT（in flight）。

错误统一为 `{ "error": { "code": "...", "message": "...", "request_id": "...", "details": {} } }`。details不含Key、任意绝对路径或原始供应商敏感响应。422本地化字段错误；503仅服务不可用，不滥用500掩盖缺资料。

## 路由总表

| 方法/路径 | 输入 | 成功 | 语义 |
|---|---|---|---|
| GET /health | 无 | 200 Health | liveness，不调用LLM |
| POST /projects | CreateProjectRequest | 201 Project | 课程要求、隐私告知确认 |
| GET /projects/{project_id} | 路径 | 200 Project | 恢复状态、当前版本、活动任务 |
| DELETE /projects/{project_id} | ConfirmDeleteRequest | 204 | 无活动任务，删除私有项目 |
| POST /projects/{project_id}/materials | multipart file | 202 MaterialUploadAccepted | 单请求单PDF；前端逐个提交队列 |
| GET /projects/{project_id}/materials | 路径 | 200 MaterialList | 解析质量、物理页数、状态 |
| POST /projects/{project_id}/plans | PlanRequest | 202 JobAccepted | 绑定corpus_revision；生成待确认大纲 |
| GET /projects/{project_id}/plans/{plan_id} | 路径 | 200 LessonPlan | 查看大纲、coverage和缺口 |
| POST /projects/{project_id}/plans/{plan_id}/confirm | ConfirmPlanRequest | 200 LessonPlan | 接受可支持的目标；不掩盖缺口 |
| POST /projects/{project_id}/generations | GenerateRequest | 202 JobAccepted | 必须已确认计划；产出候选，不直接更新当前版本 |
| GET /jobs/{job_id} | 路径 | 200 Job | status与stage分开 |
| POST /jobs/{job_id}/cancel | 无 | 200 Job | 协作式取消 |
| GET /projects/{project_id}/deck | ?version=N | 200 DeckSpec | 缺省读当前版本；没有正式版本或version<1按"不存在"处理返回404 DECK_NOT_FOUND（不作422）|
| POST /projects/{project_id}/edits | EditRequest | 202 JobAccepted | 必带base_version/corpus_revision；输出候选 |
| GET /projects/{project_id}/changes/{change_id} | 路径 | 200 CandidateChange | 候选DeckSpec、差异、验证报告 |
| POST /projects/{project_id}/changes/{change_id}/commit | CommitRequest | 201 DeckVersion | 教师确认后原子应用 |
| POST /projects/{project_id}/restores | RestoreRequest | 201 DeckVersion | 从旧版本复制产生新版本 |
| GET /projects/{project_id}/evidence/{chunk_id} | ?corpus_revision=N | 200 DocumentChunk | 原文与页码；仅当前项目可读；chunk须落在所请求累积revision内，超前revision返回409 CORPUS_CHANGED |
| GET /projects/{project_id}/versions/{version}/previews | 路径 | 200 PreviewManifest | 每页类型与ready/failed，永不串版 |
| POST /projects/{project_id}/exports | ExportRequest | 202 JobAccepted | 固定version；纯渲染，不重新推理 |
| GET /projects/{project_id}/artifacts/{artifact_id}/download | 路径 | 200 binary | Content-Type、Content-Disposition、校验和 |

## 创建与资料

CreateProjectRequest包括CourseBrief（topic、audience、duration_minutes、goals、target_slides=8）和 `consent_to_cloud_processing`。云模型模式下未确认告知则拒绝进入推理；本地解析本身不需要外发。

上传用FormData字段 `file`。浏览器不要手动写multipart boundary。后端检查文件字节数、PDF结构、页数和抽取正文，不只信MIME/扩展名。前端支持多文件，逐个上传并等待解析/任务释放后发送下一项；不将AUpload认为现成批量上传引擎。

MaterialUploadAccepted返回material_id/job_id/duplicate；重复内容返回既有material，job_id可null，且不增加revision。无法提取文字的页返回质量警告；整文件无可用正文返回PDF_TEXT_UNAVAILABLE。加密文件返回PDF_ENCRYPTED，不尝试破解。

## 计划→生成→应用

PlanRequest含corpus_revision。ConfirmPlanRequest含corpus_revision和教师调整后的slides、accepted_goal_indices和acknowledged=true（可改标题/顺序/选范围），服务端重新检查引用与coverage；`status=confirmed`由服务端决定。

GenerateRequest必须含plan_id、corpus_revision、base_version（首轮为0）。成功job.result_ref指向change_id。教师从GET change查看结果，再发CommitRequest：base_version、corpus_revision、acknowledged=true。生成和应用分离是必要流程，不可省略。

## 编辑

EditRequest含instruction、target_slide_ids、base_version、corpus_revision。允许意图：精简、重述、拆页；重新排序可走同一路径的deterministic action，不能臆造新事实。模型内部输出DeckPatch，由后端应用到副本。

split_slide要给完整替换页内容，不是只写一个“split”操作名就算实现。非目标页的语义hash必须不变。不得修改未授权的claim：共享claim被重写需新ID，避免影响其他页。

不支持指令返回422 EDIT_UNSUPPORTED；资料不足job=blocked、code=INSUFFICIENT_EVIDENCE；模型/网络错误job=failed。两类不能混淆。

## 版本/导出

RestoreRequest：target_version、base_version、corpus_revision、acknowledged=true。返回新DeckVersion。P0仅允许同当前corpus_revision的恢复；旧语料版本返回409 CORPUS_CHANGED，需重新规划生成。不能恢复陈旧报告作为当前正确性证据。

ExportRequest：version、format="pptx"。正式版本未通过门禁或语料过期返回409/422，不偷偷降级到整页图片PPT。导出job终态返回artifact_id；下载有明确版本、文件hash和文件名；PPTX使用attachment，预览图可使用对应image/png或image/jpeg和受控inline，不能将任意上传内容按HTML执行。

PreviewManifest标 `source_type=pptd_render|pptx_render|outline`。outline只是结构预览，UI必须写明，不声称与PowerPoint相同。PPTD截图成功也不证明导出PPTX排版正确。

## 错误码与HTTP语义

| code | HTTP | 可重试/行为 |
|---|---:|---|
| UNAUTHORIZED | 401 | 重新验证，不重发模型 |
| PROJECT_NOT_FOUND / DECK_NOT_FOUND / ARTIFACT_NOT_FOUND / PLAN_NOT_FOUND / CHANGE_NOT_FOUND / EVIDENCE_NOT_FOUND | 404 | 检查ID；EVIDENCE_NOT_FOUND=chunk不存在/不属该项目/不在所请求累积revision内 |
| PAYLOAD_TOO_LARGE / PAGE_LIMIT_EXCEEDED | 413 | 缩减资料 |
| UNSUPPORTED_FILE / PDF_ENCRYPTED / PDF_TEXT_UNAVAILABLE | 422 | 换可解析资料 |
| VALIDATION_ERROR / EDIT_UNSUPPORTED | 422 | 修改请求 |
| IDEMPOTENCY_CONFLICT / VERSION_CONFLICT / CORPUS_CHANGED / PROJECT_BUSY / PLAN_NOT_CONFIRMED / CHANGE_NOT_COMMITTABLE / CONSENT_REQUIRED | 409 | 刷新/确认后重做；CHANGE_NOT_COMMITTABLE=候选blocked/已提交/核验未全过，不得应用；CONSENT_REQUIRED须确认告知后重新建项目 |
| INSUFFICIENT_EVIDENCE / EVIDENCE_CONFLICT / EVIDENCE_INVALID | 422或job.blocked | 保持旧版本、补材料/收窄目标 |
| MODEL_AUTH_ERROR / MODEL_PROTOCOL_ERROR | 502或job.failed | 修配置，不无限重试 |
| MODEL_RATE_LIMIT / MODEL_TIMEOUT | 503或job.failed | 受预算限制重试 |
| MODEL_UNAVAILABLE | 503或job.failed | 供应商临时故障（5xx/连接失败重试耗尽），稍后重跑 |
| MODEL_OUTPUT_INVALID | 502或job.failed | 一次格式修复后仍不合Schema，重跑或换模型 |
| BUDGET_EXCEEDED | 422或job.failed | 用户决定是否增加预算 |
| EXPORT_FAILED / PREVIEW_FAILED | job.failed | 保留DeckVersion，只重试该派生步骤 |
| JOB_INTERRUPTED / CANCELLED | job终态 | 明确中断，不伪报成功 |

异步任务已被202接受后，阶段错误通过GET Job的200结果体现，不能期待原POST再次返回4xx。上述“或job”明确区分同步预检和异步执行。

## 前端轮询规则

默认每2秒轮询，后台页可放缓到5秒；终态立即停止，组件卸载AbortController清理。401停止且提示鉴权，单次网络错误保留最近状态并重试查询，不重新提交生成。只采纳更新时间更晚且匹配当前job/version的结果。

## 变更同步

新增接口必须修改OpenAPI、Schema、api.md、前端类型、错误处理和测试矩阵。自动导出的FastAPI OpenAPI需与本规格差异核对；不能把自动导出覆盖规格从而隐藏协议改变。
