"""Provider configuration must select the actual SDK endpoint and credentials."""

import asyncio
import importlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from artemis.agents.explorer.explorer import Explorer
from artemis.agents.video_analyzer.video_analyzer import VideoAnalyzer
from artemis.config.settings import PROVIDER_BASE_URL_FIELDS, Settings
from artemis.context import ArtemisContext
from artemis.llm.router import ModelEndpoint, ModelFactory
from artemis.services.llm import _resolve_endpoint
from third_party.mobile_use.config.llm import LLM


@pytest.fixture
def configured(monkeypatch):
    for field in PROVIDER_BASE_URL_FIELDS.values():
        monkeypatch.delenv(field, raising=False)
    keys = {
        'GOOGLE_API_KEY': SecretStr('google-configured-token'),
        'OPENAI_API_KEY': SecretStr('openai-configured-token'),
        'DEEPSEEK_API_KEY': SecretStr('deepseek-configured-token'),
        'ZAI_API_KEY': SecretStr('zhipu-configured-token'),
        'ANTHROPIC_API_KEY': SecretStr('anthropic-configured-token'),
        'OPEN_ROUTER_API_KEY': SecretStr('openrouter-configured-token'),
        'XAI_API_KEY': SecretStr('xai-configured-token'),
    }
    config = Settings(_env_file=None, **keys)
    for module in (
        'artemis.llm.router', 'artemis.agents.explorer.explorer',
        'artemis.agents.video_analyzer.video_analyzer',
    ):
        monkeypatch.setattr(importlib.import_module(module), 'settings', config)
    monkeypatch.setattr(ModelFactory, '_cache', {})
    monkeypatch.delenv('ARTEMIS_FAKE_LLM', raising=False)
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    return config


def sdk_client(model, provider):
    if provider == 'google':
        return model.client._api_client
    if provider == 'anthropic':
        return model._client
    return model.root_client


def sdk_url(model, provider):
    client = sdk_client(model, provider)
    value = client._http_options.base_url if provider == 'google' else client.base_url
    return str(value).rstrip('/')


async def close_model(model, provider):
    if provider == 'google':
        model.client.close()
        await model.client.aio.aclose()
    elif provider == 'anthropic':
        model._client.close()
        await model._async_client.close()
    else:
        model.root_client.close()
        await model.root_async_client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['google', 'openai', 'deepseek', 'zhipu', 'anthropic', 'openrouter', 'xai'])
@pytest.mark.parametrize('explicit', [False, True])
async def test_actual_client_uses_provider_url_or_explicit_model_override(configured, provider, explicit):
    configured.set_base_url(provider, f'https://{provider}.saved.example/api')
    endpoint = ModelEndpoint(
        provider=provider,
        model_name='gemini-2.5-flash' if provider == 'google' else 'test-model',
        api_base=f'https://{provider}.model.example/api' if explicit else None,
    )
    model = ModelFactory.get_model(endpoint)
    try:
        assert sdk_url(model, provider) == f'https://{provider}.{"model" if explicit else "saved"}.example/api'
        assert sdk_client(model, provider).api_key == f'{provider}-configured-token'
    finally:
        await close_model(model, provider)


@pytest.mark.asyncio
async def test_overwriting_url_or_key_rotates_cached_clients_without_changing_other_provider(configured):
    configured.set_base_url('deepseek', 'https://first.example/v1')
    configured.set_base_url('openai', 'https://openai.example/v1')
    endpoint = ModelEndpoint(provider='deepseek', model_name='deepseek-chat')
    first = ModelFactory.get_model(endpoint)
    other = ModelFactory.get_model(ModelEndpoint(provider='openai', model_name='gpt-test'))
    configured.set_base_url('deepseek', 'https://second.example/v1')
    second = ModelFactory.get_model(endpoint)
    configured.set_api_key('deepseek', 'replacement-configured-token')
    third = ModelFactory.get_model(endpoint)
    try:
        assert sdk_url(first, 'deepseek') == 'https://first.example/v1'
        assert sdk_url(second, 'deepseek') == 'https://second.example/v1'
        assert third.root_client.api_key == 'replacement-configured-token'
        assert first.root_client.api_key == 'deepseek-configured-token'
        assert sdk_url(other, 'openai') == 'https://openai.example/v1'
        assert other.root_client.api_key == 'openai-configured-token'
        assert ModelFactory.get_model(endpoint) is third
    finally:
        for model, provider in ((first, 'deepseek'), (second, 'deepseek'), (third, 'deepseek'), (other, 'openai')):
            await close_model(model, provider)


@pytest.mark.asyncio
async def test_model_config_override_reaches_the_actual_client(configured):
    configured.set_base_url('deepseek', 'https://provider.example/v1')
    model_config = LLM(provider='deepseek', model='deepseek-chat', base_url='https://model.example/v1')
    ctx = SimpleNamespace(llm_config=SimpleNamespace(get_agent=lambda _: model_config))
    model = ModelFactory.get_model(_resolve_endpoint(cast(ArtemisContext, ctx), 'planner'))
    try:
        assert sdk_url(model, 'deepseek') == 'https://model.example/v1'
    finally:
        await close_model(model, 'deepseek')


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [False, True])
async def test_native_clients_use_the_endpoint_without_overwriting_shared_context(configured, monkeypatch, explicit):
    configured.set_base_url('google', 'https://saved.example')
    model_config = SimpleNamespace(model='gemini-2.5-flash', base_url='https://model.example' if explicit else None)
    ctx = SimpleNamespace(
        llm_config=SimpleNamespace(explorer=model_config, utils=SimpleNamespace(video_analyzer=model_config)),
        _genai_client=None,
    )
    explorer = Explorer.__new__(Explorer)
    explorer.ctx, explorer.client = ctx, None
    client = explorer._ensure_genai_client()
    expected = 'https://model.example' if explicit else 'https://saved.example'
    assert client._api_client._http_options.base_url == expected
    assert (ctx._genai_client is None) if explicit else (ctx._genai_client is client)
    analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
    analyzer.ctx = cast(ArtemisContext, ctx)
    analyzer.video_config = SimpleNamespace(processing='static')
    analyzer.static_chunk_size_seconds = 30
    monkeypatch.setattr(
        importlib.import_module('artemis.agents.video_analyzer.video_analyzer'),
        'cleanup_abandoned_gemini_files', AsyncMock(return_value=None),
    )
    analyzer._init_engine()
    await asyncio.sleep(0)
    video_client = analyzer.client
    assert video_client is not None
    try:
        assert video_client._api_client._http_options.base_url == expected
        assert (ctx._genai_client is None) if explicit else (ctx._genai_client is client)
    finally:
        for current in (client, video_client) if explicit else (client,):
            current.close()
            await current.aio.aclose()
