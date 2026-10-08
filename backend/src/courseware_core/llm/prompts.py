"""系统提示词加载：app-prompts/ 是唯一事实源（docs/06 Prompt治理、AGENTS §5）。

真实运行的系统提示词必须从该目录的版本化文件读取；服务层禁止再硬编码第二份副本。
事实源缺失或版本头不可解析时显式失败（ModelProtocolError），不静默回落内置副本——
静默回落会让"改了文件但线上跑的还是旧词"这类漂移不可见。
"""

import os
import re
from pathlib import Path
from typing import Optional

from courseware_core.errors import ModelProtocolError

# 规划包根/app-prompts：本文件位于 backend/src/courseware_core/llm/prompts.py。
_BUILTIN_PROMPTS_DIR = Path(__file__).resolve().parents[4] / "app-prompts"

# 文件首行标题即版本声明，如 "# APP plan / v2"。
_VERSION_HEADER_RE = re.compile(r"^#\s*APP\s+(?P<name>\w+)\s*/\s*(?P<version>v\d+)\b")


def default_prompts_dir() -> Path:
    override = os.environ.get("APP_PROMPTS_DIR")
    return Path(override) if override else _BUILTIN_PROMPTS_DIR


def load_system_prompt(
    name: str, prompts_dir: Optional[Path] = None
) -> tuple[str, str]:
    """读取 {prompts_dir}/{name}.md，返回 (prompt_version, body)。

    prompt_version 形如 "plan-v2"（文件名+文件头版本号）；body 为标题行以下全文。
    """
    base = Path(prompts_dir) if prompts_dir is not None else default_prompts_dir()
    path = base / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ModelProtocolError(
            f"prompt source unavailable: {name}.md not found in prompts dir"
        ) from exc
    lines = text.splitlines()
    header = _VERSION_HEADER_RE.match(lines[0]) if lines else None
    if header is None or header.group("name") != name:
        raise ModelProtocolError(
            f"prompt source missing version header: {name}.md"
        )
    body = "\n".join(lines[1:]).strip()
    if not body:
        raise ModelProtocolError(f"prompt source has no body: {name}.md")
    return f"{header.group('name')}-{header.group('version')}", body
