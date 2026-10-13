"""Consumer behavior for independent DeepSeek and Zhipu provider credentials."""

import importlib

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import SecretStr

from artemis.config.settings import Settings
from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider
from artemis.utils.credentials_validator import validate_api_key


@pytest.mark.parametrize(
    ("provider", "env_key", "host"),
    [
        ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
        ("zhipu", "ZAI_API_KEY", "https://open.bigmodel.cn/api/paas/v4"),
    ],
)
def test_native_provider_uses_own_credentials_and_host(monkeypatch, provider, env_key, host):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.example/v1")
    monkeypatch.setenv(env_key, "native-secret")
    model_router = importlib.import_module("artemis.llm.router")

    monkeypatch.setattr(model_router, "settings", Settings(
        _env_file=None, DEEPSEEK_API_KEY=SecretStr("native-secret"),
        ZAI_API_KEY=SecretStr("native-secret"),
    ))
    model = ModelFactory.create_model(
        ModelEndpoint(provider=ModelProvider.from_string(provider), model_name="native-model")
    )
    assert str(model.root_client.base_url).rstrip("/") == host
    assert model.root_client.api_key == "native-secret"

def test_native_keys_are_independent_and_persist(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.setattr(importlib.import_module("artemis.config.settings"), "get_env_file", lambda: tmp_path / ".env")
    cfg = Settings(_env_file=None, OPENAI_API_KEY=SecretStr("openai-secret"),
                   DEEPSEEK_API_KEY=SecretStr("your_deepseek_api_key_here"),
                   ZAI_API_KEY=SecretStr("your_zai_api_key_here"))
    assert cfg.get_api_key("deepseek") is None
    assert cfg.get_api_key("zhipu") is None
    cfg.set_api_key("deepseek", "deepseek-secret", persist_to_env=True)
    cfg.set_api_key("zhipu", "zhipu-secret", persist_to_env=True)
    assert cfg.get_api_key("deepseek").get_secret_value() == "deepseek-secret"
    assert cfg.get_api_key("zhipu").get_secret_value() == "zhipu-secret"
    assert cfg.get_api_key("openai").get_secret_value() == "openai-secret"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("ZAI_API_KEY")
    reloaded = Settings(_env_file=tmp_path / ".env", OPENAI_API_KEY=SecretStr("unchanged-key"))
    assert reloaded.get_api_key("deepseek").get_secret_value() == "deepseek-secret"
    assert reloaded.get_api_key("zhipu").get_secret_value() == "zhipu-secret"
    assert reloaded.get_api_key("openai").get_secret_value() == "unchanged-key"


def test_configured_native_models_require_matching_key(monkeypatch):
    mobile_llm = importlib.import_module("third_party.mobile_use.config.llm")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    cfg = Settings(_env_file=None, DEEPSEEK_API_KEY=None, ZAI_API_KEY=None,
                   OPENAI_API_KEY=SecretStr("openai-secret"))
    monkeypatch.setattr(mobile_llm, "settings", cfg)
    for provider, env_name in (("deepseek", "DEEPSEEK_API_KEY"), ("zhipu", "ZAI_API_KEY")):
        model = mobile_llm.LLM(provider=provider, model="provider-model")
        with pytest.raises(Exception, match=env_name):
            model.validate_provider("planner")
        cfg.set_api_key(provider, "native-secret", persist_to_env=False)
        model.validate_provider("planner")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "url", "method"),
    [
        ("deepseek", "https://api.deepseek.com/models", "get"),
        ("zhipu", "https://open.bigmodel.cn/api/paas/v4/chat/completions", "post"),
    ],
)
async def test_native_key_verification_uses_live_provider_endpoint(provider, url, method):
    with patch(f"httpx.AsyncClient.{method}", new_callable=AsyncMock) as request:
        request.return_value = httpx.Response(401, json={"error": {"message": "Unauthorized"}})
        valid, message = await validate_api_key(provider, "invalid-key")
        assert not valid
        assert "Unauthorized" in message
        assert request.call_args.args[0] == url
        assert request.call_args.kwargs["headers"] == {"Authorization": "Bearer invalid-key"}
        if provider == "zhipu":
            assert request.call_args.kwargs["json"]["model"] == "glm-4.5-flash"
        request.return_value = httpx.Response(200, json={"data": []})
        valid, _ = await validate_api_key(provider, "valid-key")
        assert valid


@pytest.mark.asyncio
async def test_credentials_api_verifies_before_persisting_and_returns_status(monkeypatch):
    from fastapi import HTTPException
    from apps.admin_console.routers import system

    monkeypatch.delenv("ZAI_API_KEY", raising=False)

    settings = Settings(_env_file=None, DEEPSEEK_API_KEY=None, ZAI_API_KEY=None)
    # The router imports the exported singleton from artemis.config, not the settings module.
    import artemis.config as config_package

    monkeypatch.setattr(config_package, "settings", settings)
    monkeypatch.setattr(system.readiness_engine, "invalidate_cache", lambda: None)
    monkeypatch.setattr(system.readiness_engine, "run_all", AsyncMock(return_value="report"))
    with patch("artemis.utils.credentials_validator.validate_api_key", new_callable=AsyncMock) as validate:
        validate.return_value = (False, "Unauthorized")
        with pytest.raises(HTTPException) as failure:
            await system.update_credentials(system.UpdateCredentialsRequest(
                provider="zhipu", api_key="invalid-key", persist_to_env=False
            ))
        assert failure.value.status_code == 400
        assert settings.get_api_key("zhipu") is None
        validate.return_value = (True, "verified")
        response = await system.update_credentials(system.UpdateCredentialsRequest(
            provider="zhipu", api_key="valid-key", persist_to_env=False
        ))
        assert response["report"] == "report"
        assert settings.get_api_key("zhipu").get_secret_value() == "valid-key"
        status = await system.get_credentials()
        assert {p["name"]: p["configured"] for p in status["providers"]}["zhipu"] is True
        assert "valid-key" not in str(status)

@pytest.mark.asyncio
async def test_native_keys_report_only_masked_values(monkeypatch, tmp_path):
    import artemis.config as config_package
    from apps.admin_console.routers import system
    from artemis.core.diagnostics.probes.credentials_probe import LLMCredentialsProbe
    from artemis.core.diagnostics.probes import credentials_probe
    from artemis.config import paths

    secret = "native-very-sensitive-credential"
    settings = Settings(
        _env_file=None,
        GOOGLE_API_KEY=None,
        OPENAI_API_KEY=None,
        DEEPSEEK_API_KEY=SecretStr(secret),
        ZAI_API_KEY=SecretStr(secret),
    )
    monkeypatch.setattr(config_package, "settings", settings)
    monkeypatch.setattr(credentials_probe, "settings", settings)
    monkeypatch.setattr(paths, "get_config_path", lambda _: tmp_path / "artemis.jsonc")
    monkeypatch.setattr(paths, "get_env_file", lambda: tmp_path / ".env")
    (tmp_path / "artemis.jsonc").write_text(
        '{ "default": { "provider": "google", "model": "gemini-existing" } }'
    )
    response = await system.get_model_config_and_env()
    keys = {item["provider"]: item for item in response["env_vars"] if item["name"].endswith("API_KEY")}
    assert keys["deepseek"]["is_set"] and keys["zhipu"]["is_set"]
    assert secret not in str(response)
    assert response["default_model"]["provider"] == "google"
    result = await LLMCredentialsProbe().probe()
    assert secret not in str(result.metadata)
    assert {p["provider"] for p in result.metadata["providers"]} >= {"deepseek", "zhipu"}

