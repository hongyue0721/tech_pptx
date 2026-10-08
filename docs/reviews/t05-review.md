# T05 独立 Review 报告 — PDF 导入、规范化与切块

- 工程根：`Courseware_Copilot_Demo_Plan_v1`
- 基线 commit：`b5cf4da`（T04）；审查对象：全部未提交改动（`git status` 11 改 + 14 新文件，核心在 `backend/`）
- 审查方式：干净会话，只审 diff 与相关契约，未改动任何仓库代码（本报告除外）
- 契约依据：`docs/04-data-model.md`、`docs/11-security-privacy.md`、`docs/18-core-interfaces.md`、`docs/07-jobs-and-versioning.md §2/§3`、`contracts/models.schema.json`、`contracts/routes.json`、`contracts/openapi.json`、`AGENTS.md`、`tasks/tasks.json`（T05 验收四项）

## 验证执行

- `.venv/bin/pytest tests/ -q` → **270 passed**（与声称一致，退出码 0）
- 自建 `/tmp` 探针（不入库）实测：
  - PROBE1 SQLite `LENGTH(text)`：`'中文abc'` → 5（字符）而 `LENGTH(BLOB)` → 9（字节）。**确认 chunks 表 `SUM(LENGTH(text))` 统计的是字符数**，与 docs/11 §7「500000 抽取字符」语义一致（见 N7）。
  - PROBE2 负例 fixture 真实性：`encrypted.pdf`（is_encrypted=True）、`blank.pdf`（1 页空文本）、`scanned_only.pdf`（1 页空文本）、`malformed.pdf`（构造即 `PdfStreamError`）、`mixed_text_scan.pdf`（p1 有文本 / p2 空）——**均为真实文件**，非合成，符合 B 维度「负例用真实文件」。
  - PROBE3 文件名转义：`../../etc/passwd.pdf`→`passwd.pdf`、`a\x00b.pdf`→`ab.pdf`、`a<U+2028>b<U+2029>c.pdf`→`abc.pdf`、`/abs/x.pdf`→`x.pdf`、`C:\evil\..\win.pdf`→`C:evilwin.pdf`、300 字符→截断 255、`..`/`.`/`\x01\x02\x03`→`unnamed.pdf`、`e\u0301.pdf`→`é.pdf`（NFC）。**转义面覆盖完整**。
  - PROBE4 **重复上传在配额边界被误拒**：`max_files=1` 已有 1 份时重传同一文件 → 抛 `PAYLOAD_TOO_LARGE`（应为 `duplicate=true`）；`max_project_bytes` 恰满时重传同一文件 → 同样抛 `PAYLOAD_TOO_LARGE`。**复现 B1**。
  - PROBE5 pypdf stderr：对正常/损坏/加密 fixture 抽取，`2>` 捕获 **无 "invalid pdf header" 等 stderr 噪音**（5.9.0 未复现，见 N16 观察）。
  - 交叉确认：`grep reference_chunks|demo-data backend/src` → **运行路径未引用 expected 目录/参考数据**（AGENTS.md §8 达成）。

---

## 总体判断

T05 主体质量高：归一化、切块偏移自洽、限额数值、去重跨项目隔离、corpus 递增原子性、占锁建 job 同事务（N1 收口）、claim_next 写 kind 持锁校验（N8 收口，含专项测试）、文件名转义、路径守卫、202 语义、每页告警、端到端真走 worker 线程均**成立**。DB 层偏移对账（`test_parsed_page_offsets_and_hashes_hold`）与 reference 回归（`test_reference_chunks_reconcile`）为真实断言，非假绿。

发现 **1 个 BLOCKER**（去重与限额检查顺序倒置，边界处误拒合法重复上传），另有 **16 个 NONBLOCK** 进 backlog。

---

## BLOCKER

### B1 — 去重检查位于文件数/字节数限额之后，配额边界处合法重复上传被误拒 413

