# CodeArts开发工作流与原创Skill

## 1. 产品支持、账号权限和比赛认定分开

官方题面要求全程使用码道开发并提交使用/会话记录，至少一个原创Skill可在码道运行并在AtomGit发布。[S01]

CLI官方文档支持第三方Chat Completions或Anthropic Messages；自定义模型仍有企业成员、启用席位及部分套餐管理员许可前提，代码补全也不随自定义模型切换。[S03] 不能把“文档支持”当作你的账号已经开通，不能把接通文本问答当作工具执行可用。

本方案采用CodeArts CLI作为开发Agent，自定义模型是其推理后端；应用推理用独立APP配置。赛题未在已读文字中明确逐条裁决“CLI+第三方模型”组合，需向命题方确认并保留答复，不给出无条件合规担保。若外接权限不可用，先试官方内置模型完成M0，不绕开权限或伪造会话。

## 2. M0实机清单

记录OS/架构、`codearts --version`、`codearts --help`与安装来源。Ubuntu为官方列出的平台之一；Arch是否可运行要实测，不视为官方支持。[S07]

执行`codearts models`查看模型；在隔离的smoke目录让Agent读取小文件、改一处、创建pytest测试、执行测试并解释退出码。故意制造一个失败测试，确认它能修真实实现而非删断言。接着加载最小Skill执行同类任务。

必须保留：所选provider/model、工具调用及结果、实际文件diff、测试输出、失败原因。八个能力项：认证、文本、工具调用、工具结果回传、多次工具循环、文件编辑、非零退出码处理、会话导出。只有前两项通过不能开启整项目施工。

官方命令包含`codearts session list`与`codearts export <sessionID>`；后者输出JSON，应重定向至私人日志后脱敏。先以实际安装版本help核对。[S05]

## 3. 自定义模型配置

样例见`config/codearts_cli.example.json`，不是可直接带Key提交的真实配置。实际文件位于用户home的`.codeartsdoer/codearts_cli.json`，使用官方provider结构。[S03]

不覆盖已有配置；本地备份后只增加一个provider。文档支持apiKey/baseURL及环境变量回退，但具体优先级与版本必须实测。模板保留本地占位符，不臆造模型context/价格/图像能力。`tool_call=true`只是配置声明，不会让不支持工具的模型凭空具备能力。

不把个人订阅登录令牌转换成未获授权的API，不假设ChatGPT/其他产品订阅等同API额度。SDK路径、`/chat/completions`自动补全、流式工具增量格式、reasoning参数都需要小样本验证；不支持的参数从最小配置中去掉，不通过关闭TLS解决。

## 4. SDD与单人施工

一次项目级规格→设计→任务；小修不重复全套流程。CLI可使用`codearts run --command sdd-new "需求描述"`；TUI使用对应斜杠指令，具体以安装版为准。不要把CLI与TUI语法混写。[S05][S06]

SDD产生的文件只作码道过程产物。本包PRD、architecture、api和Schema是已接受契约；SDD内容有冲突要提出ADR，不得形成两套互相矛盾的主规格。每任务一个短上下文Builder，Reviewer用新上下文只检查diff和契约。

初始阅读顺序：AGENTS→process→当前任务→关联接口与测试。普通文件实现无需每一步问负责人；新增费用、公开部署、数据外发、换架构、改合同、授权问题才上报。人工确认点保留在这些高风险决策和阶段验收。

## 5. 原创Skill到底提供什么

`teacher-courseware`负责明确可复用的领域工作流：资料范围检查、目标覆盖、证据提取、课件计划、候选编辑、核验、导出，调用共享courseware_core。不能只是“请调用网站API”的空壳，也不把第三方ppt-edit算成自己原创。

模板在`skill-template/teacher-courseware/`，当前是开发模板，不是已实现、已安装Skill。M1将它复制到`.codeartsdoer/skills/teacher-courseware/`并实现入口。根SKILL.md必须name/description匹配目录；scripts/references/assets是支持目录；5M约束指ZIP导入，不是整个应用依赖总大小。[S04]

Skill CLI使用独立本地demo data-dir并取得独占锁，不同时绕过运行中的Web服务修改同一SQLite。两入口共享Python业务模块和Schema，不共享无控制的文件写入。无需为了API调用额外造MCP服务器；只有真实需要跨系统工具协议再扩展。

## 6. 使用记录与提交

原始会话保存在私人位置；公开仅脱敏摘录、session_id/日期/目标/所选模型/commit/测试结果索引。清除Key、token、私人路径、未授权资料、第三方敏感响应。脱敏后再次人工看一遍，不只跑正则。

至少覆盖需求、设计、实现、测试修复、原创Skill调用、部署。录屏中真实运行Skill和应用，说明共享模块。不能将离线fixture或以前别的Agent开发过程拼成此次码道历史。

《赛题对策》写清使用第三方模型与开源组件、原创部分和验证范围。不得为了“全程开发”重新生成伪造提交记录。
