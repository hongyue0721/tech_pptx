# T06 独立 Review 报告｜检索、覆盖与证据定位

- 审查会话：干净会话，只审 diff 与相关契约，未修改任何业务代码（仅写本报告）。
- 基线 commit：`2a05115`（T05 已提交状态）。
- 审查范围：`git status --short` + `git diff` + untracked 新文件。
  - 已跟踪改动：`backend/pyproject.toml`（+jieba、+rank-bm25）、`backend/uv.lock`、`backend/src/courseware_api/error_mapping.py`（+EVIDENCE_INVALID 422）、`process.md`、`validation-report.{md,json}`（仅 generated_at 刷新，PACK_STATIC_ONLY，无 T06 实质声明）。
  - 新增运行代码：`backend/src/courseware_core/retrieval/{tokenizer,bm25}.py`、`backend/src/courseware_core/evidence/locator.py`、`backend/src/courseware_core/services/coverage_service.py`。
  - 新增测试：`test_tokenizer / test_retrieval_bm25 / test_evidence_locator / test_coverage_service / test_retrieval_metrics / test_variant_retrieval`。
- 契约依据：docs/05 §2/§3/§7/§13、docs/04 §17–§19、docs/18（Retriever/EvidenceLocator 契约）、docs/07 §3、contracts/models.schema.json（ObjectiveCoverage/EvidenceSpan/EvidenceProposal/Claim）、AGENTS.md §4/§8。
- 验证命令：`backend/.venv/bin/pytest tests/ -q` → **310 passed / 0 failed / 0 errors / 0 skipped**，`[T06 实测] 检索命中率 10/10 = 100.0%`。命中率由 `test_retrieval_metrics.py:79` 在测试内真实计数（`hits/len(retrieval_cases)`），非硬编码；底线 `rate >= 0.8`（`test_retrieval_metrics.py:82`）。

---

## BLOCKER

### B1｜BM25Plus 的 delta 项使 `score > 0` 过滤失效，无关片段被塞入候选，coverage 据此过度宣称 supported

- 位置：`backend/src/courseware_core/retrieval/bm25.py:53`（`BM25Plus(corpus_tokens)`）、`bm25.py:68`（`if score > 0:`）、`bm25.py:84`（`scored[:limit]`）；放大点 `backend/src/courseware_core/services/coverage_service.py:44`（`max(... for hit in hits)`）、`coverage_service.py:51`（`len(hits) == 1 → partial`）。
- 问题：`rank_bm25.BM25Plus` 对每个查询词项加 `delta * idf`（delta=1）。当查询词在语料中至少出现一次（df ≥ 1）时，**所有**文档——包括与查询零词面交集的文档——都会获得 `delta * idf > 0` 的正分。于是 `bm25.py:68` 的 `if score > 0` 无法过滤无关片段，它们照样进入 `scored` 并被 `[:limit]` 纳入返回集。
  - 仅当查询词全语料不存在（df = 0）时 BM25Plus 返回 0，`test_no_results_returns_empty_not_default`（"量子隧穿效应"）恰好走这条路径而通过，掩盖了 df ≥ 1 时的污染。
- 复现证据（/tmp 探针，语料 a=真相关、c/d=完全无关）：
  - `search_chunks(query="优先级分组")` → `a score=7.029(词面交集=['优先级','分组'])`、`c score=2.773(交集=[])`、`d score=2.773(交集=[])`。无关片段 c、d 以正分入候选。
  - `evaluate_goal_coverage(goals=["优先级分组"])` → `status=supported`，`chunk_ids=['a','c','d']`。真相关只有 a 一条，本应触发 `len(hits)==1 → partial` 保护，但 delta 噪声把 `len(hits)` 撑到 3，配合 `ratio=1.0` 直接判 supported，并把两条无关片段列为支持证据。
  - 演示语料规模小（12–14 chunk），limit=12 时真相关 < 候选数 → 必现。
- 依据条款：
  - docs/05 §2「从多个文档尽可能覆盖，但**不能为多样性塞入不相关证据**」；§13「缺口在大纲阶段就给教师」——把无关片段当证据会掩盖真实缺口。
  - docs/18 Retriever 契约「无结果返回空不插入默认教材」的精神：有结果时同样不得混入不相关教材。
  - docs/05 §2「BM25 分数不是概率」：delta 项使无关片段与弱相关片段的分数不可比，`score` 排序在候选层面失真。
  - AGENTS.md 修改前自检「是否可能创建出看起来成功但关系不一致的数据」——supported + 无关 chunk_ids 正是不一致数据。
