"""Provider endpoints are readable; credentials are overwrite-only HTTP state."""

import importlib
import json

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from apps.admin_console.routers import system
from artemis.config.settings import PROVIDER_BASE_URL_FIELDS, Settings


@pytest.fixture
def provider_api(tmp_path, monkeypatch):
    import artemis.config as config_package
    from artemis.config import paths

    for name in (
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "GCP_API_KEY", "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY", "ZAI_API_KEY", "ANTHROPIC_API_KEY", "OPEN_ROUTER_API_KEY",
        "XAI_API_KEY", "OCR_API_KEY", "VISION_API_KEY", *PROVIDER_BASE_URL_FIELDS.values(),
    ):
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text("UNRELATED_SETTING=preserved\n", encoding="utf-8")
    config_path = tmp_path / "artemis.jsonc"
    config_path.write_text(json.dumps({"default": {"provider": "deepseek", "model": "deepseek-chat"}}))
    settings = Settings(_env_file=None, DEEPSEEK_API_KEY=SecretStr("stored-secret-a8fb21cd"))
    monkeypatch.setattr(config_package, "settings", settings)
    monkeypatch.setattr(importlib.import_module("artemis.config.settings"), "get_env_file", lambda: env)
    monkeypatch.setattr(paths, "get_env_file", lambda: env)
    monkeypatch.setattr(paths, "get_config_path", lambda _: config_path)
    monkeypatch.setattr(system.readiness_engine, "invalidate_cache", lambda: None)

    async def readiness(**_):
        return {"probes": []}

    monkeypatch.setattr(system.readiness_engine, "run_all", readiness)
    app = FastAPI()
    app.include_router(system.router)
    return app, settings, env, config_path


@pytest.mark.asyncio
async def test_endpoint_only_save_preserves_key_and_survives_reload(provider_api, monkeypatch):
    app, settings, env, config_path = provider_api
    original_config = config_path.read_text()
    settings.set_api_key("deepseek", "stored-secret-a8fb21cd", persist_to_env=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        saved = await client.post("/api/system/credentials", json={
            "provider": "deepseek", "base_url": "https://gateway.example/deepseek/v1/"
        })
        assert saved.status_code == 200
        row = saved.json()["configuration"]
        assert row["base_url"] == "https://gateway.example/deepseek/v1"
        assert row["configured"] is True
        assert row["api_key"] == "********"
        assert "stored-secret-a8fb21cd" not in saved.text
        read = await client.get("/api/system/credentials")
        deepseek = next(item for item in read.json()["providers"] if item["name"] == "deepseek")
        assert deepseek == row
        assert "a8fb21cd" not in read.text
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("DEEPSEEK_BASE_URL")
    reloaded = Settings(_env_file=env)
    key = reloaded.get_api_key("deepseek")
    assert key is not None
    assert key.get_secret_value() == "stored-secret-a8fb21cd"
    assert reloaded.get_base_url("deepseek") == "https://gateway.example/deepseek/v1"
    assert config_path.read_text() == original_config
    from dotenv import dotenv_values
    assert dotenv_values(env)["UNRELATED_SETTING"] == "preserved"


@pytest.mark.asyncio
async def test_key_overwrite_and_configured_key_test_use_the_selected_endpoint(provider_api, monkeypatch):
    app, settings, env, _ = provider_api
    requests = []
    original_client = httpx.AsyncClient

    def provider(request):
        requests.append(request)
        assert request.url == httpx.URL("https://gateway.example/provider/models")
        assert request.headers["Authorization"] == "Bearer replacement-secret-b11e9a7f"
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(provider), **kwargs
    ))
    async with original_client(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        saved = await client.post("/api/system/credentials", json={
            "provider": "deepseek", "base_url": "https://gateway.example/provider",
            "api_key": "replacement-secret-b11e9a7f"
        })
        assert saved.status_code == 200
        assert "replacement-secret-b11e9a7f" not in saved.text
        assert settings.get_api_key("deepseek").get_secret_value() == "replacement-secret-b11e9a7f"
        tested = await client.post("/api/system/credentials/test", json={"provider": "deepseek"})
        assert tested.status_code == 200
        assert tested.json()["valid"] is True
        assert "replacement-secret-b11e9a7f" not in tested.text
        assert len(requests) == 2
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    monkeypatch.delenv("DEEPSEEK_BASE_URL")
    reloaded = Settings(_env_file=env)
    key = reloaded.get_api_key("deepseek")
    assert key is not None
    assert key.get_secret_value() == "replacement-secret-b11e9a7f"


@pytest.mark.asyncio
async def test_rejected_overwrite_does_not_apply_url_or_key_and_never_echoes_it(provider_api, monkeypatch):
    app, settings, env, _ = provider_api
    original_client = httpx.AsyncClient
    before = env.read_text()
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _: httpx.Response(401, json={
            "error": {"message": "Rejected rejected-secret-61fc129b"}
        })), **kwargs
    ))
    async with original_client(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        rejected = await client.post("/api/system/credentials", json={
            "provider": "deepseek", "base_url": "https://rejected.example/v1",
            "api_key": "rejected-secret-61fc129b"
        })
        assert rejected.status_code == 400
        assert "rejected-secret-61fc129b" not in rejected.text
        assert settings.get_api_key("deepseek").get_secret_value() == "stored-secret-a8fb21cd"
        assert settings.get_base_url("deepseek") is None
        assert env.read_text() == before
        masked = await client.post("/api/system/credentials", json={
            "provider": "deepseek", "api_key": "********"
        })
        assert masked.status_code == 400
        assert settings.get_api_key("deepseek").get_secret_value() == "stored-secret-a8fb21cd"


@pytest.mark.asyncio
async def test_model_config_read_masks_nested_inline_keys_and_header_credentials(provider_api):
    app, _, _, config_path = provider_api
    secret = "inline-secret-d18ab4fc"
    config_path.write_text(json.dumps({
        "default": {"provider": "deepseek", "model": "deepseek-chat", "api_key": secret},
        "presets": {"custom": {"kwargs": {"apiKey": secret, "headers": {"Authorization": f"Bearer {secret}"}}}}
    }))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        response = await client.get("/api/system/model-config-env")
    assert response.status_code == 200
    assert secret not in response.text
    assert "d18ab4fc" not in response.text
    data = response.json()
    assert data["default_model"]["provider"] == "deepseek"
    assert data["default_model"]["api_key"] == "********"
    assert data["presets"]["custom"]["kwargs"]["headers"]["Authorization"] == "********"
    assert secret in config_path.read_text()  # Reading must not rewrite the user's config.
