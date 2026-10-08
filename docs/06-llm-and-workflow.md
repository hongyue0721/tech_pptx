# 模型接口与有界工作流

## 两种模型配置

DEV模型：由码道客户端使用，必须支持稳定工具调用、多步工具回传和所需流式协议。APP模型：由FastAPI业务核心调用，P0只要求文字理解和受约束JSON，不必授予工具调用。两者可同供应商，但Key、用途、预算与日志分开。

使用OpenAI兼容并不代表一定兼容所有参数。Chat Completions与Responses不是同一接口；本项目P0Adapter只实现Chat Completions。不默默把一个仅支持Responses的端点当已兼容。

## 能力探测

M0用短输入测试：普通文本、中文UTF-8、结构化JSON、错误体、超时、429、流式工具消息（DEV）、多轮tool_result、上下文超限。记录provider/model/API路径、必要参数和禁用参数；不能靠名为reasoning的布尔开关判断模型真正能力。

temperature、response_format/json_schema、max_tokens或max_completion_tokens、reasoning配置均按探测结果发送。不支持strict JSON时用纯JSON提示+本地Schema校验+一次格式修复；禁止用正则把任意自然语言“修”成貌似正确结构。不能无条件设temperature=0给不支持该参数的模型。

## Adapter职责

`complete_json(stage, messages, schema, request_context) -> TypedResult`：处理HTTP协议、请求ID、超时、用量、有限重试和日志脱敏。领域服务定义plan_course/generate_content/plan_edit/verify_claims，不在UI中散落HTTP调用。

基准超时：connect10秒、read120秒、单调用总预算180秒；项目任务总预算600秒。均为可配置工程上限，M0按实测修订。计费采用返回usage；缺失时标unknown，不写0。

## 有界流水线

1. 解析并确认资料。
2. 按目标查询，生成coverage与LessonPlan；停在教师确认。
3. 每批2—3页生成候选内容，保留证据上下文。
4. 本地Schema与引用定位；一次修复机会。
5. 批量语义核验；发现问题只修受影响claims，复核一次。
6. 结构检查→候选DeckSpec→教师确认→提交版本。
7. 独立导出job生成PPTX；预览失败不回滚已生成版本。

默认全局活动工作任务1个，单次模型并发最多2；如供应商限制更严取较小值。一次生成最多24次实际模型请求（含重试、修复和复核），耗尽返回BUDGET_EXCEEDED，不按剩余进度自动增加费用。

## 重试矩阵

429/临时5xx/网络连接失败：在剩余任务预算内至多一次退避重试，尊重Retry-After上限；不得多个层同时重试造成指数放大。

401/403/模型不存在/不支持参数：直接失败并给配置错误；不重复收费尝试。JSON不合法：一次带校验错误的修复，再失败则结束。语义不支持：补检索或修受影响事实一次，无依据则blocked，不当网络错误重试。

取消请求：检查取消位并停止后续步骤；供应商已接收的推理可能仍收费，不承诺中止后零成本。服务重启后的未知调用不自动重放，由用户选择重新运行。

## Prompt治理

提示词按任务拆为plan/content/edit/verify四份，版本化。每条含允许的内容类型、输入数据分区、Schema、无法支持时返回路径。系统约束优先于材料文本。不得在提示词植入主Demo的已知结论或文件名特判。

日志存stage、model、耗时、usage、attempt、input_hash、prompt_version，不记录完整教师材料或Key。仅在用户明确允许时将脱敏输入输出用于私有排错。

## 费用控制

配置每任务token上限与项目累计请求上限；可选价格表由负责人确认。自动预算不能依赖可能缺失的usage，至少以请求次数/输入字符/最大输出做保守边界。未明确预算不得自行付费调用。
