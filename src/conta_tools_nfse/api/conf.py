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
    cnpj_api_url: str = ""              # URL do conta-tools-cnpj, ex: http://127.0.0.1:8765
    db_pessoas_fisicas: Path | None = None  # SQLite de pessoas físicas
    # Alíquotas-padrão de retenção (podem ser sobrescritas por prestador)
    aliq_pis: float = 0.65
    aliq_cofins: float = 3.00
    aliq_inss: float = 0.00
    aliq_ir: float = 1.50
    aliq_csll: float = 1.00


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

        [pessoas_fisicas]
        db_path = Z:\\nfse\\pessoas_fisicas.db
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

    cnpj_api_url = api_sec.get("cnpj_api_url", "").strip().rstrip("/")

    pf_sec = cfg["pessoas_fisicas"] if "pessoas_fisicas" in cfg else {}
    db_pf_raw = pf_sec.get("db_path", "").strip()
    db_pessoas_fisicas = Path(db_pf_raw) if db_pf_raw else None

    ret_sec = cfg["retencoes"] if "retencoes" in cfg else {}

    def _aliq(key: str, default: float) -> float:
        raw = ret_sec.get(key, "").strip()
        if not raw:
            return default
        try:
            return float(raw.replace(",", "."))
        except ValueError:
            return default

    return ApiConf(
        host=host,
        port=port,
        bearer_token=bearer_token,
        prestadores_dir=prestadores_dir,
        cnpj_api_url=cnpj_api_url,
        db_pessoas_fisicas=db_pessoas_fisicas,
        aliq_pis=_aliq("aliq_pis", 0.65),
        aliq_cofins=_aliq("aliq_cofins", 3.00),
        aliq_inss=_aliq("aliq_inss", 0.00),
        aliq_ir=_aliq("aliq_ir", 1.50),
        aliq_csll=_aliq("aliq_csll", 1.00),
    )
