"""Leitura do arquivo .conf de configuração do prestador NFS-e."""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass
from pathlib import Path

from conta_tools_shared.auth.certificate import cert_password_from_env


@dataclass
class NfseConf:
    cert_path: Path
    inscricao_municipal: str
    cert_senha: str           # nunca logar
    ambiente: str = "producao"
    optante_simples: bool = False
    serie_rps: str = "1"
    nome: str = ""            # nome de exibição na UI (API)
    municipio: str = ""       # "campinas" | "sao_paulo"
    output_dir: Path | None = None  # diretório de saída para XMLs emitidos


def carregar_conf(caminho: Path) -> NfseConf:
    """
    Lê o arquivo .conf do prestador.

    Formato esperado:
        [prestador]
        cert = C:\\certs\\empresa.pfx
        inscricao_municipal = 123456
        senha = ...              ; opcional — se ausente, usa CONTA_TOOLS_CERT_PASSWORD

        [nfse]
        ambiente = producao      ; ou homologacao (default: producao)

    Prioridade da senha: conf > CONTA_TOOLS_CERT_PASSWORD.
    """
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {caminho}")

    cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cfg.read(caminho, encoding="utf-8")

    if "prestador" not in cfg:
        raise ValueError(f"Seção [prestador] não encontrada em {caminho}")

    prestador = cfg["prestador"]

    cert_raw = prestador.get("cert", "").strip()
    if not cert_raw:
        raise ValueError(f"Campo 'cert' ausente na seção [prestador] de {caminho}")
    cert_path = Path(cert_raw)

    inscricao = prestador.get("inscricao_municipal", "").strip()
    if not inscricao:
        raise ValueError(f"Campo 'inscricao_municipal' ausente na seção [prestador] de {caminho}")

    # Senha: conf tem prioridade; fallback para variável de ambiente
    senha = prestador.get("senha", "").strip() or cert_password_from_env()
    if not senha:
        raise ValueError(
            f"Senha do certificado não encontrada. "
            f"Defina 'senha' em [{caminho.name}] ou a variável CONTA_TOOLS_CERT_PASSWORD."
        )

    optante_raw = prestador.get("optante_simples", "N").strip().upper()
    optante_simples = optante_raw in ("S", "SIM", "TRUE", "1")

    serie_rps = prestador.get("serie_rps", "1").strip() or "1"
    nome = prestador.get("nome", "").strip()
    municipio = prestador.get("municipio", "").strip().lower()

    output_dir_raw = prestador.get("output_dir", "").strip()
    output_dir = Path(output_dir_raw) if output_dir_raw else None

    nfse_sec = cfg["nfse"] if "nfse" in cfg else {}
    ambiente = nfse_sec.get("ambiente", "producao").strip()
    if ambiente not in ("producao", "homologacao"):
        raise ValueError(f"Campo 'ambiente' inválido: {ambiente!r}. Use 'producao' ou 'homologacao'.")

    return NfseConf(
        cert_path=cert_path,
        inscricao_municipal=inscricao,
        cert_senha=senha,
        ambiente=ambiente,
        optante_simples=optante_simples,
        serie_rps=serie_rps,
        nome=nome,
        municipio=municipio,
        output_dir=output_dir,
    )
