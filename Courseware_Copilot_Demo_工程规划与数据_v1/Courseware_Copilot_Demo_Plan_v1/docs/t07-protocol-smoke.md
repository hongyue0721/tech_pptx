# T07 真实协议 smoke 报告（2026-09-19）

- 授权：负责人 2026-09-19 批准（预算授权+提供端点与Key，Key 仅内存 export，未落盘未入库）。
- 环境：backend venv Python 3.12.14 / httpx 0.28.1；端点 `https://api.deepseek.com`（Chat Completions），模型 `deepseek-flash`。凭据不记录。
- 探测脚本：/tmp/t07_smoke.py（一次性，不入库；逻辑以本报告+回归测试为准）。
- 成本实测：6 次调用，可见 usage 合计约 390 tokens（P2 153 + P5 237，P1/P3/P4/P6 未计或零）。

## 结果矩阵（五态）

| 探针 | 内容 | 状态 | 实测 |
|---|---|---|---|
| P1 | 普通文本+中文UTF-8 | **PASS** | HTTP 200，2.12s，回复"探针好"，provider request_id 为 UUID |
| P2 | 结构化JSON：`response_format={"type":"json_object"}` + `temperature=0` | **PASS** | HTTP 200，0.81s，content 可直接 json.loads 且结构符合 SemanticVerdicts；usage 完整返回（含 reasoning_tokens=32 扩展字段，解析器按白名单取三键不受影响） |
| P3 | 错误体：无效Key | **PASS** | HTTP **401**（adapter 分类 ModelAuthError、不重试，与单测语义一致） |
| P4 | 错误体：不存在模型 | **PASS** | HTTP **400**（该供应商对未知模型返回 400 而非 404；adapter 分类 ModelConfigError、不重试） |
| P5 | ChatCompletionsAdapter.complete_json 端到端真实调用 | **PASS** | attempts=1，typed 校验通过（checks_len=1），usage known（total 237），request_id 回填 |
| P6 | 取消位真实环境拦截 | **PASS** | cancel_check=True → JobCancelled，零 HTTP 请求 |
| P7 | 429 Retry-After 实际行为 | **NOT_TRIGGERED** | 未主动触发限流（无意义刷配额）；退避/封顶逻辑由 MockTransport 单测覆盖 |
| P8 | 超时（connect10/read120） | **NOT_RUN** | 不人为制造断网；超时分类由单测覆盖 |
| P9 | 流式工具消息/多轮 tool_result | **N/A** | APP 模型 P0 不要求工具调用（docs/06），DEV 模型能力与本项目无关 |

## 能力位结论（回填配置）

- `APP_LLM_PROTOCOL=chat_completions`：该端点为 Chat Completions，P0 adapter 匹配。
- `APP_LLM_SUPPORTS_JSON_MODE=true`（P2 实测）
- `APP_LLM_SUPPORTS_TEMPERATURE=true`（P2 实测，temperature=0 正常）
- usage 正常返回 → 预算保守边界（请求次数/输入字符/最大输出）仍按 docs/06 保留，不依赖 usage。
- 供应商错误语义备忘：未知模型=400（非404）、无效Key=401；两者 adapter 均不重试、typed 配置错误。

## 诚实声明

- 以上为真实外部模型调用结果（非 mock）；P7/P8 未触发项如实标注，对应逻辑仅以 MockTransport 单测背书。
- 响应含供应商扩展字段（reasoning_tokens、cache 计数），adapter 按已知三键提取，未知字段忽略不报错。
- 本次 smoke 为 deepseek-flash 单端点结论；换供应商须重跑探测（脚本可复写）。
