# 文档同步与事实维护制度

## 唯一事实源

PRD管范围；architecture管模块边界；models.schema管数据形状；api.md+openapi管HTTP契约；tasks管待做任务；process管当前事实。SDD文件、README、答辩材料只能引用/摘要，不各写一份不同接口。

文件名统一小写`api.md`和`process.md`，避免Linux上API.md/api.md两份并存。稳定文档用编号，业务实现产生后不把工作日志堆进architecture。

## 每轮同步顺序

开工：读process当前commit/任务/阻塞，确认不是在旧分支上施工。需要改契约时先记录原因→更新Schema/OpenAPI/api→调整实现和消费者→定向测试+回归→更新引用与迁移说明→更新process和CHANGELOG。普通内部重构不改API就明确写“契约无变化”。

变更矩阵：接口变化同步api、OpenAPI、types、API tests；数据变化同步Schema、存储迁移、fixtures和引用定位；依赖变化同步锁文件、third_party、部署与smoke；功能变化同步PRD、任务、E2E和demo；权限/成本变化同步owner guide、.env.example与安全说明。

## process必须含什么

当前阶段/分支/commit（未知就unknown）、正在做唯一任务、已完成与证据路径、实际运行的命令/退出码、失败项、NOT_RUN项、风险阻塞、接口/配置改变、下一任务。状态仅PLANNED/IN_PROGRESS/BLOCKED/DONE；DONE必须指向测试或可核对产物。

文档本身已写好可以记DONE，但不能连带把对应业务实现写成DONE。本包全部业务任务初始PLANNED。工程中每个任务结束更新一条交接摘要，不用每天一百条“正在优化”。

## AI停止规则

发现现代码与规格不一致先分辨bug还是变更提案，不默认代码即权威。连续两次同类修复失败，保留日志让Reviewer定位根因；不引入第二套框架救火。禁止为了完成任务删测试、放松Schema、吞异常或永久fallback到fixture。

## 机械检查

本包`tools/validate_pack.py`验证静态契约、任务DAG、文件链接、数据定位与示例。将来项目CI另外运行：lint/typecheck/unit/contracts/E2E，自动对照FastAPI导出OpenAPI。文档校验通过不能替代真实LLM/CodeArts/导出/浏览器测试。

每次影响UI/导出的改动附截图或PPT人工检查记录。修改了提示词也算产品行为变化，需要prompt_version和模型回归，不只写“文案优化”。
