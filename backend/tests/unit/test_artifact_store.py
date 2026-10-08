import hashlib

import pytest

from courseware_core.errors import ArtifactIntegrityError, ArtifactNotFound
from courseware_core.storage.artifact_store import ArtifactStore

DATA = b"%PDF-1.4 fake artifact bytes \x00\x01"


@pytest.fixture()
def store_at(conn, insert_project, tmp_path):
    insert_project("prj_a")
    return ArtifactStore(conn, root=tmp_path / "artifacts")


def put(store, artifact_id="art_1", project_id="prj_a", version=1, **over):
    kwargs = dict(
        artifact_id=artifact_id,
        project_id=project_id,
        version=version,
        corpus_revision=1,
        data=DATA,
        mime="application/pdf",
        source_type="export",
        validation_status="passed",
        renderer_version="pptx-exporter/0.1.0",
        font_profile="noto-sans-cjk",
    )
    kwargs.update(over)
    return store.put(**kwargs)


def test_put_writes_file_and_pointer(store_at):
    record = put(store_at)
    assert record.sha256 == hashlib.sha256(DATA).hexdigest()
    assert record.size == len(DATA)
    path = store_at.root / record.rel_path
    assert path.read_bytes() == DATA


def test_read_verified_returns_bytes(store_at):
    put(store_at)
    assert store_at.read_verified("art_1") == DATA


def test_read_verified_missing_pointer_raises_not_found(store_at):
    with pytest.raises(ArtifactNotFound):
        store_at.read_verified("nope")


def test_pointer_without_file_raises_integrity_error(store_at):
    record = put(store_at)
    (store_at.root / record.rel_path).unlink()
    with pytest.raises(ArtifactIntegrityError):
        store_at.read_verified("art_1")


def test_tampered_file_raises_integrity_error(store_at):
    record = put(store_at)
    (store_at.root / record.rel_path).write_bytes(DATA + b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        store_at.read_verified("art_1")


def test_no_temp_files_left_after_put(store_at):
    put(store_at)
    leftovers = [p for p in store_at.root.rglob("*") if ".tmp" in p.name]
    assert leftovers == []


def test_put_rejects_unknown_project(store_at, conn):
    from courseware_core.errors import ProjectNotFound

    with pytest.raises(ProjectNotFound):
        put(store_at, project_id="ghost")
    assert "ghost" not in [r[0] for r in conn.execute("SELECT id FROM projects")]


def test_put_rejects_unsafe_artifact_id(store_at):
    with pytest.raises(ValueError):
        put(store_at, artifact_id="../escape")


def test_get_returns_record(store_at):
    record = put(store_at)
    assert store_at.get("art_1") == record
