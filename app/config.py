"""Application settings, read from the environment (and a local .env if present).

Azure AI Foundry exposes two endpoint shapes and this app supports both:

  * an Azure OpenAI style endpoint  — https://<resource>.openai.azure.com/
  * a Foundry project models endpoint — https://<resource>.services.ai.azure.com/

Either way we talk to it over the Azure OpenAI protocol, because that is the
path with first-class tool-calling support, which the chatbot depends on.

Authentication is API key if one is supplied, otherwise Entra ID via
DefaultAzureCredential (managed identity in Azure, `az login` locally). Leaving
both unset is a supported state: the app still runs and the chat falls back to
an clearly-labelled offline responder.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Finance Workflow Dashboard"
    data_path: Path = REPO_ROOT / "data" / "workflows.json"

    # --- Azure AI Foundry -------------------------------------------------
    azure_ai_endpoint: str = ""
    azure_ai_api_key: str = ""
    azure_ai_deployment: str = "gpt-4o"
    azure_ai_api_version: str = "2024-10-21"

    # Cap the tool-calling loop so a confused model cannot spin indefinitely.
    chat_max_tool_iterations: int = 5
    chat_temperature: float = 0.2

    @property
    def azure_configured(self) -> bool:
        """True when there is at least an endpoint and a deployment to call.

        The API key is optional — without one we fall back to Entra ID — so it
        deliberately does not feature in this check.
        """
        return bool(self.azure_ai_endpoint and self.azure_ai_deployment)

    @property
    def azure_openai_endpoint(self) -> str:
        """Normalise a Foundry project endpoint to its Azure OpenAI form.

        A `*.services.ai.azure.com` endpoint is often copied from the portal
        with a `/models` or `/api/projects/...` suffix; the Azure OpenAI client
        wants the bare resource root and appends its own path.
        """
        endpoint = self.azure_ai_endpoint.strip().rstrip("/")
        for suffix in ("/models", "/openai"):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
        return endpoint


@lru_cache
def get_settings() -> Settings:
    return Settings()
