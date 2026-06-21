"""Leitura do arquivo mcp.conf — configuração do cliente MCP."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class McpConf:
    api_url: str      # URL base da REST API, ex: http://192.168.1.100:8080
    bearer_token: str


def carregar_mcp_conf(caminho: Path) -> McpConf:
    """
    Lê o arquivo mcp.conf.

    Formato esperado::

        [api]
        url          = http://192.168.1.100:8080
        bearer_token = meu-token-secreto
    """
    if not caminho.exists():
        raise FileNotFoundError(f"mcp.conf não encontrado: {caminho}")

    cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cfg.read(caminho, encoding="utf-8")

    api_sec = cfg["api"] if "api" in cfg else {}

    url = api_sec.get("url", "").strip().rstrip("/")
    if not url:
        raise ValueError("Campo 'url' ausente na seção [api] de mcp.conf")

    bearer_token = api_sec.get("bearer_token", "").strip()
    if not bearer_token:
        raise ValueError("Campo 'bearer_token' ausente na seção [api] de mcp.conf")

    return McpConf(api_url=url, bearer_token=bearer_token)
