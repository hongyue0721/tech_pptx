"""LLM适配层：单provider适配、能力表、预算（docs/18目录职责）。"""

from .adapter import ChatCompletionsAdapter, TypedCompletion, Usage
from .budget import CallBudget, JobContext
from .config import LLMConfig

__all__ = [
    "ChatCompletionsAdapter",
    "TypedCompletion",
    "Usage",
    "CallBudget",
    "JobContext",
    "LLMConfig",
]
