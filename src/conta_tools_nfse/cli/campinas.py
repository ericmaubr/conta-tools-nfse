"""CLI para emissão de NFS-e na Prefeitura de Campinas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from conta_tools_shared.auth.certificate import (
    cert_password_from_env,
    cnpj_from_certificate,
    load_pfx_data,
)
from conta_tools_shared.logging import formatter as log
from conta_tools_shared.version import handle_version_flags

from conta_tools_nfse.drivers.campinas import CampinasDriver
from conta_tools_nfse.excel.reader import ler_planilha_campinas, salvar_resultado
from conta_tools_nfse.excel.template import criar_template_campinas


def main_campinas(argv: list[str] | None = None) -> int:
    code = handle_version_flags("conta-tools-nfse", "conta_tools_nfse", argv)
    if code is not None:
        return code

    parser = argparse.ArgumentParser(
        prog="conta-tools-nfse campinas",
        description="Emissão de NFS-e na Prefeitura de Campinas (ABRASF 2.03)",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="subcomando")

    # --- template ---
    tmpl = sub.add_parser("template", help="Gera a planilha Excel de exemplo")
    tmpl.add_argument(
        "--saida",
        type=Path,
        default=Path("template_nfse_campinas.xlsx"),
        metavar="XLSX",
        help="Caminho de saída (default: template_nfse_campinas.xlsx)",
    )

    # --- emitir ---
    emit = sub.add_parser("emitir", help="Emite as notas a partir de uma planilha")
    emit.add_argument("--planilha", required=True, type=Path, metavar="XLSX")
    emit.add_argument("--cert", required=True, type=Path, metavar="PFX",
                      help="Certificado digital A1 (.pfx). Senha via CONTA_TOOLS_CERT_PASSWORD")
    emit.add_argument("--inscricao-municipal", required=True, metavar="IM",
                      help="Inscrição municipal do prestador em Campinas")
    emit.add_argument(
        "--ambiente",
        choices=["producao", "homologacao"],
        default="producao",
        help="Ambiente do webservice (default: producao)",
    )
    emit.add_argument(
        "--saida",
        type=Path,
        metavar="XLSX",
        help="Planilha de saída com resultado (default: <planilha>_resultado.xlsx)",
    )

    args = parser.parse_args(argv)

    if args.cmd == "template":
        return _cmd_template(args)
    if args.cmd == "emitir":
        return _cmd_emitir(args)

    parser.print_help()
    return 1


def _cmd_template(args: argparse.Namespace) -> int:
    criar_template_campinas(args.saida)
    log.log_ok(f"Template gerado: {args.saida}")
    return 0


def _cmd_emitir(args: argparse.Namespace) -> int:
    # 1. Carregar certificado
    cert_senha = cert_password_from_env()
    if not cert_senha:
        log.log_erro("Variável de ambiente CONTA_TOOLS_CERT_PASSWORD não definida.")
        return 1

    try:
        cert_data = load_pfx_data(args.cert, cert_senha)
    except Exception as e:
        log.log_erro(f"Erro ao carregar certificado: {e}")
        return 1

    prestador_cnpj = cnpj_from_certificate(cert_data)
    if not prestador_cnpj:
        log.log_erro("Não foi possível extrair o CNPJ do certificado.")
        return 1

    log.log_info(f"Certificado carregado — CNPJ prestador: {prestador_cnpj}")
    if args.ambiente == "homologacao":
        log.log_aviso("ATENÇÃO: executando em ambiente de HOMOLOGAÇÃO.")

    # 2. Ler planilha
    try:
        pedidos, erros_leitura = ler_planilha_campinas(
            args.planilha,
            prestador_cnpj,
            args.inscricao_municipal,
            args.cert,
            cert_senha,
        )
    except Exception as e:
        log.log_erro(f"Erro ao ler planilha: {e}")
        return 1

    for err in erros_leitura:
        log.log_aviso(err)

    if not pedidos:
        log.log_erro("Nenhum pedido válido na planilha.")
        return 1

    log.log_info(f"{len(pedidos)} nota(s) a emitir.")

    # 3. Emitir
    driver = CampinasDriver(ambiente=args.ambiente)
    resultados = []
    for req in pedidos:
        try:
            result = driver.emitir(req)
            log.log_ok(
                f"RPS {req.numero_rps} → NFS-e {result.numero_nota}"
                f" | verificação: {result.codigo_verificacao}"
            )
            resultados.append((req, result, None))
        except Exception as e:
            log.log_erro(f"RPS {req.numero_rps}: {e}")
            resultados.append((req, None, str(e)))

    # 4. Salvar resultado
    saida = args.saida or args.planilha.with_stem(args.planilha.stem + "_resultado")
    try:
        salvar_resultado(args.planilha, saida, resultados)
        log.log_ok(f"Resultado salvo: {saida}")
    except Exception as e:
        log.log_erro(f"Erro ao salvar resultado: {e}")

    erros_emissao = sum(1 for _, r, _ in resultados if r is None)
    if erros_emissao:
        log.log_aviso(f"{erros_emissao} nota(s) com erro. Verifique a coluna 'erro' na planilha.")
        return 1

    return 0
