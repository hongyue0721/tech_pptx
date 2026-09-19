# 架构｜一个业务核心，两个入口

## 1. 组件与职责

```text
教师浏览器 Vue + AnyUI
  → REST /api/v1 → FastAPI（鉴权、参数、返回语义）
  → ApplicationService → 持久化Job → 单工作器
  → courseware_core
      PDF解析 → 页与段落 → BM25/覆盖分析 → 大纲确认
      → 逐页生成 → 引用定位 + 语义核验 → DeckSpec候选
      → 教师应用 → 不可变DeckVersion
      → 布局编译 → PPTD/选定导出器 → PPTX与预览

CodeArts Agent → teacher-courseware Skill → core CLI
  → 同一ApplicationService / courseware_core（独立数据目录）

SQLite + 私有项目文件目录保存元数据与产物；外部模型仅经LLMAdapter访问。
```

只有 `courseware_core` 拥有资料解析、课件状态和验证逻辑。前端和Skill不能各自复制一套提示词/评分/渲染。Web不嵌套运行CodeArts，不向任意用户提供shell。开发时模型和产品推理模型是两套独立配置与费用。

## 2. 单实例部署

一个FastAPI进程、一个后台工作器、SQLite、文件存储。HTTP响应后任务进入数据库；工作器串行领取任务，不用Celery/Redis。进程启动拿数据目录独占锁，禁止多实例共享同一SQLite目录。

CLI可独立使用同一核心，但必须使用自己的数据目录。Web正在运行时，CLI不得直接写同一数据库；想操作Web项目需通过HTTP客户端模式（P1），P0演示用独立项目即可。

PDF解析及渲染在受限子进程执行，避免恶意/异常PDF耗尽主进程内存；LLM通过异步HTTP客户端调用。不得将长PDF解析放在async端点中同步阻塞事件循环。

## 3. 核心模块

| 模块 | 输入→输出 | 禁止依赖 |
|---|---|---|
| materials | PDF→DocumentPage、DocumentChunk | LLM、UI |
| retrieval | query+corpus→EvidenceSelection | PPTX、HTML |
| planning | LessonRequest+Evidence→LessonPlan | 用户文件系统任意路径 |
| generation | ConfirmedPlan+Evidence→DeckSpec候选 | 直接文件导出 |
| evidence | claims+source→ValidationReport | 依赖fixture答案 |
| editing | current+EditRequest→CandidateChange | 原地覆盖版本 |
| versioning | 候选+base_version→新版本 | 模型直接决定版本号 |
| rendering | DeckSpec→固定布局→产物 | 回到网络补知识 |
| jobs | 明确阶段→终态 | 无限重试/隐式重新收费 |

## 4. 真源与派生

课程输入、语料revision、已确认计划、已应用DeckSpec版本是正式状态。PPTD、PPTX、页图、缩略图和前端视图都是派生。缓存键至少包含DeckVersion、renderer_version、theme_version、font_profile；不存在全局“当前PPT”文件。

DeckSpec只允许教学语义和有限布局，不让模型填x/y或写CSS。固定布局编译器计算位置；ppt-edit仅承接通过验证的渲染中间文件。备用导出器可从相同固定布局计划生成PPTX；只启用一套，不同时维护两个主出口。切换后如没有PPTD产物，材料和界面如实说明。

## 5. 为什么保留显式步骤

大纲确认将教学覆盖问题暴露在昂贵导出之前；候选变更确认防止一句模糊指令毁掉课件；版本化产物防止屏幕是V3而下载V2。这些不是商业级“过度工程”，而是Demo必须能被追问的最小一致性。

## 6. 未来代码目录（本包不含这些业务实现）

```text
backend/src/courseware_core/  # models/services/materials/retrieval/evidence/llm/render/storage/jobs，CLI见cli.py
backend/src/courseware_api/   # main/api/dependencies；完整内部接口见docs/18-core-interfaces.md
backend/tests/{unit,contract,integration,live}/
frontend/src/{pages,components,composables,api,types,styles}/
.codeartsdoer/skills/teacher-courseware/
contracts/  docs/  tasks/  prompts/  tools/
data/       # 私有、不入Git、不进镜像构建上下文
```

## 7. 需通过M0的假设

码道账号与模型具备工具调用能力；Python/Node和导出器可在目标机器运行；AnyUI存在可用发行物；渲染依赖拥有可用授权；模型能守住JSON和引用契约。未通过前只保留方案，不当作已验证能力。
