# process｜当前工程事实与交接

版本：1.0.0；日期：2026-09-18；阶段：**M0 / PLANNED**。

## 当前事实

本轮交付工程规划、契约、Skill模板、自编演示资料和静态校验工具；**没有实现Courseware Copilot应用，没有在码道中运行，没有创建ECS，没有向GitHub/AtomGit写入，没有调用收费模型。**

| 对象 | 状态 | 证据/说明 |
|---|---|---|
| 规划/接口/工程规范 | DOCS_CREATED | 本文档包，校验见validation-report.md |
| Demo教材、案例与负向输入 | DATA_CREATED | demo-data清单与解析检查；不是产品生成结果 |
| 真实CodeArts账号/模型权限 | NOT_RUN | 需要负责人账号与席位实际确认 |
| CodeArts外接模型工具调用 | NOT_RUN | 产品文档已查阅，不等于实机通过 |
| 原创Skill运行 | NOT_RUN | 当前只提供模板与目标CLI契约 |
| AnyUI安装/构建 | NOT_RUN | 包查询尝试受本环境DNS限制，未能验证npm发布 |
| ppt-edit授权/稳定性 | BLOCKED_PENDING_AUDIT | root MIT与第三方WASM的授权范围尚未闭合 |
| 应用真实LLM/检索/版本/E2E | NOT_RUN | 无业务实现，不伪造测试结果 |
| PPTX导出/目标Office检查 | NOT_RUN | 本包不包含假装由应用生成的PPTX |
| 校内截止/命题参与数/书面认定 | OWNER_PENDING | 见比赛交付文档 |

## 当前任务

唯一建议开工任务：**T00，M0准入与证据登记**，之后T01/T02探针。任务表在tasks/tasks.json。仓库分支/commit：未创建，unknown。

## 本轮实际检查

规划包静态检查、JSON Schema/OpenAPI引用、任务依赖、演示PDF文本与页码、精确证据定位等，最终以validation-report.md记录为准。只读查询的GitHub内容用于依赖审查；未改远端。

## 收工记录模板

- 任务ID / commit / 改动路径。
- 实际完成内容及证据。
- 实际测试命令、退出码、失败和NOT_RUN。
- API/Schema/配置/提示版本变化。
- 新阻塞与费用/数据外发情况。
- 下一项唯一任务。

以后由施工AI每轮更新事实，不将这份初始说明持续当作当前状态。所有“计划已写”与“产品已实现”必须分开。
