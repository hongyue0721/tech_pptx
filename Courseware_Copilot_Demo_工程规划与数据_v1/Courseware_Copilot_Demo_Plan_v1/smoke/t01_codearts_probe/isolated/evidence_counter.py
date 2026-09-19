"""T01 smoke 目标模块：证据计数器（courseware 工程中最小可测单元的替身）。"""


class EvidenceCounter:
    """统计已定位引用数量；located 必须是合法 EvidenceSpan 列表。"""

    def __init__(self, max_claims: int = 96):
        self.max_claims = max_claims
        self._located: list[str] = []

    def add_located(self, claim_id: str) -> None:
        if not claim_id:
            raise ValueError("claim_id 不能为空")
        if claim_id in self._located:
            raise ValueError(f"claim_id 重复: {claim_id}")
        if len(self._located) >= self.max_claims:
            raise OverflowError("超过最大 claims 上限")
        self._located.append(claim_id)

    @property
    def located_count(self) -> int:
        return len(self._located)
