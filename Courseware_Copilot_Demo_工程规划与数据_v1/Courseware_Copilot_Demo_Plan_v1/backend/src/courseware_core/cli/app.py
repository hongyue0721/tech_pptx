"""teacher-courseware 项目 CLI：类型化 JSON 结果 + 明确退出码 + 复用错误码。

契约来源 skill-template/teacher-courseware/references/workflow.md。
入口 `python -m courseware_core.cli`。所有命令输出单个 JSON 信封：
  {"ok": bool, "command": str, "payload": {...}}
失败时 payload = {"error": {code, message, request_id, details}}（api.md 形状）。
退出码：0 成功；1 业务拒绝（DomainError / job 非 succeeded 终态）；
2 用法错误（参数/请求文档非法）；3 环境冲突（data-dir 被占用）；4 内部错误。
"""

import argparse
import importlib
import io
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Mapping, Optional, TextIO

from pydantic import ValidationError

from courseware_core.cli.runtime import (
    DataDir,
    DataDirLock,
    InlineJobRunner,
    probe_lock,
    recover_interrupted,
)
from courseware_core.errors import DomainError, WorkerAlreadyRunning
from courseware_core.llm.config import LLMConfig
from courseware_core.models import (
    CommitRequest,
    ConfirmPlanRequest,
    CreateProjectRequest,
    EditRequest,
    ExportRequest,
    GenerateRequest,
    Job,
    PlanRequest,
    RestoreRequest,
)
from courseware_core.services.export_service import (
    ExportService,
    artifact_filename,
)
from courseware_core.services.generate_service import GenerateService
from courseware_core.services.edit_service import EditService
from courseware_core.services.material_service import MaterialService
from courseware_core.services.plan_service import PlanService
from courseware_core.services.project_service import ProjectService
from courseware_core.services.read_service import ProjectReadService
from courseware_core.services.restore_service import RestoreService
from courseware_core.storage.artifact_store import ArtifactStore
from courseware_core.storage.material_repository import MaterialRepository
from courseware_core.storage.project_repository import ProjectRepository

EXIT_OK = 0
EXIT_BUSINESS = 1
EXIT_USAGE = 2
EXIT_ENV = 3
EXIT_INTERNAL = 4

_DEPENDENCIES = ("pypdf", "jieba", "pptx")


class UsageError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _emit(stdout: TextIO, ok: bool, command: str, payload: dict) -> None:
    stdout.write(
        json.dumps(
            {"ok": ok, "command": command, "payload": payload},
            ensure_ascii=False,
            default=str,
        )
        + "\n"
    )
    stdout.flush()


def _command_label(ns) -> str:
    """信封 command 字段全名（成功/失败路径一致，review N4）。"""
    return ns.command if ns.command == "doctor" else f"{ns.command}-{ns.sub}"


def _dump(model) -> dict:
    return model.model_dump(mode="json")


def _read_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"cannot read request file {path!r}: {exc}") from exc


def _data_dir(ns, env: Mapping[str, str]) -> DataDir:
    raw = getattr(ns, "data_dir", None) or env.get("CC_DATA_DIR")
    if not raw:
        raise UsageError("--data-dir is required (or set CC_DATA_DIR)")
    return DataDir(Path(raw))


# ---------- doctor ----------


def _cmd_doctor(ns, env: Mapping[str, str]) -> dict:
    deps = {}
    for module, label in ((_DEPENDENCIES[0], "pypdf"), (_DEPENDENCIES[1], "jieba"),
                          (_DEPENDENCIES[2], "python_pptx")):
        try:
            importlib.import_module(module)
            deps[label] = True
        except ImportError:
            deps[label] = False
    try:
        config = LLMConfig.from_env(env)
        llm = {"configured": True, "model": config.model,
               "protocol": config.protocol}
    except ValueError:
        llm = {"configured": False, "model": None, "protocol": None}
    if getattr(ns, "data_dir", None):
        lock_state = probe_lock(DataDir(Path(ns.data_dir)))
    elif env.get("CC_DATA_DIR"):
        lock_state = probe_lock(DataDir(Path(env["CC_DATA_DIR"])))
    else:
        lock_state = "skipped"
    return {
        "python": sys.version.split()[0],
        "sqlite": __import__("sqlite3").sqlite_version,
        "dependencies": deps,
        "llm": llm,
        "data_dir": {"path": getattr(ns, "data_dir", None),
                     "lock_state": lock_state},
    }


# ---------- 同步命令（锁 + 恢复 + 直查/直写） ----------


def _run_sync(data: DataDir, fn):
    data.ensure()
    with DataDirLock(data):
        conn = data.open()
        try:
            recover_interrupted(conn)
            return fn(conn)
        finally:
            conn.close()


