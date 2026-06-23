from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import create_app


def make_client(monkeypatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    get_settings.cache_clear()
    return TestClient(create_app())


def test_create_report_returns_download_url(monkeypatch, tmp_path: Path) -> None:
    # 常规：端点调 builder 成功 → 200 + 下载信息（服务端读持久化结果，请求体不含分析数据）。
    from app.agent.report.builder import ReportArtifact
    import app.api.routes.report as report_route

    async def fake_build(*, conversation_id, user_id, imagery_id):
        assert conversation_id == "conv-1"
        return ReportArtifact(
            imagery_id="d722c20e1234",
            filename="report_x.docx",
            download_url="/api/imagery/d722c20e1234/results/report_x.docx",
        )

    monkeypatch.setattr(report_route, "build_conversation_report", fake_build)
    client = make_client(monkeypatch, tmp_path)

    resp = client.post("/api/reports", json={"conversation_id": "conv-1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["download_url"].endswith("report_x.docx")
    assert body["imagery_id"] == "d722c20e1234"


def test_create_report_maps_error_codes_to_status(monkeypatch, tmp_path: Path) -> None:
    # 异常分支：ReportError 的 code 映射到对应 HTTP 状态（非属主 404 / 无结果 409）。
    from app.agent.report.builder import ReportError
    import app.api.routes.report as report_route

    cases = {
        "conversation_forbidden": 404,
        "no_analysis": 409,
    }
    for code, expected_status in cases.items():
        async def fake_build(*, conversation_id, user_id, imagery_id, _code=code):
            raise ReportError("拒绝", code=_code)

        monkeypatch.setattr(report_route, "build_conversation_report", fake_build)
        client = make_client(monkeypatch, tmp_path)
        resp = client.post("/api/reports", json={"conversation_id": "conv-1"})
        assert resp.status_code == expected_status, code


def test_create_report_rejects_bad_imagery_id(monkeypatch, tmp_path: Path) -> None:
    # 非法输入：imagery_id 格式非法 → 422（pydantic 校验，未触达 builder）。
    client = make_client(monkeypatch, tmp_path)
    resp = client.post("/api/reports", json={"conversation_id": "c", "imagery_id": "BAD"})
    assert resp.status_code == 422


def test_download_route_serves_docx_media_type(monkeypatch, tmp_path: Path) -> None:
    # 下载路由对 .docx 返回正确 media_type（nosniff 要求 Content-Type 准确）。
    imagery_id = "d722c20e1234"
    results_dir = tmp_path / "imagery" / imagery_id / "results"
    results_dir.mkdir(parents=True)
    (results_dir / "report_x.docx").write_bytes(b"PK\x03\x04 fake docx")
    # 归属校验读 metadata.json 的 owner
    (tmp_path / "imagery" / imagery_id / "metadata.json").write_text(
        '{"owner_user_id":"' + get_settings().default_user_id + '","filename":"x.tif"}',
        encoding="utf-8",
    )
    client = make_client(monkeypatch, tmp_path)

    resp = client.get(f"/api/imagery/{imagery_id}/results/report_x.docx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
