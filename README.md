# Courseware Copilot · 教师课件助手

本仓库根目录即项目根目录。教师提供课题、教学要求和可提取文本的 PDF，确认大纲后生成有来源的课件；局部修改须审阅确认，正式版本可导出可编辑 PPTX。

项目包含 Vue 前端、FastAPI 后端与共享业务核心、CodeArts Skill、接口契约、自编演示数据和规划文档。PDF 导入、候选生成与审核、版本化编辑和导出均已实现；真实模型需要单独配置和授权，完整上线验收与公网部署不能由离线测试代替。历史进度与已知未验项见 `process.md`、`tasks/tasks.json`。

## 从哪里开始

负责人：先读 `docs/00-owner-guide.md`、`docs/01-prd.md` 和 `docs/14-milestones-and-demo.md`。施工按 `AGENTS.md`、`process.md`、`api.md` 和相关契约执行；`prompts/00-start-here.md` 是最初规划阶段的历史起点，不是当前施工进度。

从仓库根目录运行后端测试：`cd backend && .venv/bin/python -m pytest tests`；开发 API：`cd backend && PYTHONPATH=src .venv/bin/python -m courseware_api.dev`；前端：`cd frontend && npm run dev`。模型配置参考 `.env.example`，开发入口读取 `APP_DB_PATH`、`APP_PORT`；密钥不进仓库。

连续阅读可打开 `阅读版.html`；演示 PDF 在 `demo-data/inputs/`，参考答案在 `demo-data/expected/`，产品运行时禁止读取参考答案。本机 `.cc_demo/` 与 `.playwright-mcp/` 是被忽略的运行记录，不属于源码。

## 已冻结的范围

Vue 3 + TypeScript + Vite + AnyUI；FastAPI + SQLite + 单实例后台工作器；文本PDF；任务内BM25检索；单一运行时模型；DeckSpec语义真源；固定四类页面；局部变更确认与撤销；版本化导出；码道原创Skill调用同一业务核心。

不做Web搜索、OCR、旧PPTX导入、Word/视频解析、多风格、通用画布编辑、多人协同、账号平台、向量数据库、MCP扩展服务或多Agent自治系统。

## 相比聊天草案的重要修正

1. 码道自定义模型有账号/席位/套餐权限前提；技术支持不自动等于赛事书面认可。
2. `ppt-edit`是待准入依赖，不将作者字段或根目录MIT声明当成所有内嵌资产授权结论。
3. PDF默认解析器调整为 `pypdf`；PyMuPDF仅在完成AGPL/商业许可评估后通过ADR启用。
4. 后台任务必须落库；撤销生成新版本；预览/下载绑定具体版本，不能只下载“latest”。
5. 找到引用不等于证据支持结论；保留自动语义核验及教师确认，不做零幻觉承诺。
6. CodeArts、渲染器、浏览器、外部模型与云部署仍需实测；不得写成“仅剩三点未知”。

## 本包的唯一事实源

| 文件 | 职责 |
|---|---|
| `AGENTS.md` | AI工程纪律、变更与交接规则 |
| `api.md` | HTTP语义、错误、幂等与版本约定 |
| `contracts/openapi.json` | 接口路由和机器可读请求/响应契约 |
| `contracts/models.schema.json` | 数据模型的机器可读约束 |
| `process.md` | 真实进度、阻塞、测试证据和下一个任务 |
| `docs/` | PRD、架构、模型、证据、UI、部署、验收、来源 |
| `tasks/tasks.json` | 施工任务及依赖 |
| `demo-data/` | 输入PDF、源文本、演示脚本、评价用例 |
| `validation-report.md` | 本规划包静态检查；不代表应用测试 |

校内截止、账号、预算及第三方授权未落实前，不作“肯定赶得上”或“保证符合全部要求”的承诺。规范冲突应显式提出ADR，不私自选择旧聊天中更方便的版本。

## 重建与校验

运行 `.venv/bin/python tools/validate_pack.py` 检查包内契约和数据（首次安装工具依赖见 `tools/README.md`）；`python tools/build_reader.py` 重建阅读版。`manifest.txt` 与 `SHA256SUMS.txt` 保存最初规划包交付快照，不代表整理后的当前文件清单或校验和。
