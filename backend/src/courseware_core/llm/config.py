"""APP模型配置：从环境变量读取，凭据不进日志与repr。

Key/用途/预算与DEV模型分开（docs/06）；本配置只服务FastAPI业务核心的APP模型。
"""

import os
from typing import Mapping, Optional

ALLOWED_PROTOCOLS = ("chat_completions",)

# 429的Retry-After可能被供应商给得很大，退避上限封顶防止任务被拖死。
RETRY_AFTER_CAP_SECONDS = 5.0
# 临时性失败（429/5xx/网络/超时）的固定退避；无Retry-After时使用。
TRANSIENT_BACKOFF_SECONDS = 0.5


class LLMConfig:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        protocol: str = "chat_completions",
        connect_timeout: float = 10.0,
        read_timeout: float = 120.0,
        supports_temperature: bool = True,
        supports_json_mode: bool = True,
    ):
        if protocol not in ALLOWED_PROTOCOLS:
            raise ValueError(
                f"unsupported protocol {protocol!r}; "
                f"P0 adapter only implements {ALLOWED_PROTOCOLS}"
            )
        if not base_url or not model:
            raise ValueError("base_url and model are required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.protocol = protocol
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.supports_temperature = supports_temperature
        self.supports_json_mode = supports_json_mode

    def __repr__(self) -> str:
        # 绝不把api_key带进repr/str，防日志脱敏遗漏。
        return (
            f"LLMConfig(base_url={self.base_url!r}, model={self.model!r}, "
            f"protocol={self.protocol!r}, api_key=***, "
            f"connect_timeout={self.connect_timeout}, "
            f"read_timeout={self.read_timeout})"
        )

    __str__ = __repr__

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "LLMConfig":
        source = dict(os.environ if env is None else env)
        return cls(
            base_url=source.get("APP_LLM_BASE_URL", ""),
            api_key=source.get("APP_LLM_API_KEY", ""),
            model=source.get("APP_LLM_MODEL", ""),
            protocol=source.get("APP_LLM_PROTOCOL", "chat_completions"),
            connect_timeout=float(source.get("APP_LLM_CONNECT_TIMEOUT_SECONDS", "10")),
            read_timeout=float(source.get("APP_LLM_READ_TIMEOUT_SECONDS", "120")),
            supports_temperature=_env_flag(source, "APP_LLM_SUPPORTS_TEMPERATURE", True),
            supports_json_mode=_env_flag(source, "APP_LLM_SUPPORTS_JSON_MODE", True),
        )


def _env_flag(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
