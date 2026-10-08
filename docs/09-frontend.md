# 前端规格｜Vue + AnyUI（三业务页面，ADR-10）

## 1. 技术与边界

Vue 3 + TypeScript + Vite + Vue Router + `@any-design/anyui@0.5.2`（npm 正式依赖，锁准确版本，不用 latest）；官方 Vue 入口 `@any-design/anyui/vue`，样式 `@any-design/anyui/styles/index.css`。不加入 React、Nuxt、SSR、Pinia、富文本编辑器或画布引擎。后端是业务状态唯一真源；前端 composables 负责选中页、输入框、轮询与弹层。

AnyUI 用于 Button/Input/Textarea/Checkbox 与 Dialog/Drawer/Toast/Progress/Tabs。个别控件用轻量本地组件替换（如 StatusTag 保证"状态不只靠颜色"、文件队列），不修改 AnyUI 源码、不为贴合组件库改业务模型。`AUpload` 只选择/派发文件不负责 HTTP；多选走原生 input multiple + 本地队列。`ASplit` 不是可拖动分栏；三栏用 CSS Grid。`AChat` 不使用（无通用会话后端）。图标与字体本地/系统，禁运行时远端 Iconify/字体/图片请求。

安装说明：AnyUI 声明多框架 peers（react/svelte/iconify），Vue-only 工程安装需 `--legacy-peer-deps`（T02 smoke 结论，非 force 掩盖）；Vue 运行时 peers `@iconify/vue`、`@popperjs/core` 显式声明。

## 2. 路由与三个业务视图（ADR-10）

```
/                          IntakePage（创建前：课题表单+待提交队列）
/project/:id/materials     IntakePage（已创建：课程只读+资料队列+解析状态）
/project/:id/outline       OutlinePage（?plan=精确ID）
/project/:id/review        ReviewPage（?change=…&slide=… 或 ?version=…&slide=…）
/project/:id               兼容入口 → WorkspaceEntry 按服务器真值转入：active_job_id 非空→materials（页面恢复链跟踪）；无活动任务且 current_version≥1→review?version=N（真值参数）；否则→materials（不猜 plan/change id）
```

业务流程固定为「资料设置 → 大纲确认 → 课件审阅」三步，顶部轻量阶段导航 + 底部固定主操作；不是后台管理系统，无 Dashboard/设置中心/登录页/历史项目中心/模板商城。

组件结构（frontend/src）：

```
layouts/{CourseShell.vue, stepNav.ts}
pages/{IntakePage, OutlinePage, ReviewPage}.vue
components/common/StatusTag.vue（状态文字+色点，不只靠颜色）
api/{client.ts, resources.ts}（fetch 封装：X-Request-ID、Idempotency-Key、ApiError）
types/models.ts（与 contracts/models.schema.json 对齐，不手写第二套字段名）
styles/{tokens.css, base.css}（FRONTEND_SPEC §2 纸页感/深靛蓝/陶色）
```

## 3. 页面规格

### A 资料设置（IntakePage）

两栏：左「这节课，想讲什么？」（课题/对象/课时/页数/目标/云处理告知 consent 默认 false），右「教学资料」（本地待提交队列可增删；上传逐份进行）。底部：资料状态 + 主操作。创建前按钮「保存设置并解析资料 →」；创建后课程配置只读（无 PATCH 接口就不制造"保存成功"），主操作「生成教学大纲 →」仅在全部资料 ready 且无活动 job 时可用。

上传链路（F2 接通）：创建成功返回真实 project_id 后才逐份上传；每份上传后轮询 parse job 至终态、项目写锁释放后再传下一份；不用 Promise.all 并发制造 PROJECT_BUSY；duplicate=true 显示既有文件不制造新解析任务；刷新后浏览器 File 对象失效，不谎报能续传未上传文件。

### B 大纲确认（OutlinePage）

三栏：左教学目标与检索覆盖（supported/partial/unsupported/conflict 语义为"相关资料充分/不足/缺口/冲突"，coverage 是检索覆盖不是"事实已验证"）；中紧凑页面列表（一行一页，选中高亮）；右当前页详情（标题/purpose 编辑、布局只读展示、来源段数、上移/下移）。缺口目标不预选、不可接受 unsupported/conflict 目标。