def _cmd_project_create(data: DataDir, ns) -> dict:
    request = CreateProjectRequest.model_validate(_read_json(ns.request))

    def work(conn):
        service = ProjectService(ProjectRepository(conn))
        return _dump(service.create_project(request))

    return _run_sync(data, work)


def _cmd_change_show(data: DataDir, ns) -> dict:
    def work(conn):
        return _dump(GenerateService(conn).get_change(ns.project, ns.change))

    return _run_sync(data, work)


def _cmd_plan_confirm(data: DataDir, ns) -> dict:
    def work(conn):
        service = PlanService(conn)
        plan = service.get_plan(ns.project, ns.plan)
        if ns.request:
            payload = _read_json(ns.request)
            # 双源冲突显式拒绝（review N6）：静默任胜会让教师看到
            # "确认了 A、实际生效 B"的假成功。
            if "corpus_revision" in payload and payload["corpus_revision"] != ns.corpus_revision:
                raise UsageError(
                    "--corpus-revision conflicts with request file corpus_revision"
                )
            payload["corpus_revision"] = ns.corpus_revision
            payload["acknowledged"] = True
            request = ConfirmPlanRequest.model_validate(payload)
        else:
            # 缺省=教师"按原样确认"：slides/接受范围取服务器当前计划，
            # CLI 显式调用 confirm 即教师确认动作（docs/10 §5 工作流）。
            request = ConfirmPlanRequest(
                corpus_revision=ns.corpus_revision,
                slides=plan.slides,
                accepted_goal_indices=plan.accepted_goal_indices,
                acknowledged=True,
            )
        return _dump(service.confirm_plan(ns.project, ns.plan, request))

    return _run_sync(data, work)


def _cmd_change_commit(data: DataDir, ns) -> dict:
    request = CommitRequest(
        base_version=ns.base_version,
        corpus_revision=ns.corpus_revision,
        acknowledged=True,
    )

    def work(conn):
        return _dump(
            GenerateService(conn).commit_change(ns.project, ns.change, request)
        )

    return _run_sync(data, work)


def _cmd_deck_show(data: DataDir, ns) -> dict:
    def work(conn):
        version = ns.version if getattr(ns, "version", None) else None
        return _dump(ProjectReadService(conn).get_deck(ns.project, version))

    return _run_sync(data, work)


def _cmd_deck_restore(data: DataDir, ns) -> dict:
    request = RestoreRequest.model_validate(_read_json(ns.request))

    def work(conn):
        return _dump(RestoreService(conn).restore(ns.project, request))

    return _run_sync(data, work)


# ---------- job 命令（临时 worker 执行到终态） ----------


def _run_job(data: DataDir, provider, accept, present):
    """accept(conn, runner)->job_id；runner 已持锁并启动 worker。

    present 仅在 succeeded 时调用：blocked/failed 的 job 没有 result_ref，
    其根因由 _job_payload 透传 job.error，CLI 不臆造结果对象。
    """
    data.ensure()
    with InlineJobRunner(data, provider=provider) as runner:
        conn = data.open()
        try:
            job_id = accept(conn, runner)
            job = runner.wait(conn, job_id)
            result = present(conn, job) if job.status == "succeeded" else None
            return job, result
        finally:
            conn.close()


def _job_payload(job: Job, result: Optional[dict]) -> dict:
    payload = {"job": _dump(job)}
    if result is not None:
        payload["result"] = result
    if job.status != "succeeded" and job.error is not None:
        # blocked/failed 的根因透传（api.md 错误形状），CLI 不吞报告。
        payload["error"] = _dump(job.error)["error"]
    return payload


def _cmd_material_add(data: DataDir, provider, ns) -> dict:
    file_path = Path(ns.file)
    if not file_path.is_file():
        raise UsageError(f"material file not found: {file_path}")
    data_bytes = file_path.read_bytes()

    def accept(conn, runner):
        service = MaterialService(conn, materials_root=data.materials_root)
        accepted = service.upload(
            project_id=ns.project, original_name=file_path.name, data=data_bytes
        )
        if accepted.job_id is None:
            # duplicate：无新 job，直接以"零等待终态占位"呈现 material 现状
            material = MaterialRepository(conn).get(accepted.material_id)
            raise _DuplicateShortCircuit(
                {"accepted": _dump(accepted), "material": _dump(material)}
            )
        return accepted.job_id

    def present(conn, job):
        material = MaterialRepository(conn).get_by_job(job.id)
        return {"accepted_material_id": material.id if material else None,
                "material": _dump(material) if material else None}

    try:
        job, result = _run_job(data, provider, accept, present)
    except _DuplicateShortCircuit as short:
        return {"job": None, "result": short.payload}
    return _job_payload(job, result if job.status == "succeeded" else None)


class _DuplicateShortCircuit(Exception):
    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__("duplicate material")


