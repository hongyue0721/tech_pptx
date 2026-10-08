import json
import time
from pathlib import Path

import jsonschema as js
import pytest
from fastapi.testclient import TestClient

from courseware_api.main import create_app
from courseware_api.wiring import build_worker_handlers

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "models.schema.json"
with SCHEMA_PATH.open(encoding="utf-8") as f:
    DEFS = json.load(f)["$defs"]

DEMO_PDF = Path(__file__).resolve().parents[3] / "demo-data" / "inputs" / "01_stm32_interrupt_notes.pdf"


def sub_schema(def_name: str) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": f"#/$defs/{def_name}",
        "$defs": DEFS,
    }


def project_body() -> dict:
    return {
        "course": {
            "topic": "STM32 中断",
            "audience": "大二",
            "duration_minutes": 45,
            "goals": ["理解 NVIC"],
            "target_slides": 8,
        },
        "consent_to_cloud_processing": True,
    }


def seed_project(client: TestClient) -> str:
    r = client.post(
        "/api/v1/projects", json=project_body(), headers={"Idempotency-Key": "seed"}
    )
    assert r.status_code == 201
    return r.json()["id"]


def upload(client: TestClient, pid: str, data: bytes, key: str, name: str = "notes.pdf"):
    return client.post(
        f"/api/v1/projects/{pid}/materials",
        files={"file": (name, data, "application/pdf")},
        headers={"Idempotency-Key": key},
    )


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "data" / "app.db")
    with TestClient(app) as c:
        yield c


def test_upload_returns_typed_202(client):
    pid = seed_project(client)
    r = upload(client, pid, DEMO_PDF.read_bytes(), "k1")
    assert r.status_code == 202
    body = r.json()
    js.validate(body, sub_schema("MaterialUploadAccepted"))
    assert body["duplicate"] is False
    assert body["job_id"]


