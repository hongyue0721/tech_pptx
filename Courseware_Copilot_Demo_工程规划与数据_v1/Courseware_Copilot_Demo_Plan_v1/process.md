# process｜当前工程事实与交接

版本：1.0.8；日期：2026-09-19；阶段：**M1 / T04 完成且独立 Review 阻塞问题修复闭环（待负责人确认提交）**。

## 当前事实

规划包已入库（commit 8e30020）。T00 由负责人完成。**2026-09-18 晚 T01/T02 两项待验收全部闭环：** ① 负责人实测 WPS/PowerPoint 打开 `minimal_probe_v2.pptx` 成功，改文本框→保存→重开修改仍在（T02 L2/L3 硬验收 PASS，真实可编辑文本而非截图冒充）；② 沙箱网络恢复（宿主 clash TUN fake-ip 已覆盖沙箱子进程），`codearts models` 列出全部三 provider 共 10 模型（huaweicloud-maas 4 + hyper 2 + ollama 4），`codearts run -m ollama/glm-5.3-flash` 真实调用模型回复"探针OK"（T01 模型直连 PASS）。**M0 硬门禁（T01/T02 不通过不进 T03）已通过。**历史：v1 PPTX 打不开（缺 slideMaster/theme 链）已修复出 v2（10部件），v1 留反例。沙箱内 WPS 无头验证不通（Xvfb 下 GUI 进程裸启动即退，如实记录）。CLI 26.9.3 / 认证 / 会话导出此前已 PASS。仍然**没有实现Courseware Copilot应用，没有创建ECS，没有向GitHub/AtomGit写入，没有调用收费模型。**

| 对象 | 状态 | 证据/说明 |
|---|---|---|
| 规划/接口/工程规范 | DOCS_CREATED | 本文档包，校验见validation-report.md |
| Demo教材、案例与负向输入 | DATA_CREATED | demo-data清单与解析检查；不是产品生成结果 |
| T00 资格/账号/授权/预算 | DONE | 负责人确认；本机开发；不外发/不付费/不公网 |
| 真实CodeArts账号/模型权限 | OWNER_CONFIRMED | T00 负责人确认；2026-09-18晚 CLI AK/SK 已实测可用 |
| CodeArts外接模型工具调用（会话内） | PASS | T01探针：会话内8项中7项PASS；故意失败真实修复PASS；证据smoke/ |
| 独立码道CLI进程 | PASS | HOME重定向+AK/SK后 --version/session list/export/models/run 全部实测PASS（26.9.3）；2026-09-18晚网络恢复后 models 列出10模型、run 真实调模型回复"探针OK" |
| 会话导出（T01验收项） | PASS | `codearts export <id>` 导出 JSON 成功、脱敏扫描通过；补充探针 S4 |
| 原创Skill运行 | NOT_RUN | teacher-courseware 未实现（T13），系统级内置Skill在线（listSkills实测12个） |
| AnyUI安装/构建 | **PASS** | 正确坐标 `@any-design/anyui@0.5.2`（npm裸名anyui是2017无关Angular包=供应链陷阱）；--legacy-peer-deps+仅Vue peers无React/Svelte混入；vite7.3.6构建PASS(120 modules)；Playwright运行时AInput/AButton/ADrawer/Toast四组件真实渲染交互（smoke/t02_anyui_probe/anyui-install-test/） |
| pypdf中文抽取链 | PARTIAL_PASS | 8页/2701字符全中文；reference_chunks 12/12 偏移+sha256一致；版本差异6.19.0 vs 锁定5.9.0已记录 |
| 最小可编辑PPTX探针 | **PASS** | v1打不开（缺master/theme链）→v2修复（10部件完整链）→**负责人WPS实测：打开+改文本框+保存重开修改均在**（L1-L3全过） |
| ppt-edit授权/稳定性 | OWNER_CONFIRMED | T00 负责人确认授权门禁；具体结论见private-evidence（不入库） |
| T03 Schema/API与工程骨架 | **DONE** | 已随 commit 18f4f6c 入库。backend：Pydantic v2 44类型对齐models.schema.json（**独立review发现items元素级约束缺口15处，已按"先失败用例后修复"闭环，双向契约验证成立**）+ FastAPI health/projects CRUD + 统一错误形状（含路由级404/405收口）+ X-Request-ID + Idempotency-Key门禁；frontend：Vue3+TS strict+Router两路由+api client，vue-tsc+vite构建PASS；review报告 docs/reviews/t03-review.md |
| T04 SQLite任务/幂等/版本仓库 | **DONE(Review修复闭环)** | jobs表+JobRepository（单语句CAS领取、终态与项目锁同事务释放）；JobWorker单例（flock锁文件、启动恢复running→interrupted不重放、handler异常→failed）；幂等24h+占位行防双执行（同键同请求重放、异请求409 IDEMPOTENCY_CONFLICT，POST /projects、DELETE、cancel已接入）；项目写锁CAS 409 PROJECT_BUSY；VersionRepository不可变版本+服务端权威版本号+semantic_hash（restore=新版本，异corpus拒绝）；ArtifactStore原子落盘(tmp+fsync+rename)后写指针、读取校验sha256不一致显式ARTIFACT_INTEGRITY；GET/cancel路由+500路径故障注入测试；**独立Review 1阻塞(B1 cancel×claim竞态)+14非阻塞：B1/N2/N3/N5/N12/N13/N14/N7/N11已修复闭环，pytest 213全绿**；报告 docs/reviews/t04-review.md |
| 应用真实LLM/检索/版本/E2E | NOT_RUN | 无业务实现，不伪造测试结果 |
| 校内截止/命题参与数/书面认定 | OWNER_CONFIRMED | T00 负责人确认 |