底部主操作「确认大纲并生成 →」内部严格串行：`POST confirm`（精确 plan_id、教师版 slides/accepted_goal_indices）成功 → `POST generations`。绝不绕过 confirm；已确认后失败重试生成不新建计划。URL 保留精确 plan_id，刷新重新 GET 指定 plan，不猜最新。confirmed 计划只读。

### C 课件审阅（ReviewPage）

三栏：左页导航；中 16:9 结构预览（语义块卡片，fact 块通过 claim_id 查 claims 字典——不存在 fact.text 字段；引用未建立显示"该条引用未建立，查看核验报告"，不白屏不静默丢页；标注「结构预览，非 PowerPoint 渲染」）+ 翻页器；右 Inspector 三 Tab（内容/依据/核验），不是常驻聊天窗，不放假的自然语言编辑输入框（T12 未接）。

候选/正式状态标签克制区分：`候选稿·未应用`、`正式版本 vN`、`候选已过期`。底部：状态与阻塞原因 + `返回大纲`、`导出 PPTX`（T10 未接=disabled+原因）、`应用此候选版本`。

## 4. CandidateChange 状态服从服务器（不前端推断）

消费 `change.status + validation.can_commit + claim_checks + unbound_assertions + warnings`：

- ready 且 can_commit=true：核验通过，允许教师确认后 commit；
- blocked：显示定位失败/partial/unsupported/conflict/not_checked/unbound/warning，禁止应用；
- stale：候选基于旧版本/旧资料，禁止应用，提示刷新重新生成；
- committed：已应用为正式版本，不再显示"再次应用"；
- job.succeeded 只表示执行完成，不等于可 commit。

提交成功返回 DeckVersion（服务端权威 version）→ 再 `GET deck?version=N` 渲染正式 Deck；不把 CandidateChange.candidate 冒充正式版本；409 重新读基线，不乐观强改。Evidence 原文走 `GET /projects/{id}/evidence/{chunk_id}?corpus_revision=N`（服务器定位结果），前端不拼页码。

## 5. 状态管理与异步规则

不引 Pinia。composables：`useProject`、`useJobPolling`、（F2/F3 扩展 materials/plan/change/deck/evidence）。URL 存定位状态（projectId/plan/change/version/slide）；服务器数据为事实来源；刷新按精确 ID 恢复。

同一路由组件内 params/query 变化：abort 上一请求、带 epoch 防旧回包覆盖新状态；轮询前台 2s、后台 5s、串行 setTimeout（上一请求未完成不叠下一轮）、终态即停、组件卸载 AbortController 清理。GET 重试与 POST 幂等重试分开；网络错误不自动重发模型生成。受理 202 立即把 job_id 写入 URL。

任务取消（D-06）：轮询进行中（isPolling）资料页/大纲页显示"取消任务"，点击 POST /jobs/{id}/cancel（稳定幂等键 cancelJobKey(jobId)，同 job 重试同键）；200 仅表示取消已受理（协作式），UI 不自行判终态、继续轮询等待服务器 cancelled，期间按钮呈"取消中…"禁用；对已终态 job 取消返回 200 现态、无害。

## 6. 错误显示（按错误码给动作，不统一"操作失败"）

PDF_TEXT_UNAVAILABLE→换文本型 PDF；PDF_ENCRYPTED→暂不支持加密 PDF；INSUFFICIENT_EVIDENCE→补充资料或调整目标；CORPUS_CHANGED→资料已变化请刷新重新规划；VERSION_CONFLICT→版本已更新请刷新继续；CONSENT_REQUIRED→确认云处理告知后重新创建；PROJECT_BUSY→等待当前任务完成。错误详情不显示 API Key、服务器绝对路径、供应商原始敏感响应。

## 7. 布局与响应式（一屏原则）

固定外壳 `grid-template-rows: 62px 60px minmax(0,1fr) 66px`（100dvh）；分栏祖先 min-height/width:0。验收尺寸 1440×900、1366×768、1180×740、941×768（CSS px）：顶部导航、主内容、底部主操作在视口内可见；允许列表/文件队列/Drawer 内部滚动；不全局缩字号、不 overflow:hidden 裁内容、不隐藏功能。

- ≥1180：审阅三栏（174px / minmax(0,1fr) / ~295–300px）；
- <1080：右 Inspector 与大纲目标列转可开合抽屉（按钮开、×关），中央内容优先；
- <760 或高倍缩放：允许纵向重排与页面滚动，操作与内容不丢失。

