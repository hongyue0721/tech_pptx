# 单任务施工模板

当前任务：<tasks/tasks.json中的ID>。

先读process.md与该任务关联规范；读取需要的源码和测试。说明当前事实、最小实现方案和预计改动文件，然后直接执行符合已冻结契约的实现，不做范围外架构调整。

允许改动：<路径>。输入/输出：<Schema与API>。禁止：<边界>。

验收：<具体case和命令>。必须运行定向测试，再跑受影响回归；未能运行说明原因，不改低测试标准。不得引用demo-data/evaluation或expected来替代模型推理。

若接口变化先更新契约并说明理由；无法在现有范围解决时保留失败证据并提出一个最小变更。完成更新api.md（若无变化写明）、process.md、关联docs、CHANGELOG；用templates/handoff.md交接。