def _result_id(job: Job) -> str:
    if job.result_ref is None:
        raise RuntimeError(f"succeeded job {job.id} without result_ref")
    return job.result_ref.id


def _cmd_plan_create(data: DataDir, provider, ns) -> dict:
    request = PlanRequest(corpus_revision=ns.corpus_revision)

    def accept(conn, runner):
        service = PlanService(conn)
        return service.create_plan_job(ns.project, request).job_id

    def present(conn, job):
        plan_id = _result_id(job)
        return _dump(PlanService(conn).get_plan(ns.project, plan_id))

    job, result = _run_job(data, provider, accept, present)
    return _job_payload(job, result if job.status == "succeeded" else None)


def _cmd_deck_generate(data: DataDir, provider, ns) -> dict:
    request = GenerateRequest(
        plan_id=ns.plan, base_version=ns.base_version,
        corpus_revision=ns.corpus_revision,
    )

    def accept(conn, runner):
        service = GenerateService(conn)
        return service.create_generate_job(ns.project, request).job_id

    def present(conn, job):
        change_id = _result_id(job)
        return _dump(GenerateService(conn).get_change(ns.project, change_id))

    job, result = _run_job(data, provider, accept, present)
    return _job_payload(job, result if job.status == "succeeded" else None)


def _cmd_deck_edit(data: DataDir, provider, ns) -> dict:
    request = EditRequest.model_validate(_read_json(ns.request))

    def accept(conn, runner):
        service = EditService(conn)
        return service.create_edit_job(ns.project, request).job_id

    def present(conn, job):
        change_id = _result_id(job)
        return _dump(EditService(conn).get_change(ns.project, change_id))

    job, result = _run_job(data, provider, accept, present)
    return _job_payload(job, result if job.status == "succeeded" else None)


def _cmd_deck_export(data: DataDir, provider, ns) -> dict:
    request = ExportRequest(version=ns.version, format="pptx")

    def accept(conn, runner):
        service = ExportService(conn, artifacts_root=data.artifacts_root)
        return service.create_export_job(ns.project, request).id

    def present(conn, job):
        artifact_id = _result_id(job)
        store = ArtifactStore(conn, data.artifacts_root)
        out_dir = Path(ns.out_dir) if ns.out_dir else data.root / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for art_id in (artifact_id, _report_id_of(artifact_id)):
            record = store.get(art_id)
            if record is None:
                continue
            data_bytes = store.read_verified(art_id)
            target = out_dir / artifact_filename(record)
            target.write_bytes(data_bytes)
            files.append({"artifact_id": art_id, "path": str(target),
                          "sha256": record.sha256, "mime": record.mime})
        return {"exported_files": files}

    job, result = _run_job(data, provider, accept, present)
    return _job_payload(job, result if job.status == "succeeded" else None)


def _report_id_of(pptx_artifact_id: str) -> str:
    suffix = pptx_artifact_id.removeprefix("art_")
    if suffix.endswith("_pptx"):
        return "art_" + suffix[: -len("_pptx")] + "_report"
    raise RuntimeError(f"unexpected artifact id shape: {pptx_artifact_id}")


# ---------- 参数装配 ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="courseware-core-cli",
        description="teacher-courseware 共享 core CLI（Skill 目标入口）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def data_arg(p):
        p.add_argument("--data-dir", default=None,
                       help="Skill 独立演示数据目录（或环境变量 CC_DATA_DIR）")

    p = sub.add_parser("doctor", help="环境自检（不输出任何 Key 值）")
    data_arg(p)

    project = sub.add_parser("project").add_subparsers(dest="sub", required=True)
    c = project.add_parser("create")
    c.add_argument("--request", required=True)
    data_arg(c)

    material = sub.add_parser("material").add_subparsers(dest="sub", required=True)
    a = material.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--file", required=True)
    data_arg(a)

    plan = sub.add_parser("plan").add_subparsers(dest="sub", required=True)
    pc = plan.add_parser("create")
    pc.add_argument("--project", required=True)
    pc.add_argument("--corpus-revision", type=int, required=True)
    data_arg(pc)
    pf = plan.add_parser("confirm")
    pf.add_argument("--project", required=True)
    pf.add_argument("--plan", required=True)
    pf.add_argument("--corpus-revision", type=int, required=True)
    pf.add_argument("--request", default=None)
    data_arg(pf)

    deck = sub.add_parser("deck").add_subparsers(dest="sub", required=True)
    ds = deck.add_parser("show")
    ds.add_argument("--project", required=True)
    ds.add_argument("--version", type=int, default=None)
    data_arg(ds)
    dg = deck.add_parser("generate")
    dg.add_argument("--project", required=True)
    dg.add_argument("--plan", required=True)
    dg.add_argument("--base-version", type=int, required=True)
    dg.add_argument("--corpus-revision", type=int, required=True)
    data_arg(dg)
    de = deck.add_parser("edit")
    de.add_argument("--project", required=True)
    de.add_argument("--request", required=True)
    data_arg(de)
    dr = deck.add_parser("restore")
    dr.add_argument("--project", required=True)
    dr.add_argument("--request", required=True)
    data_arg(dr)
    dx = deck.add_parser("export")
    dx.add_argument("--project", required=True)
    dx.add_argument("--version", type=int, required=True)
    dx.add_argument("--out-dir", default=None)
    data_arg(dx)

    change = sub.add_parser("change").add_subparsers(dest="sub", required=True)
    cs = change.add_parser("show")
    cs.add_argument("--project", required=True)
    cs.add_argument("--change", required=True)
    data_arg(cs)
    cc = change.add_parser("commit")
    cc.add_argument("--project", required=True)
    cc.add_argument("--change", required=True)
    cc.add_argument("--base-version", type=int, required=True)
    cc.add_argument("--corpus-revision", type=int, required=True)
    data_arg(cc)

    return parser