## 8. 可访问性与文案

键盘可达（Tab 顺序、焦点可见 outline、抽屉 Escape 关闭并回焦）；阶段导航 aria-current="step"；结构预览 aria-label；状态不只靠颜色。文案教育工具语气：说明能做什么与为什么阻塞，不夸大（"自动核验通过，建议教师复核"，不写"100% 正确"）。模型文本用 Vue 转义渲染，P0 不用 v-html。

## 9. 施工状态与真值

F1（已完成）：AnyUI 正式接入、三页路由、外壳、视觉 tokens、真实 GET project/materials/plan/change/deck 读取骨架；未接写入操作一律诚实 disabled+原因，生产代码路径无 mock 数据（演示数据只允许出现在测试 fixture）。截图见 docs/screenshots/f1/（共 7 张：1366×768 四页 intake/materials/outline/review、941×768 review、1440×900 materials、1180×740 review）。

F2（已完成，2026-09-20）：真实资料→真实大纲链。上传逐份+parse 轮询释放写锁、duplicate 不占位、job 精确写入 URL 并刷新恢复（URL job 优先→服务器 active_job_id 兜底）、幂等键=操作意图+业务锚点+attempt（attempt 由 URL query `pa` 承载：job 终态=意图已消费 attempt 前进、刷新不丢；受理结果未知同键恢复）、confirm 成功才 generations 严格串行、缺口目标禁勾+取消引用预检与后端同口径、"已逐页审阅"勾选门防一次点击绕过确认、stale 只读、错误码→教师文案映射（api.md 表为真源）。真实浏览器链验收（无模拟上传/解析）截图 docs/screenshots/f2/；独立 Review 3 阻塞+7 非阻塞全部当场闭环（docs/reviews/t11-f2-review.md）。成功链真实模型实测 PASS（2026-09-20 负责人授权 deepseek-flash：大纲 succeeded→confirm→generate succeeded 10 调用→自动跳审阅；42 claims 40 supported+2 partial→候选诚实显示"未通过核验"、应用禁用；prompt_version/model_id 留痕于 ValidationReport）。

F3（已完成，2026-09-21）：候选核验渲染、commit、deck、Evidence Drawer。ValidationPanel（三 gate+model_id/prompt_version/checked_at 留痕+问题 claim 前置+通过项折叠+unbound 含 reason+warnings 呈现 missing_evidence 合并流——契约中 missing_evidence 属提案层，教师可见面=validation.warnings，不另造字段）；依据 Tab 按当前页过滤，缺失 claim 可解释占位；commit 链完全服从服务器（canApply=status ready∧can_commit，body=候选基线三要素+acknowledged，稳定幂等键与服务器"失败可同键重执行/成功可回放"语义自洽，201→push version→load 重读真值不乐观改写，409→重读基线+诚实冲突文案，committed/stale/discarded 文案与服务器态一致，footer 只呈现服务器态）；正式版本 ver-nav 切换（1..current_version，不猜版本）；EvidenceDrawer 经 GET evidence 精确 project/revision/chunk（锚定**当前展示对象**的 corpus_revision），偏移按码点换算（Array.from，禁 UTF-16 直接切片），quote 与偏移切片不一致时诚实告警，404/409 走错误文案；export/preview/edit 等未接路由零请求（网络清单实证）。五态浏览器验收 PASS（ready/stale/409/evidence-409 为 dev 库构造态并留痕，不冒充模型语义背书）；截图 docs/screenshots/f3/（7 张）；独立 Review（模型 huaweicloud/qwen3.8-flash 标注）1 阻塞+6 非阻塞：B1 evidence revision 锚定改随展示对象、N1–N5 当场闭环、N6 缓存上限进 backlog（docs/reviews/t11-f3-review.md）。

