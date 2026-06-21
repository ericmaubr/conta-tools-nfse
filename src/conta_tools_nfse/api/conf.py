"""Leitura do arquivo api.conf — configuração do servidor REST."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ApiConf:
    host: str
    port: int
    bearer_token: str
    prestadores_dir: Path


def carregar_api_conf(caminho: Path) -> ApiConf:
    """
    Lê o arquivo api.conf.

    Formato esperado::

        [api]
        host          = 127.0.0.1
        port          = 8080
        bearer_token  = meu-token-secreto

        [prestadores]
        dir = Z:\\nfse\\prestadores
    """
    if not caminho.exists():
        raise FileNotFoundError(f"api.conf não encontrado: {caminho}")

    cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cfg.read(caminho, encoding="utf-8")

    api_sec = cfg["api"] if "api" in cfg else {}
    host = api_sec.get("host", "127.0.0.1").strip()
    port_raw = api_sec.get("port", "8080").strip()
    try:
        port = int(port_raw)
    except ValueError:
        raise ValueError(f"Campo 'port' inválido em api.conf: {port_raw!r}")
    bearer_token = api_sec.get("bearer_token", "").strip()
    if not bearer_token:
        raise ValueError("Campo 'bearer_token' ausente na seção [api] de api.conf")

    prest_sec = cfg["prestadores"] if "prestadores" in cfg else {}
    dir_raw = prest_sec.get("dir", "").strip()
    if not dir_raw:
        raise ValueError("Campo 'dir' ausente na seção [prestadores] de api.conf")
    prestadores_dir = Path(dir_raw)
    if not prestadores_dir.exists():
        raise FileNotFoundError(f"Diretório de prestadores não encontrado: {prestadores_dir}")

    return ApiConf(
        host=host,
        port=port,
        bearer_token=bearer_token,
        prestadores_dir=prestadores_dir,
    )
