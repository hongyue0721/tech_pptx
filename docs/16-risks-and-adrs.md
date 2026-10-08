# 决策记录与风险登记

## 已接受的架构决策（规划层）

ADR-01：teacher-courseware为原创行业Skill，ppt-edit/AnyUI是候选第三方；不将其作者元数据修改成自己的名字冒充原创。

ADR-02：Vue+AnyUI，两个路由，前端为后端状态视图；锁定经实测版本，不维护组件库。

ADR-03：P0只文本PDF。解析器默认pypdf；此前推荐PyMuPDF时忽略AGPL/商业许可，现显式修正。若选择PyMuPDF需先决定如何履行许可，不能仅在THIRD_PARTY写一句MIT。[S13][S15]

ADR-04：DeckSpec是教学语义真源；PPTD和PPTX是派生产物。渲染选定一条有效路径，备选不并行维护。

ADR-05：引用定位/语义核验/教师确认分开，资料不足不发布无依据事实；不宣传零幻觉。

ADR-06：持久job、单Worker、单项目写锁、候选后应用、版本单调递增；不因MVP删事务与幂等。

ADR-07：运行模型无Shell/网络工具，联网范围仅预置LLM服务。CodeArts开发环境和应用推理权限分离。

ADR-08：Skill与Web共享core但对data-dir排他。Skill采用独立demo目录，不让Agent直接改运行中的SQLite。

ADR-09：先真实PPTX+结构预览；PPTD图/实际PPTX图等级必须标注。高保真QA能降级，但不能把降级讲成已通过视觉检查。

ADR-10（2026-09-20，修订 ADR-02 的"两个路由"限制）：前端以三个业务视图（资料设置→大纲确认→课件审阅）承载同一流程，浏览器路由为 `/`（创建前）、`/project/:id/materials`、`/project/:id/outline`、`/project/:id/review`，并保留 `/project/:id` 兼容转入。业务范围没有扩大：仍是"材料→大纲→候选→提交"一条链，只是把单页拆成三页以降低单页密度与认知负担；阶段导航常驻、底部主操作固定可见。服务器状态（project/plan/change/deck）仍是唯一事实来源，路由 query 只存定位线索（plan/change/version/slide），刷新后按精确 ID 重读、不猜最新。两页面时代的 WorkspacePage 由三个业务页替代，不新增 Dashboard/设置中心/历史项目中心等后台形态。

ADR-11（2026-09-21，负责人拍板）：T10 导出器采用 **python-pptx**（MIT，锁定 1.0.2，传递依赖 lxml/pillow/xlsxwriter 随 uv.lock 锁定）作为唯一激活导出路径，替代 docs/03 原规划"PptExportAdapter→经准入的 ppt-edit"。依据：R05（ppt-edit 镜像/patched WASM/字体授权）核验未闭合，按 R05 预定处理"不通过则切清晰依赖"执行；docs/08 字面备用 PptxGenJS 不激活——T02 探针已实测同类 OOXML 完整部件链在 WPS 打开/编辑/保存 L1-L3 全过，python-pptx 即该骨架的标准库实现（手写 OPC 链正是 T02 v1 缺链打不开的风险面）。本决策不改 ADR-04：DeckSpec 仍是唯一语义真源、PPTX 是派生产物、备选不并行维护；导出语义（固定 version、纯渲染不推理）以 docs/08 与 api.md 为准。若未来回到 ppt-edit 路线须修订本 ADR 并同步实际宣传。

ADR-12（2026-09-23，负责人拍板"教师逐条核准 partial"）：executable gate 的 **partial 一维**增加教师核准通道。背景=T14 真实链系统性数据：4 次有效真实 generate（33~37 claims）每次 93-97% supported+located，但稳定产出 1-2 条 partial——全部为模型转写附加轻微限定（"重点"强调词、跨句指代补全、操作性细节），保守门（要求全 supported）每次正确拦下→live 提交→导出链在当前"模型+全 supported 门"组合下系统性不可达；docs/12 §3 又禁止无限重试碰运气。决策：仅 semantic_status=partial 且 missing_evidence、unbound、invalid、not_checked、unsupported、conflict 全部为零时，CommitRequest 可携带 approved_partial_claim_ids 逐条核准后应用；清单必须与 partial 集**精确相等**（漏核准→409 missing_partial_approvals、夹带非 partial→409 unknown_or_not_partial、全绿候选携带核准→409 载荷矛盾）；核准集并入前端幂等键（补核准=新意图）。边界：missing_evidence=模型自认缺依据、unbound=无绑定专业断言——两者维持 P0 零容忍不放宽；候选状态机不变（partial-only 仍 blocked，核准只作用于 commit 门）；commit 结构重算与 CAS 防线原样。语义：人工逐条对照资料确认是**加一道人审**（教师主体、AI 辅助的产品理念），不是"点一次确认盖绿章"；UI 无全选按钮、换候选即清核准、同候选 409 重读保留勾选。同步：docs/04 gate 段、api.md commit 段、models.schema.json/openapi.json CommitRequest、CLI change commit --approve-partial。

## 开工风险表

| 编号 | 风险/未知 | 优先级 | 处理/门禁 |
|---|---|---|---|
| R01 | 个人账号无自定义模型席位/权限 | 阻塞 | 账号实测或官方内置模型；不绕过 |
| R02 | 命题对CLI+第三方开发模型认定未书面确认 | 高 | 负责人询问，保留答复 |
| R03 | 校内截止与报名通道不明 | 阻塞 | 先确认学校，不只看全国截止 |
| R04 | 单题参与不足5项目可能不进入后续评审 | 高 | 查当前有效参与数/命题方口径，技术工作不能解决 |
| R05 | ppt-edit第三方镜像/WASM/字体授权未查清 | ~~阻塞~~ 已闭合（2026-09-21） | 按预定"不通过则切清晰依赖"执行：ADR-11 选定 python-pptx，ppt-edit 不进运行路径，不再阻塞 T10 |
| R06 | AnyUI仓库0.5.2未验证npm发布/构建 | 高 | 最小Vue页smoke，锁文件，不照搬全部monorepo |
| R07 | PDF中文抽取/公式图表丢失 | 高 | 自编文本资料、解析质量预览、声明不支持 |
| R08 | 乱挂引用，语义核验假阳性 | 高 | 精确定位+单独语义核验+教师抽查+负向案例 |
| R09 | 拆页漏事实/跨页修改 | 高 | claim集合与非目标hash测试 |
| R10 | 作业重启/重发导致重复计费和覆盖 | 高 | 持久状态/幂等/版本冲突；不自动重放 |
| R11 | 预览成功但PPTX字体/OOXML异常 | 高 | 目标Office实际打开编辑 |
| R12 | 云模型429、协议不兼容、花费失控 | 高 | 两种模型配置独立smoke、限次/限时/限额 |
| R13 | 文档预置expected泄漏进运行链 | 高 | 测试目录不挂载，fixture模式显式标志 |
| R14 | 单人认知负担、开发范围再次膨胀 | 高 | 一任务一验收，朋友只做真实支持工作 |

以上优先级是工程判断，不是赛事官方评级。M0完成后逐项填实际状态与证据，不能保持一张全绿色但没有运行记录的表。

## 变更请求模板

说明问题、现有证据、最小修改、替代方案、接口/数据/测试/授权影响和回退方式。负责人仅批准涉及范围/费用/数据外发/合规的重大变更；Agent可自主修符合契约的局部bug。
