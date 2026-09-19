"""T07 APP模型Adapter与预算的单元测试。

全部通过 httpx.MockTransport 脚本化协议响应，不触真实网络；
真实协议 smoke 是独立验收项（付费动作，须负责人预算授权）。
"""

import json
import time
from typing import Callable, Optional

import httpx
import pytest

from courseware_core.errors import (
    BudgetExceeded,
    JobCancelled,
    ModelAuthError,
    ModelOutputInvalid,
    ModelProtocolError,
    ModelRateLimited,
    ModelTimeout,
    ModelUnavailable,
    ValidationFailed,
)
from courseware_core.llm.adapter import ChatCompletionsAdapter, TypedCompletion
from courseware_core.llm.budget import CallBudget, JobContext
from courseware_core.llm.config import LLMConfig
from courseware_core.models import PlanProposal, SemanticVerdicts

PLAN_PROPOSAL_JSON = {
    "slides": [
        {
            "id": "s1",
            "title": "定时器基础",
            "purpose": "介绍定时器概念",
            "layout": "concept",
            "goal_indices": [0],
            "evidence_chunk_ids": ["c1"],
        }
    ],
    "coverage_notes": [
        {"goal_index": 0, "candidate_chunk_ids": ["c1"], "note": "有支持"}
    ],
}

VERDICTS_JSON = {
    "checks": [{"claim_id": "c1", "status": "supported", "reason": "证据直接支持"}]
}

MESSAGES = [
    {"role": "system", "content": "你是课件规划助手，只输出JSON。"},
    {"role": "user", "content": "按目标规划课件结构。"},
]


class ScriptedTransport(httpx.BaseTransport):
    """按脚本逐个返回响应或抛异常，并记录收到的请求。"""

    def __init__(self, steps):
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def chat_body(content, usage=None, request_id="req-1"):
    body = {
        "id": request_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def chat_response(content, status=200, usage=None, request_id="req-1", retry_after=None):
    headers = {}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return httpx.Response(
        status,
        headers=headers,
        json=chat_body(content, usage=usage, request_id=request_id),
    )


def make_config(**overrides) -> LLMConfig:
    defaults = dict(
        base_url="https://llm.example.invalid/v1",
        api_key="secret-key-123",
        model="app-model-x",
        protocol="chat_completions",
    )
    defaults.update(overrides)
    return LLMConfig(**defaults)


def make_adapter(
    steps,
    config: Optional[LLMConfig] = None,
) -> tuple[ChatCompletionsAdapter, ScriptedTransport, list[float]]:
    transport = ScriptedTransport(steps)
    sleeps: list[float] = []
    adapter = ChatCompletionsAdapter(
        config or make_config(),
        transport=transport,
        sleep=sleeps.append,
    )
    return adapter, transport, sleeps


def make_context(
    max_calls: int = 8,
    cancel_check: Optional[Callable[[], bool]] = None,
    deadline: Optional[float] = None,
) -> JobContext:
    return JobContext(
        budget=CallBudget(max_calls=max_calls),
        cancel_check=cancel_check or (lambda: False),
        deadline=deadline,
    )


class TestProtocolShape:
    def test_success_returns_typed_value_and_usage(self):
        adapter, transport, _ = make_adapter(
            [chat_response(json.dumps(PLAN_PROPOSAL_JSON), usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150})]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert isinstance(completion, TypedCompletion)
        assert isinstance(completion.value, PlanProposal)
        assert completion.value.slides[0].id == "s1"
        assert completion.usage.input_tokens == 120
        assert completion.usage.output_tokens == 30
        assert completion.usage.total_tokens == 150
        assert completion.provider_request_id == "req-1"
        assert completion.attempts == 1

    def test_request_shape_auth_header_and_json_mode(self):
        adapter, transport, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON))])
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        request = transport.requests[0]
        assert request.method == "POST"
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-key-123"
        body = json.loads(request.content)
        assert body["model"] == "app-model-x"
        assert body["messages"] == MESSAGES
        assert body["response_format"] == {"type": "json_object"}

    def test_temperature_omitted_when_unsupported(self):
        adapter, transport, _ = make_adapter(
            [chat_response(json.dumps(PLAN_PROPOSAL_JSON))],
            config=make_config(supports_temperature=False),
        )
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        body = json.loads(transport.requests[0].content)
        assert "temperature" not in body

    def test_json_mode_disabled_sends_no_response_format(self):
        adapter, transport, _ = make_adapter(
            [chat_response(json.dumps(PLAN_PROPOSAL_JSON))],
            config=make_config(supports_json_mode=False),
        )
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        body = json.loads(transport.requests[0].content)
        assert "response_format" not in body

    def test_schema_name_selects_typed_model(self):
        adapter, _, _ = make_adapter([chat_response(json.dumps(VERDICTS_JSON))])
        completion = adapter.complete_json("verify_claims", "SemanticVerdicts", MESSAGES, make_context())
        assert isinstance(completion.value, SemanticVerdicts)


