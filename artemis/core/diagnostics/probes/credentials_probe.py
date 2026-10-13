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

"""LLM & Multimodal Vision Credentials Readiness Probe."""

import os
from artemis.config import settings
from artemis.core.diagnostics.probes.base import BaseProbe
from artemis.core.diagnostics.schema import (
    ProbeAction,
    ProbeCategory,
    ProbeResult,
    ProbeStatus,
)


class LLMCredentialsProbe(BaseProbe):
    """Probe verifying Gemini and multi-provider multimodal LLM credentials."""

    @property
    def probe_id(self) -> str:
        return "gemini_api_key"

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.CREDENTIALS

    @property
    def is_blocker(self) -> bool:
        return True

    # Readiness reports are client-visible; never derive a preview from a key.
    _KEY_MASK = "********"

    async def probe(self) -> ProbeResult:
        from artemis.config.settings import is_placeholder_key

        configured_providers: list[dict[str, Any]] = []
        for provider, label in (
            ("google", "Gemini"),
            ("openai", "ChatGPT"),
            ("deepseek", "DeepSeek"),
            ("zhipu", "Zhipu"),
            ("anthropic", "Claude"),
            ("openrouter", "OpenRouter"),
            ("xai", "xAI (Grok)"),
        ):
            secret = settings.get_api_key(provider)
            if secret and not is_placeholder_key(secret):
                configured_providers.append(
                    {"provider": provider, "label": label, "masked": self._KEY_MASK}
                )

        # Detect additional providers without including environment values in the report.
        for env_var, label, prov_id in (
            ("GROQ_API_KEY", "Groq", "groq"),
            ("OPENAI_BASE_URL", "Custom OpenAI Endpoint", "custom"),
            ("OLLAMA_BASE_URL", "Local Ollama", "ollama"),
            ("VLLM_BASE_URL", "vLLM Endpoint", "vllm"),
            ("VERTEX_AI_PROJECT", "Google Cloud Vertex AI", "vertexai"),
        ):
            value = os.environ.get(env_var, "").strip()
            if value and not is_placeholder_key(value):
                configured_providers.append(
                    {"provider": prov_id, "label": label, "masked": self._KEY_MASK}
                )

        ocr_key = settings.get_api_key("ocr")
        metadata = {
            "configured_count": len(configured_providers),
            "providers": configured_providers,
            "has_ocr_key": bool(ocr_key and not is_placeholder_key(ocr_key)),
        }

        # Case 1: Gemini API Key configured (Standard / Recommended)
        if any(p["provider"] == "google" for p in configured_providers):
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Multimodal LLM API Key",
                status=ProbeStatus.PASS,
                is_blocker=self.is_blocker,
                summary="Active (Gemini)",
                description="Gemini multimodal API credential is active and ready for vision and reasoning.",
                metadata=metadata,
                actions=[
                    ProbeAction(
                        action_type="hint",
                        label="Provider Active",
                        payload="Gemini 2.5 Flash / Pro Multimodal Engine is enabled.",
                    )
                ],
            )

        # Case 2: Other LLM provider configured
        if configured_providers:
            first_p = configured_providers[0]
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Multimodal LLM API Key",
                status=ProbeStatus.PASS,
                is_blocker=self.is_blocker,
                summary=f"Active ({first_p['label']})",
                description=f"{first_p['label']} multimodal API credential is active.",
                metadata=metadata,
                actions=[
                    ProbeAction(
                        action_type="hint",
                        label="Provider Active",
                        payload=f"{first_p['label']} multimodal vision endpoint is active.",
                    )
                ],
            )

        # Case 3: No LLM key configured
        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title="Multimodal LLM API Key",
            status=ProbeStatus.FAIL,
            is_blocker=self.is_blocker,
            summary="Key Missing",
            description="No Multimodal LLM credential (e.g. GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY) found in environment or .env file.",
            metadata=metadata,
            actions=[
                ProbeAction(
                    action_type="command",
                    label="Run Artemis Init",
                    payload="artemis init",
                ),
                ProbeAction(
                    action_type="link",
                    label="Get Google AI Studio Key",
                    payload="https://aistudio.google.com/app/apikey",
                ),
            ],
        )


class VisionOCRProbe(BaseProbe):
    """Probe verifying optional Google Cloud Vision OCR credentials."""

    @property
    def probe_id(self) -> str:
        return "vision_ocr_key"

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.CREDENTIALS

    @property
    def is_blocker(self) -> bool:
        return False

    _KEY_MASK = "********"

    async def probe(self) -> ProbeResult:
        from artemis.utils.ocr_api import is_ocr_configured

        ocr_key = settings.get_api_key("ocr")
        is_configured = is_ocr_configured() and ocr_key is not None

        if is_configured:
            return ProbeResult(
                id=self.probe_id,
                category=self.category,
                title="Vision OCR API Key (Optional)",
                status=ProbeStatus.PASS,
                is_blocker=False,
                summary="Active & Configured",
                description="Google Cloud Vision OCR is active for image text recognition.",
                metadata={"configured": True, "masked_key": self._KEY_MASK},
                actions=[
                    ProbeAction(
                        action_type="hint",
                        label="OCR Enabled",
                        payload="OCR is active and will fuse text with UI XML hierarchy.",
                    )
                ],
            )

        return ProbeResult(
            id=self.probe_id,
            category=self.category,
            title="Vision OCR API Key (Optional)",
            status=ProbeStatus.PASS,
            is_blocker=False,
            summary="Not Configured (Optional)",
            description="OCR_API_KEY is not set. Perception uses the UI XML hierarchy without OCR.",
            metadata={"configured": False},
            actions=[
                ProbeAction(
                    action_type="hint",
                    label="Standard XML Perception",
                    payload="Artemis uses pure UI layout parsing and Set-of-Marks visual grounding.",
                )
            ],
        )