## 当前任务

**T04 施工完成并通过独立 Review 修复闭环（报告 docs/reviews/t04-review.md，pytest 213 全绿、validate_pack 23/23、frontend build PASS），待负责人确认后提交。下一步唯一任务：T05（PDF导入、规范化与切块）**。backlog：T04 Review 非阻塞遗留——N1（占锁+建job须同事务，T08 写路由接入前）、N4（handler 取消轮询通道，业务 handler 接入时）、N6（in-flight 与异请求冲突错误码区分）、N8（claim 联表校验项目锁一致，随 N1）、N9（artifacts version 外键+删项目清磁盘文件）、N10（sha256 DB CHECK 逐字符等价，注释已标 Pydantic 层保证）；更早遗留：N7 schema enum 补 type:string、pypdf 锁定 5.9.0 对账（T05 前）、AnyUI 图标本地静态打包（正式接入时）。仓库分支master，最新commit 18f4f6c（T04 改动未提交）。

## 新增阻塞（负责人决断）

- **B-1 外网DNS不可达（沙箱内）**：~~已解除~~ **2026-09-18 晚实测已解除**——宿主 clash TUN fake-ip 已覆盖沙箱子进程，npmjs HTTPS 200、CLI 模型直连成功。AnyUI 实装与在线锁版本不再被阻塞。
- **B-2 独立码道CLI EROFS（已闭环）**：HOME 重定向到可写目录后 CLI 全功能可用；models/run 已实测 PASS，阻塞清零。
- **B-3 PPTX Office验收（已闭环）**：**负责人 2026-09-18 实测通过**——打开 v2 成功、改文本框、保存重开修改仍在。T02 验收完成。

## 本轮实际检查