class TestJsonRepair:
    def test_invalid_json_one_repair_then_success(self):
        adapter, transport, _ = make_adapter(
            [
                chat_response("这不是JSON"),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2
        repair_request = transport.requests[1]
        repair_messages = json.loads(repair_request.content)["messages"]
        # 修复请求 = 原消息 + assistant坏输出 + user修复指令
        assert len(repair_messages) == len(MESSAGES) + 2
        assert repair_messages[-2]["role"] == "assistant"
        assert "这不是JSON" in repair_messages[-2]["content"]
        assert "JSON" in repair_messages[-1]["content"]

    def test_schema_violation_one_repair_then_success(self):
        broken = {"slides": [{"id": "s1", "title": "缺purpose与layout"}]}
        adapter, transport, _ = make_adapter(
            [
                chat_response(json.dumps(broken)),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert isinstance(completion.value, PlanProposal)
        assert completion.attempts == 2
        repair_messages = json.loads(transport.requests[1].content)["messages"]
        assert "purpose" in repair_messages[-1]["content"]

    def test_repair_failure_raises_model_output_invalid(self):
        adapter, transport, _ = make_adapter(
            [
                chat_response("仍然不是JSON"),
                chat_response("还是不是JSON"),
            ]
        )
        with pytest.raises(ModelOutputInvalid):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 2

    def test_unknown_schema_name_rejected(self):
        adapter, _, _ = make_adapter([])
        with pytest.raises(ValidationFailed):
            adapter.complete_json("plan_course", "NoSuchSchema", MESSAGES, make_context())
        assert len(adapter.transport.requests) == 0


class TestRetryMatrix:
    def test_429_retries_once_then_succeeds(self):
        adapter, transport, sleeps = make_adapter(
            [
                chat_response("", status=429, retry_after=0),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2
        assert sleeps == [0.0]

    def test_429_twice_raises_model_rate_limited(self):
        adapter, transport, _ = make_adapter(
            [
                chat_response("", status=429, retry_after=0),
                chat_response("", status=429, retry_after=0),
            ]
        )
        with pytest.raises(ModelRateLimited):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 2

    def test_retry_after_capped(self):
        adapter, _, sleeps = make_adapter(
            [
                chat_response("", status=429, retry_after=120),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert sleeps[0] <= 5.0

    def test_5xx_retries_once(self):
        adapter, transport, _ = make_adapter(
            [
                chat_response("", status=503),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2

    def test_401_fails_immediately_no_retry(self):
        adapter, transport, _ = make_adapter([chat_response("", status=401)])
        with pytest.raises(ModelAuthError):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 1

    def test_400_fails_immediately_no_retry(self):
        adapter, transport, _ = make_adapter([chat_response("", status=400)])
        with pytest.raises(ModelProtocolError):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 1

    def test_200_with_non_json_body_raises_model_output_invalid_no_retry(self):
        # B1回归：网关/代理故障页（200+HTML）必须走typed异常，不得裸AttributeError逃逸。
        adapter, transport, _ = make_adapter(
            [httpx.Response(200, text="<html>gateway error</html>")]
        )
        with pytest.raises(ModelOutputInvalid):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 1

    def test_missing_assistant_content_raises_model_output_invalid(self):
        # N6回归：choices存在但message无content字段→typed异常。
        body = {"id": "r", "choices": [{"index": 0, "message": {"role": "assistant"}}]}
        adapter, transport, _ = make_adapter([httpx.Response(200, json=body)])
        with pytest.raises(ModelOutputInvalid):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 1

    def test_403_fails_immediately_no_retry(self):
        adapter, transport, _ = make_adapter([chat_response("", status=403)])
        with pytest.raises(ModelAuthError):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 1

    def test_retry_after_non_numeric_falls_back_to_default_backoff(self):
        # N6回归：HTTP-date等病态Retry-After不得抛异常，回落固定退避。
        adapter, transport, sleeps = make_adapter(
            [
                httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, json={"error": "rate limited"}),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2
        assert sleeps == [0.5]

    def test_5xx_twice_raises_model_unavailable(self):
        adapter, transport, _ = make_adapter(
            [chat_response("", status=503), chat_response("", status=503)]
        )
        with pytest.raises(ModelUnavailable):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 2

    def test_timeout_retries_once_then_succeeds(self):
        adapter, transport, _ = make_adapter(
            [
                httpx.ReadTimeout("read timed out"),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2

    def test_timeout_twice_raises_model_timeout(self):
        adapter, transport, _ = make_adapter(
            [httpx.ReadTimeout("read timed out"), httpx.ReadTimeout("read timed out")]
        )
        with pytest.raises(ModelTimeout):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 2

    def test_connect_error_retries_once(self):
        adapter, transport, _ = make_adapter(
            [
                httpx.ConnectError("connection refused"),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.attempts == 2

    def test_network_retry_quota_shared_with_repair_no_exponential_retry(self):
        # 原始请求429→重试成功但JSON非法→修复请求又429：网络重试配额已耗尽，
        # 不得再对修复请求重试（防多层重试指数放大）。
        adapter, transport, _ = make_adapter(
            [
                chat_response("", status=429, retry_after=0),
                chat_response("坏JSON"),
                chat_response("", status=429, retry_after=0),
            ]
        )
        with pytest.raises(ModelRateLimited):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert len(transport.requests) == 3


class TestUsageAccounting:
    def test_usage_missing_marks_unknown_not_zero(self):
        adapter, _, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON), usage=None)])
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.usage.input_tokens is None
        assert completion.usage.output_tokens is None
        assert completion.usage.total_tokens is None

    def test_partial_usage_fields_mark_unknown(self):
        adapter, _, _ = make_adapter(
            [chat_response(json.dumps(PLAN_PROPOSAL_JSON), usage={"total_tokens": 42})]
        )
        completion = adapter.complete_json("plan_course", "PlanProposal", MESSAGES, make_context())
        assert completion.usage.total_tokens == 42
        assert completion.usage.input_tokens is None


class TestBudget:
    def test_budget_exhausted_blocks_call_before_request(self):
        adapter, transport, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON))])
        context = make_context(max_calls=1)
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        with pytest.raises(BudgetExceeded):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 1

    def test_budget_counts_retry_and_repair_requests(self):
        # 一次逻辑调用内部消耗2个HTTP请求（429重试），预算按实际请求扣减。
        adapter, transport, _ = make_adapter(
            [
                chat_response("", status=429, retry_after=0),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        context = make_context(max_calls=2)
        adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        with pytest.raises(BudgetExceeded):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 2

    def test_budget_exhausted_blocks_repair(self):
        # 预算只剩1次时，非法输出不得再发起修复请求。
        adapter, transport, _ = make_adapter([chat_response("坏JSON")])
        context = make_context(max_calls=1)
        with pytest.raises(BudgetExceeded):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 1


class TestCancellationAndDeadline:
    def test_cancel_before_call_raises_job_cancelled(self):
        adapter, transport, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON))])
        context = make_context(cancel_check=lambda: True)
        with pytest.raises(JobCancelled):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 0

    def test_cancel_before_repair_raises_job_cancelled(self):
        adapter, transport, _ = make_adapter(
            [chat_response("坏JSON"), chat_response(json.dumps(PLAN_PROPOSAL_JSON))]
        )
        # 首次调用放行，坏输出返回后置位取消，修复请求发出前被拦。
        state = {"calls": 0}

        def cancel_check():
            state["calls"] += 1
            return state["calls"] > 1

        context = make_context(cancel_check=cancel_check)
        with pytest.raises(JobCancelled):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 1

    def test_deadline_passed_raises_model_timeout(self):
        adapter, transport, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON))])
        context = make_context(deadline=time.monotonic() - 1.0)
        with pytest.raises(ModelTimeout):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 0

    def test_cancel_during_retry_backoff_blocks_second_request(self):
        # N1回归：取消在重试退避期间置位，第二个请求不得发出。
        adapter, transport, _ = make_adapter(
            [
                chat_response("", status=429, retry_after=0),
                chat_response(json.dumps(PLAN_PROPOSAL_JSON)),
            ]
        )
        state = {"checks": 0}

        def cancel_check():
            state["checks"] += 1
            # 检查点顺序：循环顶(1)→退避sleep后(2)→return前(3)。
            # 第2次为True即拦截重试请求。
            return state["checks"] > 1

        context = make_context(cancel_check=cancel_check)
        with pytest.raises(JobCancelled):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 1

    def test_cancel_during_flight_not_swallowed_by_success(self):
        # N1回归：取消在请求飞行期间置位且该请求成功返回时，取消不得被静默吞掉。
        adapter, transport, _ = make_adapter([chat_response(json.dumps(PLAN_PROPOSAL_JSON))])
        state = {"checks": 0}

        def cancel_check():
            state["checks"] += 1
            return state["checks"] > 1

        context = make_context(cancel_check=cancel_check)
        with pytest.raises(JobCancelled):
            adapter.complete_json("plan_course", "PlanProposal", MESSAGES, context)
        assert len(transport.requests) == 1


class TestConfig:
    def test_config_repr_does_not_leak_api_key(self):
        config = make_config()
        assert "secret-key-123" not in repr(config)
        assert "secret-key-123" not in str(config)

    def test_unsupported_protocol_rejected(self):
        with pytest.raises(ValueError):
            make_config(protocol="responses")

    def test_from_env_reads_app_llm_variables(self):
        config = LLMConfig.from_env(
            {
                "APP_LLM_BASE_URL": "https://llm.example.invalid/v1",
                "APP_LLM_API_KEY": "env-key",
                "APP_LLM_MODEL": "env-model",
                "APP_LLM_PROTOCOL": "chat_completions",
                "APP_LLM_CONNECT_TIMEOUT_SECONDS": "7",
                "APP_LLM_READ_TIMEOUT_SECONDS": "60",
            }
        )
        assert config.base_url == "https://llm.example.invalid/v1"
        assert config.model == "env-model"
        assert config.connect_timeout == 7.0
        assert config.read_timeout == 60.0

    def test_from_env_capability_flags(self):
        # N4：能力位从env读取，smoke探测结论可直接落配置。
        config = LLMConfig.from_env(
            {
                "APP_LLM_BASE_URL": "https://llm.example.invalid/v1",
                "APP_LLM_API_KEY": "env-key",
                "APP_LLM_MODEL": "env-model",
                "APP_LLM_SUPPORTS_TEMPERATURE": "false",
                "APP_LLM_SUPPORTS_JSON_MODE": "false",
            }
        )
        assert config.supports_temperature is False
        assert config.supports_json_mode is False
        default = LLMConfig.from_env(
            {
                "APP_LLM_BASE_URL": "https://llm.example.invalid/v1",
                "APP_LLM_API_KEY": "env-key",
                "APP_LLM_MODEL": "env-model",
            }
        )
        assert default.supports_temperature is True
        assert default.supports_json_mode is True