- 位置：`backend/src/courseware_core/services/material_service.py:83-99`（限额 `:83-91` 先于去重 `:93-99`）
- 问题：`upload` 顺序为 ①项目存在 ②单文件字节 ③magic ④`file_count >= max_files` → `PAYLOAD_TOO_LARGE` ⑤`total_bytes + len(data) > max_project_bytes` → `PAYLOAD_TOO_LARGE` ⑥`find_duplicate`。因 `stats()`（`material_repository.py:114-121`）统计的是**全部** material 行（含待去重命中的那一条本身），当项目已达 `max_files` 或 `total_bytes` 恰满时，**重传一份已存在的相同内容**（本应命中去重、返回原 material、不增 revision、不占新配额）会在第 ④/⑤ 步被 `PAYLOAD_TOO_LARGE` 拒绝，永远走不到第 ⑥ 步的去重分支。PROBE4 两条路径均复现。
- 依据：`docs/04 §9`「同项目同文件重复上传返回原 material，**不增加 revision**」——去重是无条件语义，与配额无关；`docs/11 §7`「单项目最多 5 份/100MiB」是**新增文件**的限额，重复命中不新增文件即不应受该限额拦截。违背 T05 验收项 3「限额/跨路径拒绝」与项 2 隐含的去重语义。
- 测试缺口：`test_duplicate_same_sha_returns_original_material`（`test_material_service.py:68`）仅在 1 份（未达配额）时测去重；`test_upload_rejects_when_project_full_of_files`（`:92`）用的是 `unique{i}` **不同内容**，恰好绕开了"配额满 + 重复"这一交集，故未暴露本缺陷。
- 建议修法：把 `find_duplicate` 命中即返回 `duplicate=true` 的分支**上移到 magic 校验之后、`file_count`/`total_bytes` 限额之前**（去重优先于配额，因为重复不消费配额）。补两条回归：(a) `max_files=1` 已有 1 份重传同内容 → `duplicate=true`、`COUNT(materials)==1`、`corpus_revision==0`；(b) `max_project_bytes` 恰满重传同内容 → 同上。

---

## NONBLOCK（进 backlog，不当场全面重构）

### N1 — HTTP 层"先整读入内存、后查限额"，与 docs/11 §7「HTTP 层先限流/长度」相悖
- 位置：`backend/src/courseware_api/api/routes_materials.py:31`（`data = file.file.read()`）；限额判定滞后于 `material_service.py:75`。
- 问题：路由无 Content-Length 预检，`file.file.read()` 将整份上传读成 `bytes` 后才在 service 层比较 `len(data) > 20MiB`。超大体（如数 GiB）在拒绝前会被完整缓冲（Starlette `UploadFile` 超阈值虽落磁盘临时文件，但 `read()` 仍一次性载入内存），构成内存放大攻击面。docs/11 §7 明确要求"HTTP 层先限流/长度"。当前值正确（20MiB），仅顺序/预检缺失。缓解：本地仅监听 127.0.0.1 + Basic Auth（docs/11 §29）。
- 依据：`docs/11 §7`。
- 建议：中间件或路由入口按 `Content-Length`/流式累计字节先行 413 拒绝，再交给 service 复核；解析侧另设超时/内存上限（docs/11 §7「解析子进程」，当前 worker 为线程非子进程，见 N16）。

### N2 — 字符数超限复用 `PAGE_LIMIT_EXCEEDED` 错误码，语义误导
- 位置：`backend/src/courseware_core/materials/parser.py:83-87`；`error_code` 亦映射为 413（`error_mapping.py:18`）。
- 问题：抽取字符超 `max_chars` 抛的是 `PAGE_LIMIT_EXCEEDED`（页限额码），与"字符限额"语义不符；`test_char_limit_exceeded_rejected`（`test_parser.py:77-80`）反而把错误码断言锁定为 `PAGE_LIMIT_EXCEEDED`，固化了误导。
- 依据：`docs/11 §7` 区分"200 物理页"与"500000 抽取字符"两类限额。
- 建议：新增 `CHAR_LIMIT_EXCEEDED`（映射 413），并更新该用例断言；typed 异常码应可区分两类限额来源。

### N3 — 非 `DomainError` 异常使 material 滞留 `parsing`（非 `failed`），成为吃配额的僵尸行
- 位置：`material_service.py:163-167`（`handle_parse` 仅 `except DomainError` → `set_failed`）；`parser.py:50` 的 `path.read_bytes()` 在 try 之外。
- 问题：若 `parse_pdf` 抛出非 `DomainError`（如原件被删/IO 错误 → `FileNotFoundError`，或 pypdf 内部未捕获异常），`handle_parse` 不 `set_failed`，material 停在 `parsing`，worker `finalize(failed)` 释放锁（锁链正确）但 material 永不为终态；`stats()` 仍计入份数/字节 → 永久占用配额，而 P0 无单材料删除（docs/04 §35）只能整项目删。
- 依据：`docs/04 §13` 状态语义、`docs/07 §6`。
- 建议：`handle_parse` 兜底 `except Exception` 亦 `set_failed("INTERNAL_ERROR"/映射码)` 后再抛；或 `parse_pdf` 顶部文件读取纳入受控 try。

