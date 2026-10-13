# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import httpx
import pytest

from artemis.utils.credentials_validator import _extract_error_message, validate_api_key
from artemis.config.settings import PROVIDER_BASE_URL_FIELDS, Settings


def test_extract_error_message():
    resp_google = MagicMock()
    resp_google.json.return_value = {"error": {"message": "API key invalid."}}
    assert _extract_error_message(resp_google) == "API key invalid."

    resp_openai = MagicMock()
    resp_openai.json.return_value = {"message": "Incorrect API key."}
    assert _extract_error_message(resp_openai) == "Incorrect API key."

    resp_fallback = MagicMock()
    resp_fallback.json.side_effect = ValueError("JSON parse error")
    resp_fallback.text = "Raw error text"
    assert _extract_error_message(resp_fallback) == "Raw error text"


@pytest.mark.asyncio
async def test_validate_empty_and_placeholder():
    is_valid, msg = await validate_api_key("google", "")
    assert not is_valid
    assert "empty" in msg.lower()

    is_valid, msg = await validate_api_key("google", "API_KEY")
    assert not is_valid
    assert "placeholder" in msg.lower()


@pytest.mark.asyncio
async def test_validate_gemini_success():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        is_valid, msg = await validate_api_key("google", "valid_key_12345")
        assert is_valid
        assert "verified successfully" in msg


@pytest.mark.asyncio
async def test_validate_gemini_failure():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": {"message": "API key not valid."}}
        mock_get.return_value = mock_resp

        is_valid, msg = await validate_api_key("google", "bad_key_12345")
        assert not is_valid
        assert "API key not valid" in msg


@pytest.mark.asyncio
async def test_validate_ocr_success():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        is_valid, msg = await validate_api_key("ocr", "valid_ocr_key_12345")
        assert is_valid
        assert "verified successfully" in msg



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,suffix",
    [
        ("google", "/v1beta/models"),
        ("openai", "/models"),
        ("deepseek", "/models"),
        ("zhipu", "/chat/completions"),
        ("anthropic", "/v1/models"),
        ("openrouter", "/auth/key"),
        ("xai", "/models"),
    ],
)
async def test_validation_uses_saved_endpoint_and_explicit_override(monkeypatch, provider, suffix):
    settings = Settings(_env_file=None, **dict.fromkeys(PROVIDER_BASE_URL_FIELDS.values()))
    saved_base = f"https://{provider}.saved.example"
    setattr(settings, PROVIDER_BASE_URL_FIELDS[provider], saved_base)
    monkeypatch.setattr("artemis.utils.credentials_validator.settings", settings)
    original_client = httpx.AsyncClient
    explicit_base = f"https://{provider}.explicit.example"

    def upstream(request):
        supplied = (
            request.headers.get("x-goog-api-key")
            or request.headers.get("x-api-key")
            or request.headers.get("authorization", "").removeprefix("Bearer ")
        )
        authorized = (
            str(request.url.copy_with(query=None)) in {saved_base + suffix, explicit_base + suffix}
            and request.method == ("POST" if provider == "zhipu" else "GET")
            and supplied == "validation-test-secret"
        )
        return httpx.Response(200 if authorized else 401, json={})

    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(upstream), **kwargs),
    )
    valid, _ = await validate_api_key(provider, "validation-test-secret")
    assert valid
    valid, _ = await validate_api_key(provider, "validation-test-secret", base_url=explicit_base)
    assert valid
    valid, _ = await validate_api_key(provider, "validation-test-secret", base_url="https://wrong.example")
    assert not valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, json={"error": {"message": "bad test-secret credential"}}),
        httpx.Response(401, text="bad test-secret credential"),
    ],
)
async def test_validation_redacts_upstream_secret(response):
    with (
        patch("artemis.utils.credentials_validator.settings", SimpleNamespace(get_base_url=lambda _: None)),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=response),
    ):
        valid, message = await validate_api_key("openai", "test-secret")
    assert not valid
    assert "test-secret" not in message


@pytest.mark.asyncio
async def test_validation_redacts_network_exception_in_response_and_logs(caplog):
    with (
        patch("artemis.utils.credentials_validator.settings", SimpleNamespace(get_base_url=lambda _: None)),
        patch("httpx.AsyncClient.get", new_callable=AsyncMock,
              side_effect=httpx.RequestError("test-secret is invalid")),
    ):
        valid, message = await validate_api_key("deepseek", "test-secret")
    assert not valid
    assert "test-secret" not in message
    assert "test-secret" not in caplog.text
