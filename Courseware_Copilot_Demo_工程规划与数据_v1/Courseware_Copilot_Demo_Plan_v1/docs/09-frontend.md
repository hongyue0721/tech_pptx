# 前端规格｜Vue + AnyUI

## 1. 技术与边界

Vue 3 + TypeScript + Vite + Vue Router + AnyUI；仅两个路由：`/`、`/project/:id`。不加入React、Nuxt、SSR、Pinia、富文本编辑器或画布引擎。后端是业务状态真源；前端composables负责选中页、输入框、轮询与弹层。

AnyUI的仓库版本是0.5.2，不把它等同已发布npm版本。本包未完成安装验证。M0先检查包可获取、类型入口、CSS、Vue peer与构建；锁定实际通过版本和lockfile。新建业务工程，不克隆整个AnyUI monorepo作为应用。[S08]

按官方Vue入口初始化。最小样例先验证Button/Input/Drawer/Toast；全局注册可以作为Demo简化，不对包体积作未经测量的承诺。不得把上游所有React/Svelte开发依赖照搬。图标本地静态打包，禁运行时远端Iconify请求；界面字体使用本地/系统字体。

## 2. 组件与页面

CreateProject：课题、对象、课时、4—12目标页数、教学目标、PDF队列、云模型资料处理告知。创建后进入Workspace，上传资料逐个排队；文件扩展名过滤仅是用户提示，服务器仍验证字节。

Workspace：顶栏课程名/版本/导出；左栏页导航；中央大纲或页面预览；右栏AI编辑与操作结果；来源Drawer。没有正式课件时中央显示计划：教师检查可支持目标和缺口、调整标题/顺序、确认后才生成。不能先生成十页再要求用户倒过来确认计划。

业务组件建议：`PdfDropzone`、`MaterialQueue`、`OutlineReview`、`SlideNavigator`、`SlidePreview`、`AssistantPanel`、`ChangeReview`、`EvidenceDrawer`、`JobStatus`。同一个页面通过阶段切换，不添加一堆空Dashboard。

AnyUI `AUpload`只选择/派发文件，不负责HTTP上传；本次已读实现取第一个文件。多选用原生input multiple及自定义drop处理。`ASplit`是分割线，不是拖动分栏；三栏用CSS Grid。`AChat`仅作消息呈现，不承担工具调用、来源核验或变更提交状态。复杂操作卡自己做，不为贴合组件库改业务模型。

## 3. 交互闭环

资料导入成功显示：文件名、物理页数、可用文本页、不可用页警告、语料版本。按钮文案是“生成教学大纲”，而非立即“全自动生成完美课件”。资料缺失或全部不可解析不能开始规划。

大纲确认后触发生成job，展示真实stage，无假进度百分比。完成后显示候选课件；检查通过也必须由教师点“应用此版本”。失败/依据不足时保持旧版本，不清空整页。

编辑时发送选中slide_id、base_version与corpus_revision；按钮默认精简、拆成两页、重新解释，可附自然语言。界面明确本次改哪些页。候选展示修改前后差异、知识点变化与核验状态；应用/放弃都可执行。

撤销表现为“恢复到上一版（创建新版本）”。不让前端数组回退假装服务器已保存。导出按钮固定version，等待artifact链接；修改后旧导出显示所属旧版本，不能写“最新”。

来源Drawer显示文件名、PDF第N页、原文摘录和claim；定位成功与语义支持分开，不能用一个绿色图标表示整页绝对正确。印刷页标签仅附加显示。结构预览显式标明，不伪装真实PPT截图。

## 4. 状态和错误

建议composables：`useProject`、`useJobPolling`、`useDeckSelection`、`useCandidateChange`。每个job使用独立AbortController；卸载/换项目停止旧轮询，401停止并提示，超时只重试GET不重新POST。保留表单输入与最后成功状态。

显示empty/loading/blocked/failed/interrupted/cancelled/ready。资料不足是blocked，不是系统崩溃。409解释版本已变化；不自动合并AI修改。选中页删除/拆分后按服务端映射跳转；禁止以数组下标当长期ID。

## 5. 布局、可访问性和测试

单主题，白/浅灰背景、深正文、蓝色强调；不启用全局液态玻璃和大面积动画。16:9课件画布与应用外壳是不同设计对象。

桌面参考三栏220px / minmax(0,1fr) / 340px；窄屏右栏变Drawer，不承诺手机全功能。至少在1366×768和1920×1080验收。内容区域min-width:0，避免长文件名撑开布局。

表单有label，错误可读且不只依赖颜色；可键盘操作主按钮与Drawer，关闭后恢复焦点；空态说明下一步。模型文本用Vue转义渲染，P0不用v-html。上传/提交可禁重复点击但服务端幂等仍不可少。

测试覆盖多PDF队列、同文件重复选择、扫描件失败、job恢复、候选应用、来源查看、拆页后选中、409、取消、导出和刷新恢复。AnyUI组件异常先在业务包装层替换，不能擅自转向修整个组件库。
