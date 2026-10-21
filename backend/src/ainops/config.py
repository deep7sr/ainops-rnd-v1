"""Settings, read from the repo-root .env (never committed) and the environment.

Secrets (LLM key, device passwords, Neo4j password) stay in .env. Code only ever sees them through
these settings or `device_credentials`, and never logs them.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


class Settings(BaseSettings):
    # AINOPS always works on the live lab: the EVE-NG host whose consoles it logs into.
    lab_eve_host: str = ""
    # True when those consoles are the simulated copy of the lab on this laptop
    # (scripts/start-all.ps1 -Sim). The UI says so, so its results are never taken for real ones.
    lab_simulated: bool = False
    lab_inventory: Path = REPO_ROOT / "lab" / "inventory.yaml"
    logs_dir: Path = REPO_ROOT / "logs"
    # Expert skills for frequent questions (skills/<name>/SKILL.md, see agent/skills.py).
    skills_dir: Path = REPO_ROOT / "skills"

    # MCP servers (streamable HTTP, local only).
    mcp_network_port: int = 8101
    mcp_topology_port: int = 8102

    # Knowledge graph.
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")

    # Which LLM the agent uses:
    # "azure_openai":      the company Azure AI Foundry deployment (AZURE_AI_* and MODEL below).
    #                      Reachable only from the UST network or VPN (firewall on the resource).
    # "openai_compatible": any OpenAI-compatible API (LLM_* below; Groq in the lab, LiteLLM later).
    llm_provider: Literal["azure_openai", "openai_compatible"] = "openai_compatible"

    azure_ai_endpoint: str = ""
    azure_ai_api_key: SecretStr = SecretStr("")
    azure_api_version: str = ""
    azure_model: str = Field(default="", validation_alias="MODEL")  # the deployment name

    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model_reasoning: str = ""
    llm_model_fast: str = ""

    @property
    def llm_model(self) -> str:
        return self.azure_model if self.llm_provider == "azure_openai" else self.llm_model_reasoning

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "azure_openai":
            key = self.azure_ai_api_key.get_secret_value()
            return bool(
                self.azure_ai_endpoint and key and self.azure_api_version and self.azure_model
            )
        return bool(self.llm_base_url and self.llm_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()


def device_credentials(credential_ref: str) -> tuple[str, str]:
    """Username and password for a credential_ref, from AINOPS_CRED_<REF>_USERNAME/_PASSWORD."""
    prefix = "AINOPS_CRED_" + credential_ref.upper().replace("-", "_")
    username = os.environ.get(prefix + "_USERNAME", "")
    password = os.environ.get(prefix + "_PASSWORD", "")
    if not username:
        raise LookupError(f"no login configured for credential '{credential_ref}' (see .env)")
    return username, password