### N4 — `upload` 先落盘后建 DB 行，DB 失败留下无指针终名孤儿文件；缺启动孤儿清理
- 位置：`material_service.py:116`（`_store_file` 早于 `create_with_job`）；`create_with_job` 抛 `ProjectBusy`/`ProjectNotFound` 时 `{material_id}.pdf`（终名，非 `.tmp`）已落盘。
- 问题：顺序"先文件后指针"符合 docs/04 §47「失败不得留下指向不存在文件的成功记录」，方向正确；但 `ProjectBusy` 分支会遗留一份无 DB 指针的终名文件（最多 20MiB）。全仓无孤儿清理实现（`grep` 仅见 artifact_store/material_service 注释「可被清理」，无 GC 代码），docs/04 §47「启动清理孤儿临时文件」未落地。
- 依据：`docs/04 §47`。
- 建议：worker/app 启动期扫描 `materials_root`，删除无对应 material 行的 `*.pdf`/`*.tmp-*`；或改为"先建 DB 行（占锁）成功后再落盘"，但需保证指针行有 `status='queued'` 且读取容错，权衡后仍推荐"落盘→建指针 + 启动 GC"。

### N5 — 去重命中不区分 status，失败材料被当"duplicate"返回，且失败材料长期吃配额
- 位置：`material_repository.py:99-105`（`find_duplicate` 仅按 `project_id+sha256`，不看 `status`）；`stats`（`:114`）计入 failed。
- 问题：一份内容此前因 `PDF_ENCRYPTED`/`PAGE_LIMIT` 等失败后，再传同内容返回 `duplicate=true` 指向 failed 材料（误导"已入库"）；且 failed 行长期占用 5 份/100MiB。P0 虽无单材料删除，但去重语义应明确"是否含失败态"。
- 依据：`docs/04 §9`（去重语义未含失败态定义）。
- 建议：明确 `find_duplicate` 是否排除 `failed`（倾向排除，让重传重新走解析），并在文档/契约注明失败材料配额回收仅靠整项目删除。与 B1 修复一并处理顺序。

### N6 — `save_parsed` 忽略 payload 的 `corpus_revision/project_id/document_id`，字段冗余易埋雷（D③）
- 位置：`material_service.py:180-192`（`split_page(..., corpus_revision=0)`，dump 出 rev=0 的 chunk）；`material_repository.py:190-208`（INSERT 用 `new_revision`、`material.project_id`、`material.id`，未读 `chunk["corpus_revision"]`）。
- 问题：当前**不是 bug**（DB 落的是正确 new_revision），但 chunk 载荷携带 `corpus_revision=0` 等占位值被静默丢弃，形成"看似权威实则忽略"的双源。若日后有人重构为"信任 payload"，会写入 rev=0。
- 依据：`docs/18 §29`「Project/corpus 由 service 填，不能从 PDF 读取」。
- 建议：要么把真实 revision 传入 `split_page` 让模型即权威、`save_parsed` 直接取用；要么在 chunker 层不接收 project/corpus（仅产偏移/text/hash），由 service 组装，消除占位假字段。

### N7 — `ready_page_budget` 字符预算按 chunks 汇总，较页文本略偏松（D④，语义正确但口径不一）
- 位置：`material_repository.py:130-136`（`SUM(LENGTH(text))` over chunks）。
- 问题：PROBE1 证实 `LENGTH(TEXT)` 返回字符数，与 docs/11「抽取字符」一致，**语义无偏差**；但 chunk 切分时剥离了段落边界空白（`_paragraph_spans` 去尾空白、`\n\n` 不入 chunk），故 chunk 字符和 < 页归一化文本字符和，而 parser 的 `max_chars` 用页文本 `len()`（`parser.py:82`）。两处口径不同，项目累计预算略偏松（漏计空白）。
- 依据：`docs/11 §7`。
- 建议：预算与 parser 限额统一口径（都用页文本 `pages.text` 字符和，或都用 chunk 和），并在文档写明"抽取字符"计法。

### N8 — `printed_page_label` 恒 None，PDF `/PageLabels` 未实现且差距未显式记录（D⑤）
- 位置：`parser.py:27,172`、`material_service.py:171`（恒 None）。
- 问题：docs/04 §13「可选印刷页标签」为可选，P0 不实现可接受；但 `process.md` T05 段未记录该差距，后续 EvidenceSpan/预览若依赖印刷页码会踩空。
- 依据：`docs/04 §13`。
- 建议：backlog 记「/PageLabels 抽取（可选）」，并在 `pages.printed_page_label` 注释标注 P0 恒空。

