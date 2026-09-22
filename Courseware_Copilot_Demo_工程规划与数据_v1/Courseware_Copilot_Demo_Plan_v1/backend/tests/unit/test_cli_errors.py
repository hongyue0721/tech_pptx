"""T13 循环③：CLI 负例与入口真实性——错误码复用、锁回退、真实进程入口。"""

import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from courseware_core.cli import main

DEMO_PDF = Path(__file__).resolve().parents[3] / "demo-data" / "inputs" / \
    "01_stm32_interrupt_notes.pdf"


def run_cli(argv, *, provider=None, env=None):
    out = io.StringIO()
    rc = main(argv, env=env or {}, provider=provider, stdout=out)
    return rc, json.loads(out.getvalue())


@pytest.fixture()
def data_dir(tmp_path):
    return tmp_path / "skill-demo"


@pytest.fixture()
def project_id(data_dir):
    req = data_dir.parent / "p.json"
    req.write_text(json.dumps({
        "course": {"topic": "STM32 中断", "audience": "大二",
                   "duration_minutes": 45, "goals": ["理解 NVIC 优先级分组"],
                   "target_slides": 4},
        "consent_to_cloud_processing": True,
    }, ensure_ascii=False), encoding="utf-8")
    rc, env = run_cli(["project", "create", "--request", str(req),
                       "--data-dir", str(data_dir)])
    assert rc == 0, env
    return env["payload"]["id"]


def test_material_add_missing_file_is_usage_error(data_dir, project_id):
    rc, env = run_cli(["material", "add", "--project", project_id,
                       "--file", "/nonexistent/x.pdf",
                       "--data-dir", str(data_dir)])
    assert rc == 2, env
    assert env["payload"]["error"]["code"] == "USAGE_ERROR"


def test_material_add_unknown_project_reuses_domain_code(data_dir):
    rc, env = run_cli(["material", "add", "--project", "nope",
                       "--file", str(DEMO_PDF), "--data-dir", str(data_dir)])
    assert rc == 1, env
    assert env["payload"]["error"]["code"] == "PROJECT_NOT_FOUND"


def test_deck_show_unknown_project_reuses_domain_code(data_dir):
    rc, env = run_cli(["deck", "show", "--project", "nope",
                       "--data-dir", str(data_dir)])
    assert rc == 1, env
    assert env["command"] == "deck-show"  # 失败信封 command 全名（复审 N4）
    assert env["payload"]["error"]["code"] == "PROJECT_NOT_FOUND"


def test_export_unknown_version_reuses_domain_code(data_dir, project_id):
    rc, env = run_cli(["deck", "export", "--project", project_id,
                       "--version", "9", "--data-dir", str(data_dir)])
    assert rc == 1, env
    assert env["payload"]["error"]["code"] == "DECK_NOT_FOUND"


def test_generate_unconfirmed_plan_reuses_domain_code(data_dir, project_id):
    rc, env = run_cli(["deck", "generate", "--project", project_id,
                       "--plan", "plan_ghost", "--base-version", "0",
                       "--corpus-revision", "1", "--data-dir", str(data_dir)])
    assert rc == 1, env
    assert env["payload"]["error"]["code"] == "PLAN_NOT_FOUND"


def test_commit_wrong_base_reuses_domain_code(data_dir, project_id):
    rc, env = run_cli(["change", "commit", "--project", project_id,
                       "--change", "chg_ghost", "--base-version", "7",
                       "--corpus-revision", "1", "--data-dir", str(data_dir)])
    assert rc == 1, env
    assert env["payload"]["error"]["code"] == "CHANGE_NOT_FOUND"


def test_cc_data_dir_env_fallback(data_dir, project_id, monkeypatch):
    """CC_DATA_DIR 环境变量兜底（Skill 侧免重复传参）；显式参数优先。"""
    monkeypatch.delenv("CC_DATA_DIR", raising=False)
    rc, env = run_cli(["deck", "show", "--project", project_id],
                      env={"CC_DATA_DIR": str(data_dir)})
    assert rc == 1, env  # 项目存在但无 deck：DECK_NOT_FOUND（走对了目录）
    assert env["payload"]["error"]["code"] == "DECK_NOT_FOUND"
    rc, env = run_cli(["deck", "show", "--project", "nope"],
                      env={"CC_DATA_DIR": str(data_dir)})
    assert env["payload"]["error"]["code"] == "PROJECT_NOT_FOUND"


_SRC = Path(__file__).resolve().parents[2] / "src"


def _entry_env():
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC)
    return env


def test_real_entry_point_subprocess_doctor():
    """`python -m courseware_core.cli` 真实进程入口（验收项：目标 CLI 真实实现）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "courseware_core.cli", "doctor"],
        capture_output=True, text=True, timeout=60, env=_entry_env(),
    )
    assert proc.returncode == 0, proc.stderr
    envelope = json.loads(proc.stdout)
    assert envelope["ok"] is True and envelope["command"] == "doctor"
    assert envelope["payload"]["dependencies"]["python_pptx"] is True


def test_real_entry_point_unknown_command_exit_2():
    proc = subprocess.run(
        [sys.executable, "-m", "courseware_core.cli", "frobnicate"],
        capture_output=True, text=True, timeout=60, env=_entry_env(),
    )
    assert proc.returncode == 2
    envelope = json.loads(proc.stdout)
    assert envelope["payload"]["error"]["code"] == "USAGE_ERROR"


def test_help_exits_0_without_error_envelope():
    """Review B1 回归锁：--help 是正常路径，不得追加 USAGE_ERROR 信封盖掉帮助。"""
    proc = subprocess.run(
        [sys.executable, "-m", "courseware_core.cli", "--help"],
        capture_output=True, text=True, timeout=60, env=_entry_env(),
    )
    assert proc.returncode == 0, proc.stdout
    assert "usage:" in proc.stdout
    assert '"ok": false' not in proc.stdout


def test_edit_unknown_target_reuses_domain_code(data_dir, project_id):
    edit_req = data_dir.parent / "edit.json"
    edit_req.write_text(json.dumps({
        "instruction": json.dumps({"action": "reorder", "slide_ids": ["nope"]}),
        "target_slide_ids": ["nope"], "base_version": 1, "corpus_revision": 1,
    }), encoding="utf-8")
    rc, env = run_cli(["deck", "edit", "--project", project_id,
                       "--request", str(edit_req), "--data-dir", str(data_dir)])
    assert rc == 1, env
    # 项目 current_version=0：受理门链 base_version 先拒（api.md 门链口径）
    assert env["payload"]["error"]["code"] == "VERSION_CONFLICT"