F4（已完成，2026-09-21）：UI_TEST_MATRIX 1440×900/1366×768/1180×740 三页+941×768 Inspector 抽屉截图 11 张（docs/screenshots/f4/，console 0 错误）；**远程图标消除的实际手段=main.ts 去 `app.use(AnyUI)` 全量注册、组件纯具名导入**（根因：AMessage.install 无条件 loadIcons 预取 4 个 Iconify 图标；三页零外部请求实证 network-zero-external.md）；压力可访问性=真实 8 目标+超长标题（emoji/扩展汉字）+5 份不同 PDF 逐份真实解析，双面板内部滚动+主 CTA 可见实测。**契约事实**：target_slides 服务端上限 12（16 被 VALIDATION_ERROR 拒），12 页全量 deck 压力需真实模型生成未再授权=该项 PARTIAL（滚动机制已验）。矩阵执行中抓到并修复**后端并发 500 生产 bug**（sqlite 连接跨线程交接：uvicorn 线程池+依赖 teardown；修复=check_same_thread=False+threadsafety==3 运行时断言，backend/tests/unit/test_database_thread_safety.py 回归锁，534 全绿）。独立 Review（模型 huaweicloud/qwen3.8-flash 标注）1 阻塞+3 非阻塞全当场闭环。T10/T12 能力（导出/预览/编辑）仍未接：无请求、无假 Blob、按钮 disabled+原因。

每轮同步 api.md/OpenAPI/Schema/前端类型/契约测试（仅契约真实变化时）与 process.md/tasks.json。

收尾轮（D-04/D-06，2026-09-21 负责人放行后闭环）：兼容入口 WorkspaceEntry 按服务器真值转入（active_job_id→materials、current_version≥1→review?version、否则 materials；不猜 plan/change）；cancel UI（两页轮询中"取消任务"→POST 200 受理→等服务器终态，"取消中…"态；API 层 live 实测 PASS，UI 点击全链因 parse 亚秒窗口如实 PARTIAL、T14 generate 补验）；materials 页 generate/blocked 终态按 result_ref 跳审阅看报告；Review B1（parse 恢复终态后 loadMaterials 刷新）修复并可控时序实证。报告 docs/reviews/t11-entry-cancel-review.md。

T12 loop⑤（2026-09-21，工作区段）：审阅页受限编辑消费——**EditPanel**（意图单选：自由文本走模型路径/结构化 reorder 确定性；勾选目标页≤12；受理门参数取服务器真值 project.current_version/corpus_revision，绝不取展示 deck 快照——曾有真实 409 CORPUS_CHANGED 教训）、**SlideMoveControls**（reorder 全量置换载荷+页数变化越界 clamp）、**VersionHistoryPanel**（恢复=产生新版本非本地撤回，acknowledged 二次确认，busy 原因"指针即锁"如实呈现）、**useEditFlow**（job URL 驱动、终态消耗含 interrupted 兜底；editKey 无 attempt、载荷 canonicalize——409/422 占位回滚后同键重试=重新执行，改配置由载荷变化自然换键）。编辑结果只呈现候选与版本历史，前端不直接改 deck。浏览器真实链 PASS（验证项目为真实上传解析+构造 seed 非模型背书）：下移→候选→应用→v3→恢复 v1→v4（semantic_hash==v1、restored_from=1）→重构回归 v5；截图 docs/screenshots/t12/ 3 张；轻量复审（模型 huaweicloud/qwen3.8-flash）0 阻塞。backlog：restored_from 版本卡头呈现（需接口补字段，Q2）、consent 受理前 UI 告知（Q5）。

T10 导出消费（2026-09-22，工作区段）：**ExportPanel**（正式版本视图导出 PPTX=只读快照 job：受理 202→?export_job= URL 承载刷新恢复→轮询→succeeded 保留双下载链接（PPTX+证据报告，report id 按 api.md 契约规则派生并由后端契约测试锁死）；failed/cancelled 清 URL——幂等键=版本意图，占位回滚后同键重试=重新执行；渲染中可取消（协作式等终态）；候选视图 disabled+原因"候选须先应用"；导出说明"最终版式以 Office 打开导出文件为准"不冒充渲染保证）。预览分级 UI 口径：结构预览标注"非 PowerPoint 渲染效果"（既有 preview-note 承载，P0=outline 级）。浏览器真实链 PASS（无凭据后端）：导出 v5→下载 courseware-v5.pptx（文件重开 44 部件/4 页中文/页脚引用）→刷新恢复→console 0 错误；截图 docs/screenshots/t10/ 2 张。L3 目标 Office 实测 PASS（2026-09-22 负责人按 L3 指引实测验收文件：打开+改文本+保存重开确认无问题）——T10 导出消费链 DONE。
