# 内部接口与施工边界

以下是目标协议，不是当前实现。用这些边界拆任务；不要让所有函数都返回dict[str,Any]并把错误留到前端。

## 目录建议

```text
backend/src/courseware_core/
  models/          # 与contracts等价的Pydantic类型
  services/        # 项目/资料/计划/生成/候选/版本/导出
  materials/       # pypdf解析、规范化、切块
  retrieval/       # tokenizer、BM25、覆盖
  evidence/        # locator、语义核验编排、关系验证
  llm/             # 单provider适配、能力表、预算
  render/          # DeckSpec→选定导出器；preview
  storage/         # SQLite repositories与原子文件
  jobs/            # 单Worker、取消和状态
  cli.py           # Skill入口，调用services
backend/src/courseware_api/  # FastAPI路由，只调services
frontend/src/               # Vue视图/composables/api client
contracts/                  # Schema/OpenAPI
app-prompts/                 # 四种提示，不塞演示答案
```

## 接口契约

`MaterialParser.parse(path, limits) -> ParsedDocument`：输入已限额的受控路径，输出逐页text/quality；无网络、无LLM、无跨页合并。PDF_ENCRYPTED/TEXT_UNAVAILABLE等typed异常。不直接写DB。

`Chunker.split(document_id, page, extractor_version) -> list[DocumentChunk]`：纯函数；归一化后坐标、页内边界、hash可重现。Project/corpus由service填，不能从PDF读取。

`Retriever.search(project_id, corpus_revision, query, limit) -> list[RankedChunk]`：存储查询必须带项目/revision；结果score仅作排序。tokenizer版本入元数据，中文和ASCII词保留；无结果返回空不插入默认教材。

`EvidenceLocator.resolve(proposal, permitted_chunks) -> EvidenceSpan`：仅接受当前允许chunk集合；唯一原文子串匹配，服务端填document/page/start/end。不改quote使其看起来相符。

`LLMProvider.complete_json(stage, schema_name, messages, context) -> TypedCompletion`：只负责协议/格式/有限重试，不修改业务状态。返回value/usage/provider_request_id/attempts；usage可unknown。JobContext含deadline/cancel-check/call-budget/project/revision/trace，所有重试从同一预算扣。

`Planner.create(project, chunks, context) -> LessonPlan`：生成draft与coverage，不自行confirmed。`Planner.confirm(plan, teacher_request) -> LessonPlan`：校验有效目标/顺序/引用，缺口目标必须被明确移出接受范围，不能假绿。

`Generator.propose(confirmed_plan, base_deck, context) -> CandidateChange`：先ContentProposal，再locator，转存储Claim；再semantic verifier与关系/layout检查。不写current，不在格式修复时变更教师范围。

`EditService.propose(deck, request, context) -> CandidateChange`：使用EditProposal。限制目标页与受支持动作，copy-on-write共享claim；split两页须完整、非目标hash不变。模型操作里不允许路径/SQL/任意URL。

`Verifier.check(claims, exact_evidence, context) -> ValidationReport`：引用定位结果由代码产生；模型只返回SemanticVerdicts。引用核验不存在时不得把model verdict当定位成功。零fact的封面无需调用语义模型。

`VersionRepository.commit(candidate, expected_base, expected_corpus) -> DeckVersion`：检查可提交和教师ack，原子新版本；`restore`只同corpus创建新版本。版本号由服务端分配，Candidate里的拟议version不可作为全局权威。

`Exporter.export(deck_version, output_dir, render_config) -> ExportArtifact`：只消费已提交DeckSpec；不调LLM、不下载依赖、不改内容；返回path/hash/size/page_count/tool_version/检查报告。用subprocess参数数组，不能shell拼接。

`PreviewService.describe(version) -> PreviewManifest`：可能是outline、PPTD图或PPTX图；使用同版artifact，不越权返回文件路径。PPTX真实打开仍需要人工验收。

## CLI与HTTP错误映射

core抛结构化DomainError(code,message,details)，由HTTP/CLI分别映射；不把FastAPI HTTPException渗透到core。CLI退出码建议0成功，2输入/缺资料，3冲突，4环境/模型，5导出失败；最终选定映射写进API/Skill文档。

JSON结果不混stdout调试行；日志走stderr并脱敏。调用模型/渲染不可持有长SQLite事务；领取/提交各用短事务，外部I/O在外执行，再带version/revision CAS提交。

## 模型输出与服务端状态

模型用PlanProposal/ContentProposal/EditProposal/SemanticVerdicts；存储/HTTP用LessonPlan/DeckSpec/DeckPatch/ValidationReport。不要把两类Schema混用，让模型填充它不应决定的页码、版本、已确认状态和成功标志。

结构预览直接读DeckSpec；若Renderer最终发现放不下，不能偷偷删正文，应明确失败或返回需拆页的候选需求。字体和资源由渲染配置白名单决定，不作为大模型自由参数。
