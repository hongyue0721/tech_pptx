# T13 Skill 黄金链实测记录（2026-09-22）

## 执行环境

- 真实进程入口：`PYTHONPATH=backend/src backend/.venv/bin/python -m courseware_core.cli`
  （Python 3.12.14 / sqlite 3.53.1 / pypdf+jieba+python-pptx 可用，doctor 实证）
- 独立 data-dir：`.cc_demo/skill-golden/`（app.db+materials/+artifacts/+exports/），
  与 Web 服务（8010，.cc_demo/app.db）完全隔离，锁互不冲突
- 模型：deepseek-flash（哥哥本轮授权范围内）；凭据仅与命令同行注入、不落盘

## 命令序列与结果（全部为实际退出码）

| 步骤 | 命令 | 结果 | llm_calls |
|---|---|---|---|
| 1 | `doctor --data-dir D` | exit 0；lock=available；无任何 Key 输出 | — |
| 2 | `project create`（真实教材 goal，consent=true） | exit 0 → 359ed03a… | 0 |
| 3 | `material add`（01_stm32_interrupt_notes.pdf） | exit 0，job=succeeded，corpus→1 | **0（本地解析）** |
| 4 | 同文件重传（CLI 测试链内） | duplicate=true 零新 job | 0 |
| 5 | `plan create --corpus-revision 1` | exit 0，job=succeeded，goal0=partial/goal1=supported，plan draft | **1（真实）** |
| 6 | `plan confirm`（按原样） | exit 0 → confirmed | 0 |
| 7 | `deck generate` | exit 0，job=succeeded，**候选 blocked** | **7（真实）** |
| 8 | `change show` | exit 0，与 generate 结果同真源 | — |
| 9 | seed v1（声明构造，见下） | current_version=1 | — |
| 10 | `deck show --version 1` | exit 0，slide ids 取得 | — |
| 11 | `deck edit`（结构化 reorder） | exit 0，change kind=edit **ready** | **0（确定性路径）** |
| 12 | `change commit` | exit 0 → v2 | 0 |
| 13 | `deck restore`（target=1） | exit 0 → v3，restored_from=1 | 0 |
| 14 | `deck export --version 3` | exit 0，pptx+report 落 exports/ | 0 |

真实模型调用合计 = **8 次**（plan 1 + generate 7），在授权范围内；
`jobs.llm_calls` 列程序化核对（禁手抄，逐 job 查询）。

## 可信链在真实模型上的行为实证（重要）

步骤 7 候选 **blocked 是正确结果**：真实 deepseek 提案含 1 条 quote
非片段原文子串（locator invalid→not_checked）+ 5 条 missing_evidence
声明（讲义明示不提供统一配置值），P0 保守门拦截、不盖绿
（claim_checks/warnings/model_id=deepseek-flash/prompt_version=
content-v4+verify-v2+audit-v2 全字段留痕于 CLI JSON 输出）。
"资料不足/引用失败呈现给教师而非补写"由此在真实模型链上实证，
非仅 scripted 背书。

## seed v1 声明（诚实登记）

blocked 候选不可 commit；为演示下游链（edit/restore/export），
用 `.cc_demo/skill-golden/seed_v1.py` 直接构造合规 v1
（claims 引用真实解析 chunks 的原文子串，layout title+concept×3）。
**该版本为声明构造，非模型生成背书**（与 T12 浏览器轮同口径）。

## 导出文件验证

`courseware-v3.pptx`：zipfile 44 部件；python-pptx 重开 4 页；
标题/正文/页脚为真实可编辑文本框（非图片）。
`evidence-report-v3.json` 成对交付，sha256 与 artifact 记录一致。
（L3 Office 打开实测：与 T10 同文件链同 exporter，哥哥 T10 轮已实测
通过；本文件哥哥可复验。）

## Skill 发现性（如实区分）

- Skill 已安装两处：规划包 `.codeartsdoer/skills/teacher-courseware/`
  （allowed_paths 内，随仓库发布）与工作区 `.codeartsdoer/skills/`
  （码道发现目录）。
- 本会话 listSkills 未列出该 Skill：码道 Skill 发现为会话启动时快照，
  会话中途安装不进入当前清单。**"码道 Agent 按 SKILL.md+references
  工作流真实执行"已达成（本记录即执行结果）**；"新会话自动发现/
  `codearts run` CLI 会话加载"两项验证需新会话或哥哥提供 CLI AK/SK
  （凭据不落盘），已登记待验，不谎报。

## 复现命令

见 `.codeartsdoer/skills/teacher-courseware/references/workflow.md`
（命令契约同步版）。
