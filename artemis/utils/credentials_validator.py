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

"""Validation utility to verify LLM and Vision API keys against live provider endpoints."""

from urllib.parse import quote

import httpx

from artemis.config.settings import is_placeholder_key, settings
from artemis.llm.google.provider import is_google_family_provider, is_google_provider

from third_party.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

# Minimal 1x1 PNG transparent pixel base64 for Vision API testing
_TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


def _redact_error(message: str, api_key: str) -> str:
    """Never expose a credential echoed by an upstream API or transport error."""
    for secret in (api_key, quote(api_key, safe="")):
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message


def _extract_error_message(resp: httpx.Response, api_key: str = "") -> str:
    """Extract a human-friendly error message from a provider HTTP response."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            # Google style: {"error": {"message": "..."}}
            err_obj = data.get("error")
            if isinstance(err_obj, dict):
                msg = err_obj.get("message")
                if msg:
                    return _redact_error(str(msg), api_key)
            elif isinstance(err_obj, str):
                return _redact_error(err_obj, api_key)

            # OpenAI / Anthropic / OpenRouter style
            if "message" in data:
                return _redact_error(str(data["message"]), api_key)
            if "detail" in data:
                return _redact_error(str(data["detail"]), api_key)
    except ValueError:
        # Response body is not valid JSON; fall through to the text fallback.
        pass

    # Fallback to response text or HTTP status
    text = resp.text.strip()
    if text and len(text) < 200:
        return _redact_error(text, api_key)
    return _redact_error(f"HTTP {resp.status_code}: {resp.reason_phrase}", api_key)


async def validate_api_key(
    provider: str,
    api_key: str,
    base_url: str | None = None,
    timeout: float = 12.0,
) -> tuple[bool, str]:
    """Tests if the provided API key is valid and usable with the corresponding provider.

    Args:
        provider: Provider identifier (e.g. 'google', 'gemini', 'ocr', 'openai', 'anthropic', etc.)
        api_key: Secret API key string.
        base_url: Optional custom endpoint URL.
        timeout: Request timeout in seconds.

    Returns:
        tuple[bool, str]: (is_valid, descriptive_message)
    """
    clean_provider = provider.strip().lower()
    clean_key = api_key.strip()

    if not clean_key:
        return False, "API key cannot be empty."

    # Reject template values before making a live request.
    if is_placeholder_key(clean_key):
        return False, "Please enter a real API key instead of the placeholder."

    provider_base_url = base_url
    if provider_base_url is None and clean_provider in (
        "google",
        "gemini",
        "openai",
        "deepseek",
        "zhipu",
        "anthropic",
        "claude",
        "openrouter",
        "xai",
        "grok",
    ):
        provider_base_url = settings.get_base_url(clean_provider)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if is_google_family_provider(clean_provider):
                # Test Google Gemini via generativelanguage API
                # The key travels in a header, never in the URL: httpx logs request
                # URLs at INFO level and those logs end up in files.
                host = (
                    provider_base_url
                    if is_google_provider(clean_provider) or base_url is not None
                    else None
                )
                url = (
                    f"{(host or 'https://generativelanguage.googleapis.com').rstrip('/')}"
                    "/v1beta/models?pageSize=1"
                )
                resp = await client.get(url, headers={"x-goog-api-key": clean_key})
                if resp.status_code == 200:
                    return True, "Google Gemini API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"Gemini API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider in ("ocr", "vision", "google_vision"):
                # Test Google Cloud Vision OCR API
                url = "https://vision.googleapis.com/v1/images:annotate"
                payload = {
                    "requests": [
                        {
                            "image": {"content": _TINY_PNG_B64},
                            "features": [{"type": "TEXT_DETECTION"}],
                        }
                    ]
                }
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json", "x-goog-api-key": clean_key},
                )
                if resp.status_code == 200:
                    return True, "Google Cloud Vision OCR API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"Vision OCR API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider == "openai":
                endpoint = (
                    f"{provider_base_url.rstrip('/')}/models"
                    if provider_base_url
                    else "https://api.openai.com/v1/models"
                )
                resp = await client.get(endpoint, headers={"Authorization": f"Bearer {clean_key}"})
                if resp.status_code == 200:
                    return True, "OpenAI API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"OpenAI API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider == "deepseek":
                endpoint = (
                    f"{(provider_base_url or 'https://api.deepseek.com').rstrip('/')}/models"
                )
                resp = await client.get(endpoint, headers={"Authorization": f"Bearer {clean_key}"})
                if resp.status_code == 200:
                    return True, "DeepSeek API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"DeepSeek API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider == "zhipu":
                # Zhipu documents chat completions, not an authenticated
                # model-list endpoint. A minimal real request verifies access.
                endpoint = (
                    f"{(provider_base_url or 'https://open.bigmodel.cn/api/paas/v4').rstrip('/')}"
                    "/chat/completions"
                )
                resp = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {clean_key}"},
                    json={
                        "model": "glm-4.5-flash",
                        "messages": [{"role": "user", "content": "hi"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    return True, "Zhipu API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"Zhipu API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider in ("anthropic", "claude"):
                host = (provider_base_url or "https://api.anthropic.com").rstrip("/")
                url = f"{host}/models" if host.endswith("/v1") else f"{host}/v1/models"
                resp = await client.get(
                    url,
                    headers={
                        "x-api-key": clean_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    return True, "Anthropic Claude API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"Anthropic API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider == "openrouter":
                url = (
                    f"{(provider_base_url or 'https://openrouter.ai/api/v1').rstrip('/')}"
                    "/auth/key"
                )
                resp = await client.get(url, headers={"Authorization": f"Bearer {clean_key}"})
                if resp.status_code == 200:
                    return True, "OpenRouter API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"OpenRouter API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider in ("xai", "grok"):
                url = f"{(provider_base_url or 'https://api.x.ai/v1').rstrip('/')}/models"
                resp = await client.get(url, headers={"Authorization": f"Bearer {clean_key}"})
                if resp.status_code == 200:
                    return True, "xAI API key verified successfully."
                err_msg = _extract_error_message(resp, clean_key)
                return False, f"xAI API verification failed ({resp.status_code}): {err_msg}"

            elif clean_provider in ("ollama", "vllm", "custom"):
                if base_url:
                    endpoint = f"{base_url.rstrip('/')}/models"
                    headers = (
                        {"Authorization": f"Bearer {clean_key}"} if clean_key != "EMPTY" else {}
                    )
                    resp = await client.get(endpoint, headers=headers)
                    if resp.status_code == 200:
                        safe_url = _redact_error(base_url, clean_key)
                        return True, f"Custom endpoint ({safe_url}) verified successfully."
                    err_msg = _extract_error_message(resp, clean_key)
                    return (
                        False,
                        f"Custom endpoint verification failed ({resp.status_code}): {err_msg}",
                    )
                return True, "Custom endpoint configured."

            else:
                # Unknown provider - fallback to basic length check
                if len(clean_key) >= 8:
                    return True, f"Credentials for {provider} configured."
                return False, f"Invalid API key format for {provider}."

    except httpx.TimeoutException:
        logger.warning(f"Timeout verifying API key for {clean_provider}")
        return (
            False,
            f"Connection to {clean_provider.capitalize()} API timed out. Please check network/proxy settings.",
        )
    except httpx.RequestError as exc:
        safe_error = _redact_error(str(exc), clean_key)
        logger.warning(f"Network error verifying API key for {clean_provider}: {safe_error}")
        return False, f"Network error connecting to {clean_provider.capitalize()} API: {safe_error}"
    except Exception as exc:
        safe_error = _redact_error(str(exc), clean_key)
        logger.error(f"Unexpected error validating API key for {clean_provider}: {safe_error}")
        return False, f"Validation error: {safe_error}"
