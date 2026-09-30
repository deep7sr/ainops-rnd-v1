"""Settings, read from the repo-root .env (never committed) and the environment.

Secrets (LLM key, device passwords, Neo4j password) stay in .env. Code only ever sees them through
these settings or `device_credentials`, and never logs them.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


class Settings(BaseSettings):
    # "live": log into the EVE-NG lab with Netmiko (and record every output for replay).
    # "replay": answer from the recorded outputs in fixtures/lab; no device is contacted.
    lab_executor: Literal["live", "replay"] = "replay"
    lab_eve_host: str = ""
    lab_inventory: Path = REPO_ROOT / "lab" / "inventory.yaml"
    fixtures_dir: Path = REPO_ROOT / "fixtures" / "lab"
    logs_dir: Path = REPO_ROOT / "logs"

    # MCP servers (streamable HTTP, local only).
    mcp_network_port: int = 8101
    mcp_topology_port: int = 8102

    # Knowledge graph.
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("")

    # LLM through an OpenAI-compatible API (Groq in the lab, the company LiteLLM gateway later).
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model_reasoning: str = ""
    llm_model_fast: str = ""


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