### N9 — 错误/告警文本内嵌异常类名，轻微内部细节外泄（D 维度：日志脱敏）
- 位置：`parser.py:56`（`unreadable PDF structure: {type(exc).__name__}`）、`:78`（`page extraction failed: {type(exc).__name__}`）。
- 问题：这些 message 经 `save_parsed` 存入 warnings_json，`GET /materials` 原样回给客户端，暴露 `PdfStreamError` 等内部类型。属轻微信息泄露（非密钥/路径），docs/11 §25 要求日志/故障信息脱敏。
- 建议：对外 message 用通用文案，异常类名/栈仅入服务端日志（stderr、脱敏）。

### N10 — 扫描页检测基于图片 XObject，纯矢量/Type3-only 图像页判为 `EMPTY_PAGE`（诚实性边界）
- 位置：`parser.py:88-105,119-137`。
- 问题：无文本且无图片 XObject 的纯矢量/Type3 图形页 → `EMPTY_PAGE`（而非 `SCAN_DETECTED`）；Type3 若 `extract_text` 产出乱码则被当"有文本"计入 usable 且无告警。**核心诚实性成立**：真正无文本的页一律告警且不计 `usable_pages`（`:39-40`），未声称"读完"。混合文件逐页告警亦成立。
- 依据：`docs/11 §9`「混合文件逐页告警，不声称没文本的页已读完」。
- 建议：process.md 已诚实声明"基于图片 XObject、未做视觉确认"；可补一句"纯矢量/Type3 页可能误判 EMPTY_PAGE"，P1 再增强。

### N11 — multipart 幂等指纹以 `\n` 拼接，域分隔依赖"文件名不含换行 + sha 定长"（A：指纹覆盖）
- 位置：`routes_materials.py:34-37`。
- 问题：指纹覆盖 路由+project_id+文件名+内容 hash，**影响结果的输入均已覆盖**（内容/项目/文件名/路由齐备，session 在 scope 中），无缺项；仅拼接以裸 `\n` 分隔，理论上文件名含 `\n` 可移位（python-multipart 实际禁止头内换行，故不可利用）。
- 依据：`docs/07 §2`。
- 建议：改长度前缀或对 filename 单独哈希后拼接，消除域分隔歧义（防御性）。

### N12 — duplicate 命中且原件仍 queued/parsing 时返回 `job_id=None`，调用方无"等待把手"（D①）
- 位置：`material_service.py:95-99`。
- 问题：第二次上传命中去重返回 `duplicate=true, job_id=None`，即便原件尚未 ready。契约 `job_id` 可空故合法，但客户端如何等待原件完成未定义（需按 `material_id` 轮询 `GET /materials`）。
- 依据：`contracts/models.schema.json`（`MaterialUploadAccepted.job_id` nullable）。
- 建议：在 api.md/契约注释写明"重复上传无 job，按 material_id 轮询状态"；或 duplicate 时回填原件当前 job_id（若可取）。

### N13 — 关键失败链与 B1 边界缺测试（B：非假绿，但覆盖有洞）
- 位置：`test_worker.py:113-123`（failed 用例仅断言 `status=failed`，**未断言自身项目锁 `active_job_id` 被释放**）；无"parse 失败经 worker→material failed→锁释放→可再上传"的 e2e。
- 问题：`finalize` 释锁逻辑对 failed 亦生效（`job_repository.py:157-162`，与 status 无关），行为正确，但"失败释放自身锁"这条 reviewer 点名要验证的链**未被任何断言锁定**（succeeded 路径 `test_worker.py:106-108` 有断言，failed 无）。B1 边界（配额满去重）亦无测试。
- 依据：`docs/07 §3`、T05 验收项 1/3。
- 建议：failed 用例补 `assert active_job_id is None`；新增 B1 两条去重-配额交叉用例；可选 e2e 用 `encrypted.pdf` 走 worker 断言 material=failed、锁释放、corpus 不变。

### N14 — `ParseLimits` 默认值与 `ProjectLimits` 双份限额常量并存（C）
- 位置：`parser.py:44-46`（200/500000）与 `material_service.py:39-40`（200/500000）。
- 问题：`handle_parse` 恒以 `ProjectLimits` 余量覆盖 `ParseLimits`（`material_service.py:159-162`），parser 默认值成为"平行死常量"，两处数值各自维护，改一漏一即漂移。
- 建议：单一来源（parser 默认引用 service 常量，或 parser 不设默认、强制显式传入）。

### N15 — 结构/命名小瑕疵（C）
- 位置：`material_service.py:71-74`（`upload` 用裸 SQL 查项目存在，而 `list_materials:138` 用 `ProjectRepository.get`，两径不一致）；`:124-125`（`except BaseException: raise` 为无操作占位）。
- 建议：统一经 `ProjectRepository` 判存在；删除空 try/except 或改为有意义的清理。

