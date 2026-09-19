# 交给CodeArts的首次施工指令

你负责开发Courseware Copilot Demo。先读取AGENTS.md、process.md、docs/00-owner-guide.md、docs/01-prd.md、docs/02-architecture.md、docs/10-codearts-and-skill.md、tasks/tasks.json。

本轮**仅执行M0准入与技术探针**，不要铺开整站。当前文档是规划不是已实现程序；不能运行不存在的courseware_core命令后伪报成功。

1. 列出真实环境版本、当前工作区/分支、已有文件；记录CodeArts版本和可用模型。不查看或输出真实Key。
2. 检查账号自定义模型席位/权限。用隔离smoke目录验证文件读写、工具调用、pytest成功/失败修复和会话导出。缺权限明确阻塞，不绕过。
3. 检查Vue+AnyUI候选版本可安装、类型入口、CSS与生产构建；不克隆整个UI库、不照搬React/Svelte依赖。
4. 查ppt-edit直接和传递组件来源/许可证。授权未闭合不得运行patched/no-sign路径当默认方案；提出PptxGenJS等授权清晰的单一替代，记ADR。
5. 用自编短PDF验证pypdf文本/页码；在选定、已许可Exporter上生成一份最小可编辑PPTX，并要求负责人在目标Office打开确认。没有人工结果写NOT_RUN。
6. 编制环境/兼容性矩阵、真实命令和结果、依赖锁定建议、阻塞清单，更新process.md、THIRD_PARTY.md、相关ADR。

你可以自主完成范围内的普通文件和测试，不必每写一行就问我；新增费用、公开部署、真实材料外发、许可证风险或主架构变更才需要我决定。没有通过M0不实现全部业务。

结束时只汇报：实际通过项、未通过项、证据路径、是否允许进入T03以及原因。严禁“应该可以”“已全面验证”而无记录。