- 码道会话内 smoke：读文件/改文件/建测试/故意失败/真实修复/回归，退出码探针 3 组全对。命令与结果见 `smoke/t01_codearts_probe/`。
- 构建探针：`smoke/t02_anyui_probe/vue-offline-test/`（vite build 真实产物 dist/；离线搭建脚本 setup_offline_node_env.sh 已固化）。
- PDF 探针：`smoke/t02_pdf_probe/extract_report.json` + `chunk_verify.py`（12/12 一致）。
- PPTX 探针：v1（2050字节）负责人实测**打不开**→根因（缺 slideMaster/slideLayout/theme，OPC 仅 2 部件）→ v2 修复（4909字节 10 部件完整链，构建脚本 /tmp/pptx_fix/build_full_pptx.py 逻辑固化在探针目录）→ xmllint 良构 + 关系闭合审计 + python-docx OPC 解析（5部件/7关系集）+ Playwright 1:1 布局渲染（标题四行正文完整无重叠）四重验证通过；v1 改名 minimal_probe_v1_BAD.pptx 留反例。
- 沙箱内 WPS 无头验证尝试失败（Xvfb 下 /opt/kingsoft/wpp GUI 进程裸启动即退，多轮复现），此路不通，如实记录不作为证据。
- CLI 补充探针（2026-09-18 晚，负责人 AK/SK）：`--version`=26.9.3、`session list`=7 条、`export`=JSON+脱敏通过；`run -m ollama/glm-5.3-flash` 认证/配置解密通过但沙箱内 ConnectionRefused，关键结论已写入 smoke 报告。
- **闭环探针（2026-09-18 20:49，网络恢复后沙箱内实测）**：`codearts models` PASS（huaweicloud-maas 4 + hyper 2 + ollama 4 共 10 模型）；`codearts run -m ollama/glm-5.3-flash "只回复三个字：探针OK"` PASS（模型真实回复"探针OK"）。T01 模型直连闭环。
- **T02 Office 验收（负责人 2026-09-18 实测）**：WPS/PowerPoint 打开 minimal_probe_v2.pptx 成功，改文本框→保存→重开修改仍在。T02 L1-L3 全过。
- **T03 施工（2026-09-18 21:00–21:30）**：`backend/` uv 建 Python 3.12.14 venv + uv.lock（fastapi 0.141.1/pydantic 2.13.5/httpx 0.28.1/uvicorn 0.53.0/pytest 8.4.2/jsonschema 4.26.0）；`courseware_core/models/` 44 个 Pydantic 类型与 models.schema.json 对齐（extra=forbid、const→Literal、oneOf→discriminated union、datetime 强制带时区）；`courseware_api/` health+projects 三端点、统一错误形状、X-Request-ID 验证/回传/生成、Idempotency-Key 存在性门禁（完整幂等语义留给 T04）；`frontend/` Vue3+TS strict+vue-router 两路由+api client+useProject，vue-tsc+vite 构建 PASS。测试：`.venv/bin/pytest` **119 passed**（契约往返 44+extra拒绝 44+非法样例 14+naive datetime+API 行为+service 单测），退出码0。
- **T04 施工（2026-09-19）**：按 docs/07 落地可靠状态层。① `storage/database.py` 新增 jobs/idempotency_keys/deck_versions/artifacts 四表（状态/stage CHECK 与 schema enum 对齐，FK 到 projects）；② `JobRepository`：单语句 `UPDATE...RETURNING` CAS 领取、mark_interrupted_on_startup（running→interrupted 且同事务释放项目锁）、finalize（终态+释放锁同事务）、request_cancel（queued→cancelled / running→置标志）；③ `jobs/worker.py` JobWorker：flock 锁文件单实例（第二实例 WorkerAlreadyRunning）、启动恢复不重放、线程内独立连接、handler 异常映射 failed（DomainError 保留 code）；④ 幂等：`IdempotencyRepository`+`IdempotencyService`（scope=会话|项目|路由，占位行 INSERT OR IGNORE 防双执行，24h 过期重执行，同键异请求 IdempotencyConflict→409），`api/idempotency.py` 接入 POST /projects、DELETE /projects、POST /jobs/cancel（T03 存在性门禁升级为完整语义）；⑤ `ProjectRepository.acquire/release_write_lock`（CAS，holder 匹配才释放）；⑥ `VersionRepository`：服务端权威版本号（候选 version 被覆盖）、base/corpus CAS 409、restore=新 version 且异 corpus 拒绝、semantic_hash 忽略 version；⑦ `ArtifactStore`：tmp+fsync+os.replace 原子落盘后才写指针，读取校验 sha256/size 不一致 ARTIFACT_INTEGRITY 显式失败，artifact_id 路径穿越拒绝；⑧ `create_app(worker_handlers=…)` lifespan 启动单 worker（默认 None 不启用）；⑨ 500 路径故障注入测试（T03 backlog N3 闭环：X-Request-ID 在 500 响应头与错误体均保留）。测试：新增 66 条（job_repo 15/lock 6/idempotency 7/version 8/artifact 9/worker 7+API jobs 7+API idempotency 5+500 注入 2），`.venv/bin/pytest` **206 passed** 退出码0；validate_pack 23/23；frontend build 不回归。诚实声明：LLM/渲染 handler 未接（T05+），worker 执行路径用注入 handler 验证，无真实业务 job 类型可跑。
- **AnyUI 实装闭环（2026-09-18 晚）**：见 smoke 报告"AnyUI 实装闭环"节——`@any-design/anyui@0.5.2` 安装/构建/运行时四组件全 PASS；npm 裸名 anyui 为无关旧包（供应链陷阱，已记录禁用）。
- **校验器适配（经负责人批准，tools/ 越出 T03 allowed_paths 的唯一例外）**：`tools/validate_pack.py` 三处全文件系统 rglob 改为 **git 分发视角**（`git ls-files --cached --others --exclude-standard`），PACK_STATIC 从此只验"将被分发的内容"，node_modules/.venv 等 gitignore 目录自然排除；顶层禁 node_modules/data/private-evidence 与字体检查规则不变。改后回归 **23/23 PASS**。
- **T03 独立 Review（干净会话，只审改前）**：发现 3 阻塞（B1 items 元素级约束丢失 15 处、B2 测试盲区、B3 路由级 404/405 错误形状未统一）+ 7 非阻塞。修复严格按"先失败用例（19 条 items 用例先红，失败点确认在 Pydantic 侧）→ 修实现 → 转绿"；B3 加 StarletteHTTPException handler + 2 条用例；N1 错误体经模型构造、N2 encodeURIComponent、N4 .gitignore 补 .playwright-mcp、N5 401 独立状态。N3（500 路径故障注入）、N7（schema enum 缺 type:string）进 backlog。报告与闭环记录：`docs/reviews/t03-review.md`。
- 最终回归：`pytest` **140 passed**（退出码0）；`validate_pack.py` 23/23；frontend `npm run build`（vue-tsc+vite）PASS。
- 环境落地：规划包 `.venv`（Python 3.13.15 + pypdf/jsonschema/PyYAML/pytest 全离线装齐）已建，`validate_pack.py` 回归 **23/23 PASS**（此前"jsonschema 全机无安装"的结论已由实测推翻并闭环）。
- 汇总：`smoke/t01_t02_probe_report.md`（环境矩阵、阻塞清单、给负责人的沙箱外命令清单、诚实声明）。
- 规划包静态检查以validation-report.md为准；未改远端。凭据 AK/SK 全程仅内存环境变量，未写入任何仓库文件。

## 收工记录模板

- 任务ID / commit / 改动路径。
- 实际完成内容及证据。
- 实际测试命令、退出码、失败和NOT_RUN。
- API/Schema/配置/提示版本变化。
- 新阻塞与费用/数据外发情况。
- 下一项唯一任务。

以后由施工AI每轮更新事实，不将这份初始说明持续当作当前状态。所有“计划已写”与“产品已实现”必须分开。
