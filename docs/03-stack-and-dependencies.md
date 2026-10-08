# 技术栈、依赖与锁定方式

| 层 | 决策 | 锁定/验证 |
|---|---|---|
| 开发环境 | Ubuntu24.04优先，Arch仅本机终端/SSH | [S07]列出Ubuntu；不要求额外安装VM才能开始 |
| Python | 3.12 | M0记录补丁版；venv隔离 |
| Node | 22.12+ | [S17]；不能按ppt-edit Node18要求配置整套项目 |
| 包管理 | 前端npm + package-lock；Python uv.lock或受控requirements.lock，M0选定一个 | 禁止混用多个锁文件来源 |
| 前端 | Vue3、TS strict、Vite、Vue Router、AnyUI | AnyUI仓库版本0.5.2是候选，npm可安装性未实测；M0锁tarball/完整性 |
| 状态 | Vue composable管理工作区瞬态，后端为持久化真源 | 不上Pinia；不等于“不管理前端状态” |
| 后端 | FastAPI、Uvicorn单worker、Pydantic v2、httpx | M0确认相互兼容并锁具体版本 |
| PDF | pypdf | 原PyMuPDF调整原因：[S13—S15]；不启用OCR |
| 检索 | jieba + rank-bm25 | 锁版本、词典和tokenizer_version；无embedding |
| 存储 | SQLite（WAL、外键、busy timeout）+ 文件 | 单实例，原子写与快照 |
| 渲染 | python-pptx==1.0.2（ADR-11，2026-09-21 负责人拍板，唯一激活出口） | uv.lock 锁定；MIT；生成 T02 实测过的同类 OOXML 完整部件链 |
| 替代出口 | ppt-edit/PptxGenJS 均不激活（ADR-11） | 单一激活出口；不是两套都做；回退须修订 ADR |
| 测试 | pytest、jsonschema、前端类型检查、Playwright | live标签默认不消耗API；需显式开启 |
| 部署 | 单台云实例 + Nginx HTTPS + systemd | 不是强制华为ECS，选择其可便于展示；见[S01]云部署目标 |

## 依赖准入

先建立最小空工程安装、类型检查和构建，记录操作系统/架构/Node/Python/包管理器版本。核查source tree与实际发布包入口一致。禁止只凭README宣布“已适配”。本轮无法连接npm/PyPI registry，相关安装状态是NOT_RUN。

AnyUI只复用底层组件，不clone整个monorepo当产品模板，不引入React/Svelte依赖。需要的Vue peers按实发包记录安装；不能把上游所有devDependencies复制到应用。UI缺陷用业务适配器/原生元素处理，禁止临时fork库修大量代码。

## 许可与来源

AnyUI上游按MIT标记[S08/S09]，保留对应声明。ppt-edit根LICENSE为MIT[S12]，但local-export说明包含patched WASM[S11]：必须确认其资产来源与许可链；根LICENSE不能替他人资产授权。不得生成或依赖规避签名/访问控制的新补丁。

PyMuPDF的官方许可为AGPL/商业双许可[S15]，并非“任何项目都能按MIT分发”。P0选择pypdf降低未审许可风险；这不是法律意见，也不等于AGPL不可用于比赛。

PPT默认不嵌入字体，不复制本机商业字体。用目标机器合法安装的中文字体并记录profile；实际Office缺字体会替换，须验收。包中不分发字体文件。未来如嵌入，另行审查字体许可及导出器能力。

## 可复现清单

M0产出 `dependency-lock-report.json`：包名/版本、来源、integrity或commit、许可证、用途、实测状态。Docker不是核心前置；若使用镜像需固定base digest和依赖，不把data、eval expected、Key或私有会话打包进去。
