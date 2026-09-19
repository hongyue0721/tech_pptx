"""Chat Completions协议适配：typed JSON、有限重试、预算与取消。

只负责协议/格式/有限重试，不修改业务状态（docs/18）。领域服务定义
plan_course/generate_content/plan_edit/verify_claims，不在UI中散落HTTP调用。

重试矩阵（docs/06）：
- 429/临时5xx/网络连接失败/超时：至多一次退避重试，尊重Retry-After上限；
  网络重试配额在整个complete_json调用内共享，不得多层重试指数放大。
- 401/403：ModelAuthError；400/404/不支持参数：ModelConfigError；均不重试。
- JSON不合法或schema校验失败：一次带校验错误的修复，再失败则ModelOutputInvalid。

预算按实际HTTP请求次数扣减（含重试与修复请求），耗尽抛BudgetExceeded。
"""

import json
import time
from typing import Any, Callable, Optional, Sequence

import httpx
from pydantic import BaseModel, ValidationError

from courseware_core.errors import (
    BudgetExceeded,
    DomainError,
    JobCancelled,
    JobDeadlineExceeded,
    ModelAuthError,
    ModelConfigError,
    ModelOutputInvalid,
    ModelUnavailable,
)
from courseware_core.models import PlanProposal, SemanticVerdicts

from .budget import BudgetExceededError, CancelledError, DeadlineExceededError, JobContext
from .config import RETRY_AFTER_CAP_SECONDS, TRANSIENT_BACKOFF_SECONDS, LLMConfig

# 模型输出提案Schema注册表：模型只填提案类型，存储/HTTP类型不进此表（docs/18）。
OUTPUT_SCHEMAS = {
    "PlanProposal": PlanProposal,
    "SemanticVerdicts": SemanticVerdicts,
}

TEMPORARY_STATUS_CODES = {429, 500, 502, 503, 504}

REPAIR_INSTRUCTION = (
    "上一次输出无法通过校验，请修正后重新只输出一个符合要求的JSON对象，"
    "不要输出任何其他文字。校验错误：\n{error}"
)


class Usage:
    """计费用量；供应商未返回时记unknown（None），不写0（docs/06）。"""

    def __init__(
        self,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        total_tokens: Optional[int],
    ):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = total_tokens


class TypedCompletion:
    def __init__(
        self,
        value: Any,
        usage: Usage,
        provider_request_id: Optional[str],
        attempts: int,
    ):
        self.value = value
        self.usage = usage
        self.provider_request_id = provider_request_id
        self.attempts = attempts


def _parse_usage(raw: Any) -> Usage:
    if not isinstance(raw, dict):
        return Usage(None, None, None)

    def pick(key: str) -> Optional[int]:
        value = raw.get(key)
        return value if isinstance(value, int) else None

    return Usage(pick("prompt_tokens"), pick("completion_tokens"), pick("total_tokens"))


class _CallOutcome:
    """一次_send请求的结果；网络失败用error标记。"""

    def __init__(
        self,
        body: Any = None,
        status: int = 0,
        retry_after: Optional[float] = None,
        error: Optional[Exception] = None,
    ):
        self.body = body
        self.status = status
        self.retry_after = retry_after
        self.error = error


