# 数据模型与一致性约束

机器约束以 `contracts/models.schema.json` 为准；本文件定义不能只用JSON Schema表达的跨对象关系。结构合法不等于业务有效。

## 标识与版本

所有对象ID由服务端生成，不把原始文件名用作主键或路径。示例中的简短ID仅为易读。Deck版本为单项目单调递增整数；corpus_revision在新材料成功入库时递增。计划、生成、编辑、验证和导出全部绑定具体corpus_revision与deck_version。

文档内容按SHA-256去重：同项目同文件重复上传返回原material，不增加revision。不同项目不能跨用户泄露重复文件是否存在。文件名只作展示并转义。

## 源文件与切块

Document保存id、项目、原文件名、私有存储路径、sha256、页数、解析版本和质量报告。DocumentPage保存从1开始的PDF物理页、可选印刷页标签、归一化正文、正文hash和警告。

归一化固定：CRLF/CR→LF，Unicode NFC，删除NUL，整页首尾strip；不折叠正文空格、不改变数字、不合并跨页内容。先规范后定位。后续修改归一化算法必须增加extractor_version并重新建索引，不让旧引用偏移静默失效。

Chunk永不跨物理页，优先段落/句子边界，目标600—900字符、上限1200字符；重叠不超过100字符。保留页内起止字符偏移。短页不强行拼页。记录chunk_id、document_id、pdf_page、start/end、text、text_sha256、tokenizer_version。

EvidenceSpan引用chunk_id、document_id、pdf_page、chunk内start/end及quote。模型只提议chunk_id+quote（提案类型ProposalSlide/ProposalIllustrationBlock与存储类型隔离，权威字段在Schema层即不可由模型填写）；服务端确认chunk属于本批实际提供给模型的片段集合、quote是归一化chunk的唯一连续子串后填充偏移和页码。重复quote需补上下文，不随意匹配第一次。不接受模型自填的页码/来源作为事实。

## DeckSpec

`schema_version / project_id / version / corpus_revision / course / claims[] / slides[]`。

每个Claim有id、text、kind（direct或derived）、evidence_refs。derived需要非空rationale，且推论不能超过证据前提。事实块只存claim_id，由渲染器取对应text，避免“核验了A、页面展示B”。教学提示和课堂假设独立为teaching与illustration块，仍需审查是否偷塞事实。

每页有稳定slide_id、标题、四类layout之一、blocks。教师说“第四页”时前端发送当时选中slide_id与base_version，不以易漂移的页号执行修改。页顺序是slides数组，页号是显示属性。

## 候选与应用

CandidateChange保存base_version、corpus_revision、原始指令、改动页、完整候选DeckSpec、差异摘要和ValidationReport；模型不直接改变current_version。

原子提交时再检查base_version与corpus_revision。通过后分配新版本，写版本文件并更新指针。冲突返回409；前端展示“内容已变化，请刷新后重试”，不自动覆盖。

快照包括DeckSpec与验证报告，而不是只存PPTX。恢复旧版本时复制成新版本，记录restored_from；不回退版本计数器。P0仅允许恢复同当前corpus_revision的旧版本；语料已变化则返回CORPUS_CHANGED，重新确认计划并生成，旧语料全量重核验属于P1。P0不单独删除材料，整项目可删除；删除项目需确认且不能在活动任务中执行。

## 验证报告不是模型自证

ClaimVerification分别记录引用定位（located/invalid）与语义核验（supported/partial/unsupported/conflict/not_checked）。教师确认字段独立存在；不是把用户点击“应用”写成“AI已确认事实正确”。记录model_id、prompt_version、checked_at、原始结果hash。

定义executable gate：所有正式fact的引用可解析、语义核验supported，所有跨对象关系有效，结构/布局通过，unbound_assertions为空且使用中的claim核验恰好全覆盖。存在partial/unsupported/conflict/not_checked则候选不准应用为正式版本。教师可先删除该教学目标或补材料再生成，不能点一次确认就给未经支持的内容盖绿章。

## 数据库建议表

projects、materials、pages、chunks、plans、deck_versions、changes、jobs、artifacts、idempotency_keys。字段约束：外键开启、id唯一、(project_id,version)唯一、同项目同时最多一个活动写任务。

SQLite不保存大文件内容。产物先写同文件系统临时目录、fsync/原子rename，再提交指针。失败不得留下指向不存在文件的成功记录。启动清理孤儿临时文件；未结束jobs标interrupted。
