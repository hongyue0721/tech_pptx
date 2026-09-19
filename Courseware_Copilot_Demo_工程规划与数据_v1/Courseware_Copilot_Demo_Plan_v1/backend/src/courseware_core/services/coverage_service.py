"""逐目标覆盖评估（docs/05 §2/§13）：大纲阶段就把缺口给教师。

P0 规则判定基于"查询词在最佳命中片段中的覆盖率"而非裸命中数：
词面部分重叠（如教材的"测量"撞进无关目标查询）不足以宣称 supported。
coverage < 1/3 = unsupported；1/3–2/3 或仅一条候选 = partial；≥ 2/3 = supported。
conflict 需要跨片段语义比对，属 L3 语义核验（T09），规则层不假装能判。
分数不是概率；note 用"当前材料检索未找到足够支持"，不断言知识不存在。
"""

import sqlite3

from courseware_core.errors import ProjectNotFound
from courseware_core.models import ObjectiveCoverage
from courseware_core.retrieval.bm25 import search_chunks
from courseware_core.retrieval.tokenizer import tokenize

TOP_K = 12
SUPPORTED_COVERAGE = 2 / 3
PARTIAL_COVERAGE = 1 / 3


def evaluate_goal_coverage(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    goals: list[str],
) -> list[ObjectiveCoverage]:
    row = conn.execute(
        "SELECT corpus_revision FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise ProjectNotFound({"project_id": project_id})
    corpus_revision = row["corpus_revision"]

    coverage: list[ObjectiveCoverage] = []
    for goal_index, goal in enumerate(goals):
        hits = search_chunks(
            conn,
            project_id=project_id,
            corpus_revision=corpus_revision,
            query=goal,
            limit=TOP_K,
        )
        ratio = max((_term_coverage(goal, hit.text) for hit in hits), default=0.0)
        # 在全部候选（≤TOP_K）上取最佳覆盖率：目标句可能落在页内非首个
        # chunk，BM25 首位也可能是页眉碎片，只看 top1/top5 会误判缺口。
        if not hits or ratio < PARTIAL_COVERAGE:
            status = "unsupported"
            note = "当前材料检索未找到足够支持，建议补充资料或调整目标表述。"
            chunk_ids: list[str] = []
        elif ratio < SUPPORTED_COVERAGE or len(hits) == 1:
            status = "partial"
            note = "仅词面部分命中，支持程度需教师或语义核验确认。"
            chunk_ids = [hit.chunk_id for hit in hits]
        else:
            status = "supported"
            note = ""
            chunk_ids = [hit.chunk_id for hit in hits]
        coverage.append(
            ObjectiveCoverage(
                goal_index=goal_index,
                status=status,
                chunk_ids=chunk_ids,
                note=note,
            )
        )
    return coverage


def _term_coverage(goal: str, candidate_text: str) -> float:
    """查询词在候选文本中的子串覆盖率。

    用子串而非分词集合交集：jieba 对 "EXTI 配置流程" 与正文 "EXTI配置流程"
    可能切出不同词形（"配置"/"流程" vs "配置流程"），词形交集会因边界
    不对称而漏判；子串匹配对覆盖判断更稳（排序仍归 BM25）。
    """
    query_terms = set(tokenize(goal))
    if not query_terms:
        return 0.0
    lowered = candidate_text.lower()
    hit = sum(1 for term in query_terms if term in lowered)
    return hit / len(query_terms)