- 测试为何没拦住（维度B 关联）：`test_relevant_chunk_ranks_first`（`test_retrieval_bm25.py:78`）只断言 `hits[0]` 相关 + 分数降序，未断言"结果集不含零交集片段"；命中率测试判"至少命中一个相关页"，无关片段混入不影响"命中≥1"。整组测试对 delta 污染是盲的。
- 建议修法（择一并固化）：
  1. 过滤条件由 `score > 0` 改为"真实词面命中"：保留 `query_tokens ∩ tokenize(row.text) ≠ ∅` 的文档才入候选（最直接，且与 coverage 的 `_term_coverage` 语义一致）；或
  2. 对 BM25Plus 分数减去其 delta 基线（`delta * idf`）后再判正；或
  3. 换 `BM25Okapi` 并显式处理小语料负/零 idf（如 idf 取下界 0），但需重跑命中率实测确认不回退。
  - 无论哪种，补两条回归测试：① `search_chunks` 返回的每个 `RankedChunk` 必须与 query 有词面交集；② coverage 判 supported 时 `chunk_ids` 全部为真词面命中候选，且"仅 1 条真相关"必须落 partial 而非 supported。

---

## NONBLOCK

### N1｜tokenizer 过滤单字中文词，合法单字术语检索不到
- `retrieval/tokenizer.py:32`（`len(word) >= 2`）。实测 `tokenize("熵") == []`，`search_chunks(query="熵") == []`，`coverage("熵") == unsupported`——即便语料满是"熵"。中文单字术语（熵/波/场/力/能/功/热/电/磁/光/酶）会恒判"未找到支持"。docs/05 §2 只要求"中文 jieba 与英文/代码标识符并行保留"，未要求滤单字，属实现自加策略。缓解：note「建议调整目标表述」引导改写。建议：单字目标回退字符级或保留单字并 IDF 降权；或在 docs/05/process 明示该限制并加测试固化风险，避免演示目标踩坑。

### N2｜locator 用 `str.count` 判歧义为非重叠计数，重叠周期 quote 漏判
- `evidence/locator.py:34`（`row["text"].count(quote)`）、`locator.py:47`（`.index(quote)`）。实测 text="前言 aaa 结尾"、quote="aa"：`count=1` 判唯一、`start=3` 取第一次，但"aa"在"aaa"中重叠出现 2 次。违反 docs/04 §19「重复 quote 需补上下文，不随意匹配第一次」的精神（重叠重复也是重复）。真实中文自然文本少触发，但代码/数字/叠词可能。建议：改用重叠 `finditer` 计数，或对 `start` 之后再 `find` 一次确认唯一。

### N3｜coverage 测试缺 partial 与"偶然命中不得 supported"负向用例；supported note 为空
- `test_coverage_service.py` 无 partial 断言、无"词面偶然命中"负向用例（partial 路径经探针确认可达，但套件未固化）。`coverage_service.py:57` supported 时 `note=""`，未带"词面判定，建议教师/语义复核"措辞，与 docs/05 L4「展示自动核验通过，建议教师复核」的诚实性略有距离。建议：补 partial/偶然命中测试；supported 也带轻量 note 或在调用方（T08）标注词面来源。

### N4｜命中率底线 0.8 / corpus_revision=2 / limit=8 为硬编码
- `test_retrieval_metrics.py:70-72,82`。rate 计算真实（好），但阈值常量可被未来回归静默下调。建议：注释锁定 0.8 的理由并链接 docs/05 §7「固定测试集实际计数，绝不把模板 100% 当实测」，防止被改成 0.5 凑过。

### N5｜bm25 SQL 无 LIMIT，全量 rows + tokenize + RankedChunk.text 入内存
- `retrieval/bm25.py:37-50`。每次查询全量现建索引，语料与每条全文常驻内存。演示规模（约 ≤500k 字符）可接受，但规模上限未文档化，也无软保护。建议：在 docs/05 或代码注释记录"P0 现建索引规模假设"，为 T08/后续索引缓存留扩展点。

### N6｜精确短语加成对自然语言长 query 几乎不触发，且中文词无对应加成
- `retrieval/bm25.py:63`（`lowered_query in text.lower()` → +1.0）需整条 query 为片段子串，长自然语言查询几乎不可能命中；`bm25.py:66`（ASCII token +0.5）只对 ASCII 词生效，中文词无精确加成，行为不对称。`test_retrieval_bm25.py:126` `test_ascii_identifier_query_matches_whole_word` 仅断言 `isinstance(hits, list)`（恒真废断言）。建议：补"ASCII 标识符整词命中优于其碎片/无关片段"的有效断言，或简化加成逻辑为可测的单一规则。

### N7｜变体测试未做"重排后页码异于原件"的对照断言
- `test_variant_retrieval.py:59` 只验证 chunk 偏移落在其所属 `page_text` 的自洽性，未对照同一内容在原件 vs 变体的 `pdf_page` 差异。变体数据确已重排（原件页0="课程范围与学习目标"，变体页0="先问能否打断，再问谁先服务"），故可加对照。"不特判"的负向保证目前靠 grep（运行代码无按文件名/特定词匹配，已确认）+ 正向命中测试，建议补页码对照以强化验收 4。

