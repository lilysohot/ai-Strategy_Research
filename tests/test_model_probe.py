"""Exercise the real preflight with provider responses, without outbound requests."""

import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from server.routes import models


@pytest.fixture
def probe(monkeypatch):
    from server import store

    monkeypatch.setattr(
        store,
        "get_llm_config",
        AsyncMock(return_value={"base_url": "https://provider.test/api/v3", "model": "chosen"}),
    )
    client_class = httpx.AsyncClient

    async def run(response):
        def handle(request):
            assert request.method == "POST"
            assert str(request.url) == "https://provider.test/api/v3/chat/completions"
            body = json.loads(request.content)
            assert body["model"] == "chosen"
            assert body["max_tokens"] <= 64
            assert request.headers["Authorization"] == "Bearer private-test-key"
            if isinstance(response, Exception):
                raise response
            return response

        monkeypatch.setattr(
            models.httpx,
            "AsyncClient",
            lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs),
        )
        return await models._probe_connectivity(uuid.uuid4(), uuid.uuid4(), "private-test-key")

    return run


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (401, {"message": "Your api key private-test-key is invalid"}, "API Key 无效"),
        (403, {"message": "Forbidden"}, "访问被拒绝"),
        (402, {"message": "Insufficient Balance"}, "额度不足"),
        (429, {"code": "insufficient_quota"}, "额度不足"),
        (429, {"code": "rate_limit_exceeded"}, "请求限流"),
        (
            400,
            {"message": "The supported API model names are a, b, but you passed c"},
            "模型不可用",
        ),
        (404, {"code": "model_not_found"}, "模型不可用"),
        (404, {"message": "Not Found"}, "接口路径不存在"),
        (400, {"message": "Invalid temperature"}, "请求参数不兼容"),
        (503, {"message": "Service unavailable"}, "服务暂时不可用"),
    ],
)
async def test_probe_errors_explain_reason_and_next_step(probe, status, error, expected):
    ok, detail = await probe(httpx.Response(status, json={"error": error}))
    assert ok is False
    assert expected in detail
    assert f"HTTP {status}" in detail
    assert "建议：" in detail
    assert "private-test-key" not in detail
    assert len(detail) <= 500


async def test_probe_success_checks_actual_model_call(probe):
    ok, detail = await probe(
        httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                ],
            },
        )
    )
    assert ok is True
    assert "模型调用成功" in detail


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}, ["bad"]])
async def test_probe_does_not_accept_arbitrary_http_200(probe, body):
    ok, detail = await probe(httpx.Response(200, json=body))
    assert ok is False
    assert "响应格式" in detail


async def test_probe_timeout_does_not_claim_bad_credentials(probe):
    ok, detail = await probe(httpx.ReadTimeout("private-test-key"))
    assert ok is False
    assert "超时" in detail
    assert "无法确认" in detail
    assert "private-test-key" not in detail


async def test_probe_transport_failure_does_not_echo_exception(probe):
    ok, detail = await probe(httpx.ConnectError("https://private-test-key@provider.test"))
    assert ok is False
    assert "网络连接失败" in detail
    assert "private-test-key" not in detail


async def test_probe_html_error_is_not_exposed(probe):
    ok, detail = await probe(httpx.Response(502, text="<html>private-test-key</html>"))
    assert ok is False
    assert "服务暂时不可用" in detail
    assert "private-test-key" not in detail