def _dispatch(ns, env: Mapping[str, str], provider):
    command = _command_label(ns)
    if ns.command == "doctor":
        return command, _cmd_doctor(ns, env), EXIT_OK
    data = _data_dir(ns, env)
    if command == "project-create":
        return command, _cmd_project_create(data, ns), EXIT_OK
    if command == "change-show":
        return command, _cmd_change_show(data, ns), EXIT_OK
    if command == "deck-show":
        return command, _cmd_deck_show(data, ns), EXIT_OK
    if command == "plan-confirm":
        return command, _cmd_plan_confirm(data, ns), EXIT_OK
    if command == "change-commit":
        return command, _cmd_change_commit(data, ns), EXIT_OK
    if command == "deck-restore":
        return command, _cmd_deck_restore(data, ns), EXIT_OK
    if command == "material-add":
        return command, _cmd_material_add(data, provider, ns), None
    if command == "plan-create":
        return command, _cmd_plan_create(data, provider, ns), None
    if command == "deck-generate":
        return command, _cmd_deck_generate(data, provider, ns), None
    if command == "deck-edit":
        return command, _cmd_deck_edit(data, provider, ns), None
    if command == "deck-export":
        return command, _cmd_deck_export(data, provider, ns), None
    raise UsageError(f"command not implemented: {command}")


def _job_exit(job_payload: dict) -> int:
    job = job_payload.get("job")
    if job is None or job["status"] == "succeeded":
        return EXIT_OK
    return EXIT_BUSINESS


def main(
    argv: Optional[list[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    provider: Optional[object] = None,
    stdout: Optional[TextIO] = None,
) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    out = stdout if stdout is not None else io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8"
    ) if hasattr(sys.stdout, "buffer") else sys.stdout
    request_id = f"cli_{secrets.token_hex(8)}"
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            # --help 正常路径：帮助文本已输出，不追加错误信封（review B1）
            return EXIT_OK
        _emit(out, False, "usage", {"error": {
            "code": "USAGE_ERROR",
            "message": "invalid command line arguments "
                       "(see `python -m courseware_core.cli --help`)",
            "request_id": request_id, "details": {},
        }})
        return EXIT_USAGE
    label = _command_label(ns)
    try:
        command, payload, fixed_exit = _dispatch(ns, env, provider)
        if fixed_exit is not None:
            exit_code = fixed_exit
        else:
            exit_code = _job_exit(payload)
        ok = exit_code == EXIT_OK
        _emit(out, ok, command, payload)
        return exit_code
    except UsageError as exc:
        _emit(out, False, label, {"error": {
            "code": "USAGE_ERROR", "message": str(exc),
            "request_id": request_id, "details": {},
        }})
        return EXIT_USAGE
    except ValidationError as exc:
        _emit(out, False, label, {"error": {
            "code": "VALIDATION_ERROR", "message": str(exc)[:2000],
            "request_id": request_id, "details": {"errors": exc.errors(include_url=False)[:5]},
        }})
        return EXIT_USAGE
    except WorkerAlreadyRunning as exc:
        _emit(out, False, label, {"error": {
            "code": exc.code, "message": exc.message,
            "request_id": request_id, "details": exc.details or {},
        }})
        return EXIT_ENV
    except DomainError as exc:
        _emit(out, False, label, {"error": {
            "code": exc.code, "message": exc.message,
            "request_id": request_id, "details": exc.details or {},
        }})
        return EXIT_BUSINESS
    except Exception as exc:
        _emit(out, False, label, {"error": {
            "code": "INTERNAL_ERROR",
            "message": f"{type(exc).__name__}: {exc}"[:2000],
            "request_id": request_id, "details": {},
        }})
        return EXIT_INTERNAL
