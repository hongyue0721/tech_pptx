"""T13 循环①：CLI runtime 契约——doctor、data-dir 布局、独占锁、输出信封、退出码。

CLI 是码道 Skill 的目标入口（skill-template/references/workflow.md）：
类型化 JSON 结果 + 明确退出码 + 复用错误码，不解析随意聊天文字。
"""

import fcntl
import json
import os
from pathlib import Path

import pytest

from courseware_core.cli import main

FAKE_KEY = "sk-donot-echo-1234567890"


def run_cli(argv: list[str], *, env: dict[str, str] | None = None):
    import io

    out = io.StringIO()
    rc = main(argv, env=env or {}, stdout=out)
    return rc, out.getvalue()


def parse_envelope(raw: str) -> dict:
    payload = json.loads(raw)
    assert set(payload) == {"ok", "command", "payload"}, f"envelope keys: {payload}"
    return payload


# ---------- doctor ----------


def test_doctor_reports_environment_without_secrets(tmp_path):
    rc, raw = run_cli(
        ["doctor"],
        env={"APP_LLM_API_KEY": FAKE_KEY, "APP_LLM_MODEL": "deepseek-flash",
             "APP_LLM_BASE_URL": "https://api.deepseek.com",
             "APP_LLM_PROTOCOL": "chat_completions"},
    )
    assert rc == 0, raw
    env = parse_envelope(raw)
    assert env["ok"] is True and env["command"] == "doctor"
    result = env["payload"]
    assert FAKE_KEY not in raw, "doctor 输出绝不允许携带 Key 值"
    assert result["llm"]["configured"] is True
    assert result["llm"]["model"] == "deepseek-flash"
    for dep in ("pypdf", "jieba", "python_pptx"):
        assert result["dependencies"][dep] is True, "锁定栈内依赖必须可用"


def test_doctor_llm_not_configured_is_reported_not_failed():
    rc, raw = run_cli(["doctor"], env={})
    assert rc == 0, raw
    result = parse_envelope(raw)["payload"]
    assert result["llm"]["configured"] is False


def test_doctor_without_data_dir_skips_lock_probe():
    rc, raw = run_cli(["doctor"], env={})
    assert rc == 0, raw
    result = parse_envelope(raw)["payload"]
    assert result["data_dir"]["lock_state"] == "skipped"


def test_doctor_with_free_data_dir_reports_available(tmp_path):
    rc, raw = run_cli(["doctor", "--data-dir", str(tmp_path / "demo")], env={})
    assert rc == 0, raw
    result = parse_envelope(raw)["payload"]
    assert result["data_dir"]["lock_state"] == "available"


# ---------- data-dir 布局与独占锁 ----------


def test_project_create_initializes_data_dir_layout(tmp_path):
    data = tmp_path / "demo"
    request = data.parent / "req.json"
    request.write_text(json.dumps({
        "course": {"topic": "STM32 中断", "audience": "大二",
                    "duration_minutes": 45, "goals": ["理解 NVIC"],
                    "target_slides": 8},
        "consent_to_cloud_processing": False,
    }), encoding="utf-8")
    rc, raw = run_cli(
        ["project", "create", "--request", str(request), "--data-dir", str(data)],
        env={},
    )
    assert rc == 0, raw
    envelope = parse_envelope(raw)
    assert envelope["command"] == "project-create"
    assert envelope["payload"]["consent_to_cloud_processing"] is False
    assert (data / "app.db").exists()
    assert (data / "materials").is_dir()
    assert (data / "artifacts").is_dir()


def test_cli_lock_conflicts_with_worker_lock_path(tmp_path):
    """CLI 与 JobWorker 共用同一把数据目录独占锁（单一事实源，非平行锁）。"""
    from courseware_core.storage.database import connect, init_db

    data = tmp_path / "demo"
    data.mkdir()
    conn = connect(data / "app.db")
    init_db(conn)
    conn.close()
    lock_path = Path(str(data / "app.db") + ".worker.lock")
    holder = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        rc, raw = run_cli(
            ["change", "show", "--project", "p", "--change", "c",
             "--data-dir", str(data)], env={}
        )
        assert rc == 3, raw
        envelope = parse_envelope(raw)
        assert envelope["ok"] is False
        assert envelope["payload"]["error"]["code"] == "WORKER_ALREADY_RUNNING"
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)


# ---------- 输出信封与退出码 ----------


def test_unknown_command_exits_2_with_json_envelope(tmp_path):
    rc, raw = run_cli(["no-such-command", "--data-dir", str(tmp_path)], env={})
    assert rc == 2, raw
    envelope = parse_envelope(raw)
    assert envelope["ok"] is False
    assert envelope["payload"]["error"]["code"] == "USAGE_ERROR"


def test_missing_data_dir_exits_2(tmp_path):
    rc, raw = run_cli(["change", "show", "--project", "p", "--change", "c"], env={})
    assert rc == 2, raw
    envelope = parse_envelope(raw)
    assert envelope["payload"]["error"]["code"] == "USAGE_ERROR"


def test_invalid_request_json_exits_2(tmp_path):
    data = tmp_path / "demo"
    bad = tmp_path / "req.json"
    bad.write_text("{not json", encoding="utf-8")
    rc, raw = run_cli(
        ["project", "create", "--request", str(bad), "--data-dir", str(data)],
        env={},
    )
    assert rc == 2, raw
    envelope = parse_envelope(raw)
    assert envelope["payload"]["error"]["code"] == "USAGE_ERROR"


def test_business_domain_error_exits_1_with_reused_error_code(tmp_path):
    data = tmp_path / "demo"
    rc, raw = run_cli(
        ["change", "show", "--project", "missing_project", "--change",
         "missing_change", "--data-dir", str(data)],
        env={},
    )
    assert rc == 1, raw
    envelope = parse_envelope(raw)
    assert envelope["ok"] is False
    # 复用 api.md 错误码，不造 CLI 私有语义（get_change 先查 change：
    # CHANGE_NOT_FOUND 与 Web 契约 test_api_changes 同口径）
    assert envelope["payload"]["error"]["code"] == "CHANGE_NOT_FOUND"