def test_upload_requires_idempotency_key(client):
    pid = seed_project(client)
    r = client.post(
        f"/api/v1/projects/{pid}/materials",
        files={"file": ("n.pdf", DEMO_PDF.read_bytes(), "application/pdf")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_upload_replay_same_key_same_file(client):
    pid = seed_project(client)
    data = DEMO_PDF.read_bytes()
    first = upload(client, pid, data, "k1")
    second = upload(client, pid, data, "k1")
    assert second.status_code == 202
    assert second.json() == first.json()


def test_upload_same_key_different_file_conflicts(client):
    pid = seed_project(client)
    ok = upload(client, pid, DEMO_PDF.read_bytes(), "k1")
    assert ok.status_code == 202
    other = DEMO_PDF.read_bytes() + b"\n%trailer-variant\n%%EOF"
    conflict = upload(client, pid, other, "k1")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_upload_non_pdf_rejected_typed_422(client):
    pid = seed_project(client)
    r = upload(client, pid, b"not a pdf", "k1")
    assert r.status_code == 422
    body = r.json()
    js.validate(body, sub_schema("ErrorResponse"))
    assert body["error"]["code"] == "UNSUPPORTED_FILE"


def test_upload_busy_project_returns_409(client):
    pid = seed_project(client)
    first = upload(client, pid, DEMO_PDF.read_bytes(), "k1")
    assert first.status_code == 202
    other = DEMO_PDF.read_bytes() + b"\n%second\n%%EOF"
    busy = upload(client, pid, other, "k2")
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "PROJECT_BUSY"


def test_list_materials_shape(client):
    pid = seed_project(client)
    upload(client, pid, DEMO_PDF.read_bytes(), "k1")
    r = client.get(f"/api/v1/projects/{pid}/materials")
    assert r.status_code == 200
    body = r.json()
    js.validate(body, sub_schema("MaterialList"))
    assert body["corpus_revision"] == 0
    assert len(body["materials"]) == 1
    assert body["materials"][0]["status"] == "queued"


def test_end_to_end_worker_parses_material(tmp_path: Path):
    db = tmp_path / "e2e" / "app.db"
    app = create_app(
        db, worker_handlers=build_worker_handlers(db, tmp_path / "e2e" / "materials")
    )
    with TestClient(app) as client:
        pid = seed_project(client)
        accepted = upload(client, pid, DEMO_PDF.read_bytes(), "k1").json()
        # 等待窗 10s：冷启动首跑（.pyc 编译+jieba 词典首载）在满负载下可超 5s，
        # 这是异步收敛窗口不是行为断言；断言本身（ready/succeeded）不放宽。
        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            listing = client.get(f"/api/v1/projects/{pid}/materials").json()
            status = listing["materials"][0]["status"]
            if status in {"ready", "failed"}:
                break
            time.sleep(0.05)
        assert status == "ready"
        assert listing["corpus_revision"] == 1
        material = listing["materials"][0]
        assert material["pdf_pages"] >= 1
        assert material["usable_pages"] >= 1
        job = client.get(f"/api/v1/jobs/{accepted['job_id']}").json()
        assert job["status"] == "succeeded"
        assert job["result_ref"] == {"type": "material", "id": accepted["material_id"]}


def test_content_length_preflight_rejects_oversize(tmp_path: Path):
    """N1 回归：声明长度远超上限时 413，错误体仍是统一形状。"""
    from courseware_core.services.material_service import ProjectLimits

    app = create_app(
        tmp_path / "d" / "app.db",
        materials_limits=ProjectLimits(max_file_bytes=64),
    )
    with TestClient(app) as client:
        pid = seed_project(client)
        r = upload(client, pid, b"%PDF-" + b"x" * 5000, "k1")
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_worker_startup_gc_removes_orphan_files(tmp_path: Path):
    """R00-B（N4 收口）：GC 随 worker 取得独占锁后执行；孤儿与残留 tmp 清理，有指针文件保留。"""
    db = tmp_path / "gc" / "app.db"
    root = tmp_path / "gc" / "materials"
    app = create_app(db, materials_root=root)
    with TestClient(app) as client:
        pid = seed_project(client)
        accepted = upload(client, pid, DEMO_PDF.read_bytes(), "k1").json()
        stored = root / f"{accepted['material_id']}.pdf"
    # 手工制造孤儿与残留 tmp；只有带 worker（锁后）的启动才触发 GC。
    (root / "mat_ghost.pdf").write_bytes(b"%PDF-orphan")
    (root / "mat_tmp.pdf.tmp-999").write_bytes(b"partial")
    app2 = create_app(
        db, worker_handlers=build_worker_handlers(db, root), materials_root=root
    )
    with TestClient(app2):
        assert not (root / "mat_ghost.pdf").exists()
        assert not (root / "mat_tmp.pdf.tmp-999").exists()
        assert stored is not None and stored.exists()


def test_app_without_worker_does_not_gc_active_files(tmp_path: Path):
    """R00-B：未取得独占权的第二实例不得触碰数据目录——

    活动上传窗口（文件已落盘、DB 指针未提交）绝不能被误当孤儿删除。
    """
    db = tmp_path / "gc2" / "app.db"
    root = tmp_path / "gc2" / "materials"
    root.mkdir(parents=True)
    app1 = create_app(
        db, worker_handlers=build_worker_handlers(db, root), materials_root=root
    )
    with TestClient(app1):
        # 第一实例 worker 持锁、启动 GC 已跑完；此刻模拟在途上传的文件。
        (root / "mat_live.pdf").write_bytes(b"%PDF-live")
        (root / "mat_live.pdf.tmp-123").write_bytes(b"partial")
        # 第二实例 create_app（无 worker）：锁前路径不得执行任何 GC。
        app2 = create_app(db, materials_root=root)
        with TestClient(app2):
            pass
        assert (root / "mat_live.pdf").exists()
        assert (root / "mat_live.pdf.tmp-123").exists()


def test_worker_failure_releases_lock_for_next_upload(tmp_path: Path):
    """N13 回归：parse 失败经 worker 收口后锁释放，下一份上传不被 PROJECT_BUSY 卡死。"""
    db = tmp_path / "fail" / "app.db"
    root = tmp_path / "fail" / "materials"
    app = create_app(db, worker_handlers=build_worker_handlers(db, root))
    enc = (SCHEMA_PATH.parents[1] / "demo-data" / "negative" / "encrypted.pdf").read_bytes()
    with TestClient(app) as client:
        pid = seed_project(client)
        first = upload(client, pid, enc, "k1")
        assert first.status_code == 202
        job_id = first.json()["job_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            if client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "failed":
                break
            time.sleep(0.05)
        assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "failed"
        listing = client.get(f"/api/v1/projects/{pid}/materials").json()
        assert listing["materials"][0]["status"] == "failed"
        assert listing["materials"][0]["error_code"] == "PDF_ENCRYPTED"
        assert listing["corpus_revision"] == 0
        good = upload(client, pid, DEMO_PDF.read_bytes(), "k2")
        assert good.status_code == 202


def test_duplicate_upload_returns_original_without_job(client):
    pid = seed_project(client)
    data = DEMO_PDF.read_bytes()
    first = upload(client, pid, data, "k1").json()
    # 释放锁模拟任务完成后的重复上传（duplicate 语义与任务状态无关）。
    import sqlite3

    conn = sqlite3.connect(client.app.state.db_path)
    conn.execute("UPDATE projects SET active_job_id = NULL WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    second = upload(client, pid, data, "k2")
    assert second.status_code == 202
    body = second.json()
    assert body["duplicate"] is True
    assert body["material_id"] == first["material_id"]
    assert body["job_id"] is None