### N16 — 解析在 worker 线程内 in-process 执行，无子进程级超时/内存/输出隔离（C）
- 位置：`wiring.py:17-23`、`worker.py:109-136`。
- 问题：docs/11 §7 设想"解析子进程另设超时、内存与输出上限"；当前 pypdf 在 worker 线程内跑，恶意高解析成本 PDF（压缩炸弹/深对象）可拖住线程且无超时。另 pypdf stderr 噪音（"invalid pdf header"）PROBE5 未复现，但建议显式配 `logging.getLogger("pypdf")` 级别以免上游版本变动引入噪音。
- 依据：`docs/11 §7`、`AGENTS.md §3`（子进程参数数组/超时/限额）。
- 建议：P0 至少给解析设墙钟超时与页数早停（已有页数上限）；若引入子进程则按 AGENTS.md §3 参数数组+最小环境；预置 pypdf 日志级别。

---

## 结论

**需修复后提交。** 唯一阻塞项 **B1**（去重检查须上移至文件数/字节限额之前，并补两条边界回归）必须修复并复跑 pytest 后方可提交。N1–N16 按 AGENTS.md §2「非阻塞改进进 backlog」处理，不当场全面重构；其中 N1（HTTP 先限流）、N13（失败释锁断言）建议随 T05 或紧随其后的小版本优先收口，N4（孤儿 GC）应在 T06 前补齐以兑现 docs/04 §47。


---

## 修复闭环记录（Builder 2026-09-19，先失败用例后修复）

- **B1 已修**：`upload` 去重上移至 magic 校验之后、份数/字节限额之前（重复不消费配额）。回归 `test_duplicate_wins_over_file_count_limit`（max_files 满 + 重传同内容 → duplicate=true、行数不变）。
- **N5 已修**：`find_duplicate` 排除 failed——失败件重传开新一轮解析（`test_failed_material_reupload_starts_new_round`）。failed 行仍计配额，P0 回收仅靠整项目删除（语义已在代码注释固化）。
- **N3 已修**：`handle_parse` 全兜底——DomainError 保留原 code、其余异常标 `INTERNAL_ERROR` 后重抛，不留 parsing 僵尸（`test_parse_io_error_marks_material_failed_not_zombie`；parser 不再把原件丢失伪装成 UNSUPPORTED_FILE）。
- **N2 已修**：字符限额独立错误码 `EXTRACTION_LIMIT_EXCEEDED`→413（error_mapping 同步），页限额仍 `PAGE_LIMIT_EXCEEDED`。
- **N1 已修**：路由按 Content-Length 预检（2 倍文件上限，预留 multipart 开销）先行 413，service 复核兜底；真实部署的流式限流放 T15 中间件。
- **N4 已修**：`cleanup_orphan_material_files` 启动期删除无指针 `*.pdf` 与 `*.tmp-*`（docs/04 §47），有指针文件不动（`test_startup_gc_removes_orphan_files`）。
- **N6 已修**：`save_parsed` 接收 `DocumentChunk` 对象，corpus_revision 单源出自事务内分配值，dict 占位通道删除。
- **N11 已修**：multipart 幂等指纹改长度前缀拼接，消除换行域分隔歧义。
- **N13 已修**：worker failed 用例补 `active_job_id is None` 断言；新增 e2e 失败链（encrypted→worker→job failed→material failed→锁释放→下一份 202）。
- **N14 已修**：`PROJECT_MAX_PAGES/PROJECT_MAX_CHARS` 单一事实源，ParseLimits/ProjectLimits 默认值同源。
- **N15 已修**：移除 `except BaseException: raise` 噪音；`_page_has_image` 宽 except 注明有意兜底。
- **进 backlog**：N7（预算口径已核实 LENGTH() 为字符数，语义正确）、N8（/PageLabels 未实现，printed_page_label 恒 None，T06 前在契约文档记录差距）、N9（错误文本类名已顺手清）、N10（纯矢量/Type3 字体页误判 EMPTY_PAGE——消息仍诚实"无可抽取文本"，T14 变体覆盖）、N12（duplicate 命中且原件 queued 时 job_id=None，等待把手=轮询 GET /materials，前端 T11 落实）、N16（解析超时/子进程隔离，T15 部署硬化；P0 本地单用户接受）。

**修复后回归**：`.venv/bin/pytest tests/` **276 passed**（+6 条回归）退出码 0；validate_pack 23/23；frontend build PASS。B1 修复后验收项 3"限额/跨路径拒绝"与去重语义闭合，四项验收全达。
