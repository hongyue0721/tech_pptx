# 规划包静态校验报告

时间：2026-09-22T07:46:03.778462+00:00
范围：**PACK_STATIC_ONLY**。通过23项，失败0项。

这只验证文档/契约/生成的测试资产，不表示应用、模型、码道或PPTX链路已通过。

| 检查 | 结果 | 实际检查内容 |
|---|---|---|
|JSON Schema definitions and references|PASS|49 definitions, internal refs resolve|
|OpenAPI and api.md route consistency|PASS|21 route operations, parameters/responses/local refs checked (not full external OpenAPI conformance certification)|
|Schema sample: demo-data/lesson_request.json|PASS||
|Schema sample: contracts/examples/create_project.json|PASS||
|Schema sample: contracts/examples/job_interrupted.json|PASS||
|Schema sample: demo-data/expected/reference_deck.json|PASS||
|Schema sample: demo-data/expected/split_patch.json|PASS||
|Schema sample: demo-data/expected/semantic_wrong_quote_claim.json|PASS||
|Schema sample: demo-data/expected/relation_invalid_deck.json|PASS||
|Fixture chunk hashes and physical PDF pages|PASS|12 page-bounded chunks validated against actual PDF text|
|Reference Deck relations and exact citations|PASS|9 exact claim references, 8 slides; no semantic-model truth claim|
|Schema-valid but relation-invalid negative control|PASS|Deliberately invalid relation rejected after schema passes|
|Semantic counterexample construction, not semantic verification|PASS|Fixture has valid quote but reversed meaning. Actual semantic verifier NOT_RUN; this test only confirms negative control construction.|
|Reference split-patch invariants|PASS|Reference patch construction preserves other slides and claims. Future app patch engine NOT_RUN.|
|Generated PDF positive and negative properties|PASS|Main PDFs 12 text pages; supplementary 2; variant 4; deliberate encrypted/scan/blank/malformed/mixed properties checked|
|Demo data manifest, byte lengths and SHA-256|PASS|38 data files checked|
|Evaluation case references|PASS|39 evaluation definitions; no application execution implied|
|Task dependency DAG and initial truth state|PASS|18 task cards, acyclic dependencies and read paths|
|Skill template metadata and scope|PASS|Valid frontmatter and template disclosure; 3949 source bytes, not a real CodeArts import test|
|Markdown local links|PASS|Markdown clickable local links resolve|
|Source marker registration|PASS|21 source records, marker identifiers checked; relevance manually reviewed|
|Package exclusion rules and placeholder configuration|PASS|No standalone font files, live .env, known runtime directories or non-placeholder API key in template|
|Required canonical documentation|PASS|Required canonical documents present|

## 未运行

- CodeArts account permissions and custom model tool loop
- AnyUI npm installation / Vue production build
- Actual runtime model quality / billing / latency
- Application API / SQLite jobs / browser E2E
- ppt-edit asset authorization and exporter execution
- PPTX output / PowerPoint or WPS editing
- Cloud deployment / competition eligibility confirmation

PDF页面人工目视抽查见[记录](docs/pdf-visual-review.md)。