class ChatCompletionsAdapter:
    def __init__(
        self,
        config: LLMConfig,
        transport: Optional[httpx.BaseTransport] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ):
        self.config = config
        self.sleep = sleep or time.sleep
        self.transport = transport
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            timeout = httpx.Timeout(
                connect=self.config.connect_timeout,
                read=self.config.read_timeout,
                write=self.config.connect_timeout,
                pool=self.config.connect_timeout,
            )
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            client_kwargs: dict = {
                "base_url": self.config.base_url,
                "timeout": timeout,
                "headers": headers,
            }
            if self.transport is not None:
                client_kwargs["transport"] = self.transport
            self._client = httpx.Client(**client_kwargs)
        return self._client

    def complete_json(
        self,
        stage: str,
        schema_name: str,
        messages: Sequence[dict],
        context: JobContext,
    ) -> TypedCompletion:
        model = OUTPUT_SCHEMAS.get(schema_name)
        if model is None:
            raise ModelConfigError(
                f"unknown output schema {schema_name!r}",
                {"known": sorted(OUTPUT_SCHEMAS)},
            )

        attempts = 0
        network_retry_used = False
        repair_used = False
        pending_messages = list(messages)

        try:
            while True:
                context.ensure_active()
                outcome, requests_spent = self._send(pending_messages, context, network_retry_used)
                attempts += requests_spent
                if requests_spent > 1:
                    network_retry_used = True

                if outcome.error is not None:
                    raise ModelUnavailable(
                        "temporary failure persisted after retry",
                        {"stage": stage, "attempts": attempts},
                    )
                if outcome.status in TEMPORARY_STATUS_CODES:
                    raise ModelUnavailable(
                        f"temporary failure persisted after retry ({outcome.status})",
                        {"stage": stage, "attempts": attempts},
                    )
                if outcome.status in (401, 403):
                    raise ModelAuthError(
                        f"model endpoint rejected credentials ({outcome.status})",
                        {"status": outcome.status},
                    )
                if outcome.status != 200:
                    raise ModelConfigError(
                        f"model endpoint rejected request ({outcome.status})",
                        {"status": outcome.status},
                    )
                # B1：网关/代理可能返回200+非JSON体（HTML故障页），先守卫再取字段。
                if not isinstance(outcome.body, dict):
                    raise ModelOutputInvalid(
                        "response body is not JSON",
                        {"stage": stage, "status": outcome.status},
                    )

                usage = _parse_usage(outcome.body.get("usage"))
                request_id = (
                    outcome.body.get("id")
                    if isinstance(outcome.body.get("id"), str)
                    else None
                )
                content = self._extract_content(outcome.body)
                if content is None:
                    raise ModelOutputInvalid(
                        "response has no assistant message content",
                        {"stage": stage, "request_id": request_id},
                    )

                try:
                    value = self._validate(content, model)
                except (json.JSONDecodeError, ValidationError) as exc:
                    if repair_used:
                        raise ModelOutputInvalid(
                            "model output failed validation after repair",
                            {"stage": stage, "error": str(exc)[:500]},
                        ) from exc
                    repair_used = True
                    pending_messages = list(messages) + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": REPAIR_INSTRUCTION.format(error=str(exc)[:500]),
                        },
                    ]
                    continue

                # N1：取消在请求飞行期间置位时，不得被正常返回值静默吞掉。
                context.ensure_active()
                return TypedCompletion(value, usage, request_id, attempts)
        except (BudgetExceededError, CancelledError, DeadlineExceededError) as exc:
            raise self._domain_from_internal(exc, stage, attempts) from exc

    def _send(
        self, messages: list[dict], context: JobContext, network_retry_used: bool
    ) -> tuple[_CallOutcome, int]:
        """发送请求；临时性失败在配额内重试一次。每个实际请求先扣预算。"""
        retry_budget = 0 if network_retry_used else 1
        spent = 0
        while True:
            context.budget.consume(1)
            spent += 1
            outcome = self._dispatch(messages)
            transient = outcome.error is not None or outcome.status in TEMPORARY_STATUS_CODES
            if transient and spent <= retry_budget:
                self.sleep(outcome.retry_after if outcome.retry_after is not None else TRANSIENT_BACKOFF_SECONDS)
                # N1：退避期间取消/deadline可能已置位，重试请求发出前复查。
                context.ensure_active()
                continue
            return outcome, spent

    def _dispatch(self, messages: list[dict]) -> _CallOutcome:
        request = self._build_request(messages)
        try:
            raw = self.client.send(request)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return _CallOutcome(error=exc)
        retry_after: Optional[float] = None
        raw_retry = raw.headers.get("Retry-After")
        if raw_retry is not None:
            try:
                retry_after = min(float(raw_retry), RETRY_AFTER_CAP_SECONDS)
            except ValueError:
                retry_after = None
        try:
            body = raw.json()
        except ValueError:
            body = None
        return _CallOutcome(body=body, status=raw.status_code, retry_after=retry_after)

    def _build_request(self, messages: list[dict]) -> httpx.Request:
        payload: dict = {"model": self.config.model, "messages": list(messages)}
        if self.config.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        if self.config.supports_temperature:
            payload["temperature"] = 0
        return self.client.build_request("POST", "/chat/completions", json=payload)

    def _extract_content(self, body: Any) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0] if isinstance(choices[0], dict) else None
        message = first.get("message") if first is not None else None
        if not isinstance(message, dict):
            return None
        content = message.get("content")
        return content if isinstance(content, str) else None

    def _validate(self, content: str, model: type[BaseModel]) -> BaseModel:
        parsed = json.loads(content)
        return model.model_validate(parsed)

    @staticmethod
    def _domain_from_internal(
        exc: Exception, stage: str, attempts: int
    ) -> DomainError:
        if isinstance(exc, BudgetExceededError):
            return BudgetExceeded({"stage": stage, "max_calls": exc.max_calls, "used": exc.used})
        if isinstance(exc, CancelledError):
            return JobCancelled({"stage": stage, "attempts": attempts})
        return JobDeadlineExceeded({"stage": stage, "attempts": attempts})
