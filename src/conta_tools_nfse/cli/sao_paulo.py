"""CLI para emissão de NFS-e na Prefeitura de São Paulo."""

from __future__ import annotations

import argparse
from pathlib import Path

from conta_tools_shared.auth.certificate import cnpj_from_certificate, load_pfx_data
from conta_tools_shared.logging import formatter as log
from conta_tools_shared.version import handle_version_flags

from conta_tools_nfse.conf import carregar_conf
from conta_tools_nfse.drivers.sao_paulo import SaoPauloDriver
from conta_tools_nfse.excel.reader import ler_planilha_sp, salvar_resultado
from conta_tools_nfse.excel.template import criar_template_sp


def main_sao_paulo(argv: list[str] | None = None) -> int:
    code = handle_version_flags("conta-tools-nfse", "conta_tools_nfse", argv)
    if code is not None:
        return code

    parser = argparse.ArgumentParser(
        prog="conta-tools-nfse sao_paulo",
        description="Emissão de NFS-e na Prefeitura de São Paulo",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="subcomando")

    # --- template ---
    tmpl = sub.add_parser("template", help="Gera a planilha Excel de exemplo")
    tmpl.add_argument(
        "--saida",
        type=Path,
        default=Path("template_nfse_sp.xlsx"),
        metavar="XLSX",
        help="Caminho de saída (default: template_nfse_sp.xlsx)",
    )

    # --- emitir ---
    emit = sub.add_parser("emitir", help="Emite as notas a partir de uma planilha")
    emit.add_argument("--planilha", required=True, type=Path, metavar="XLSX")
    emit.add_argument(
        "--conf",
        required=True,
        type=Path,
        metavar="CONF",
        help="Arquivo .conf do prestador (cert, inscrição municipal, senha, ambiente)",
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
    criar_template_sp(args.saida)
    log.log_ok(f"Template gerado: {args.saida}")
    return 0


def _cmd_emitir(args: argparse.Namespace) -> int:
    try:
        conf = carregar_conf(args.conf)
    except Exception as e:
        log.log_erro(f"Erro ao ler configuração: {e}")
        return 1

    if conf.ambiente == "homologacao":
        log.log_aviso("ATENÇÃO: executando em ambiente de HOMOLOGAÇÃO.")

    try:
        cert_data = load_pfx_data(conf.cert_path, conf.cert_senha)
    except Exception as e:
        log.log_erro(f"Erro ao carregar certificado: {e}")
        return 1

    prestador_cnpj = cnpj_from_certificate(cert_data)
    if not prestador_cnpj:
        log.log_erro("Não foi possível extrair o CNPJ do certificado.")
        return 1

    log.log_info(f"Certificado carregado — CNPJ prestador: {prestador_cnpj}")

    try:
        pedidos, erros_leitura = ler_planilha_sp(
            args.planilha,
            prestador_cnpj,
            conf.inscricao_municipal,
            conf.cert_path,
            conf.cert_senha,
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

    driver = SaoPauloDriver(ambiente=conf.ambiente)
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
