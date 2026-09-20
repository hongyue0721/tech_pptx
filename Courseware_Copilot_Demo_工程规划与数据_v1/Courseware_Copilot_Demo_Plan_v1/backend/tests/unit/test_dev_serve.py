"""F00 开发启动装配契约：业务服务必须装配 handlers+唯一 worker，且只绑回环。

create_app(worker_handlers=None) 是测试工厂，直接当服务跑会造成"受理了 job
但永远没人执行"的假可用（AGENT_00 第二轮核对项）；启动只允许 127.0.0.1。
"""

import courseware_api.dev as dev


def test_build_dev_app_wires_all_handlers_and_worker(tmp_path):
    app = dev.build_dev_app(db_path=tmp_path / "dev.db")
    assert app.state.worker is not None
    assert set(app.state.worker._handlers) == {"parse", "plan", "generate"}
    app.state.worker._release_singleton_lock()


def test_serve_binds_loopback_only(monkeypatch, tmp_path):
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    dev.serve(db_path=tmp_path / "dev.db")
    assert captured["host"] == "127.0.0.1"
    assert captured["app"].state.worker is not None
    captured["app"].state.worker._release_singleton_lock()