### N8｜归属确认（非缺陷，记录判断）
- docs/05 §2「去重复后每页最多 8 片段、约 8000 字符」属**计划上下文组装**职责（T08 Planner/Generator），T06 Retriever 返回 Top12 候选正确，本任务不应裁剪。`coverage_service` 无 HTTP 路由属 T08 Planner 接线（docs/18 `Planner.create` 调 coverage），非调用方缺口。`ObjectiveCoverage.chunk_ids` 最多 `TOP_K=12 ≤ maxItems=20`（schema:785）自洽；note 为 `str maxLength=500`（schema:793），supported 时 `""` 合法（minLength=0），无独立 `MissingEvidenceNote` 类型——任务书所述类型名与实际契约以 schema 为准。

---

## 维度核对结论

- A（阻塞级）：
  - revision 累积快照 `<=` 与 docs/04/07 一致，且由 `test_revision_snapshot_is_cumulative_and_excludes_future`、`test_chunk_from_other_revision_rejected`、`test_coverage_binds_corpus_snapshot` 三处固化"未来不可见"——通过。
  - locator 拒绝跨项目/跨 revision/不存在/歧义 quote，偏移全服务端填充、`EvidenceProposal` 仅 chunk_id+quote 无自报通道——通过（重叠边界见 N2）。
  - coverage 词面偶然命中过度宣称 supported——**B1**。conflict 规则层不假装判定（status 不产 conflict，注释诚实）——通过。
  - "评估答案不得被运行读取"：grep 运行代码 `src/` 无任何路径读 `demo-data/expected|evaluation|reference_*|cases.json`（仅 version_repository 的 `expected_base_version` 参数名，无关）；测试侧读取 `cases.json` 隔离清晰——通过。
  - 变体不特判：无隐藏文件名/内容映射逻辑（grep 确认），正向命中测试——通过（对照可加强见 N7）。
  - BM25Plus 未破坏"分数非概率"表述纪律：src 无任何把 score 当 probability/confidence 的代码——通过（但 delta 使候选层分数不可比并入 B1）。
  - 命中率 10/10 真实计算、底线 0.8 不可静默放宽（阈值常量风险见 N4）——通过。
- B（测试假绿）：命中率/排序测试对 B1 污染盲——并入 B1；tokenizer 含 `or True` 恒真断言（`test_tokenizer.py:13`，line12/14 仍有回归检测力）、ascii 检索废断言——N6/N3。
- C/D：见 N1–N8。

---

## 结论

**需修复后提交。** 唯一阻塞项 B1（BM25Plus delta 污染 → 塞入不相关片段 + coverage 过度宣称 supported，且现有测试对其盲）必须修复并补回归测试；B1 修复须重跑命中率实测确认不回退。N1–N8 进 backlog，其中 N1/N3 与演示诚实性相关，建议随 B1 一并处理或在 T08 前明确记录。


---

## 修复闭环记录（Builder 2026-09-19，先失败用例后修复）

- **B1 已修**：`search_chunks` 增加词面交集门槛——与查询 token 集合零交集的片段直接排除（BM25Plus delta 常数项给所有片段正分的事实被显式压制），精确命中加成保留。回归 `test_chunks_without_surface_intersection_are_excluded`（红烧狮子头片段不得混入"优先级分组"候选）。修复后命中率实测仍 10/10，无召回回退。
- **N1 已修**：tokenizer 全单字中文查询兜底（多字词与 ASCII 皆空时保留 CJK 单字），`test_single_char_cjk_query_survives_fallback`（"熵"不再恒空）。
- **N2 已修**：locator 重叠计数（find 逐位推进），"aba"∈"ababa" 判 2 次=ambiguous，`test_overlapping_duplicate_quote_is_ambiguous`。
- **N3 已修**：单真相关候选场景测试入库（`test_single_relevant_chunk_stays_partial`）；supported note 为空符合契约 minLength=0，partial/unsupported 均有可见 note。
- **N4 已修**：命中率底线提取为 `HIT_RATE_FLOOR=0.8` 常量并注明下调需负责人批准。
- **N6 已修**：tokenizer 测试两处恒真废断言改实断言（setpriority 不得单独出现）。
- **N5/N7 部分处理**：N5 规模边界以注释固化（500k 字符内现建索引可接受，缓存/增量留 T15 评估）；N7 变体页码自洽已断言（page_text[start:end]==text 且内容含查询词），刻意不加"页码必须不同"断言——重排未必移动目标页，脆弱断言反而掩盖真问题。
- **N8 归属确认**：每页 8 片段/8000 字符裁剪属 T08 计划上下文组装职责；coverage 无 HTTP 路由属 T08 消费方；chunk_ids 12≤20、note≤500 自洽。

**修复后回归**：pytest **315 passed**（+5 条）退出码 0；validate_pack 23/23；frontend build PASS；命中率实测 10/10 不回退。B1 修复后验收项 1/2 达成，四项全达。
