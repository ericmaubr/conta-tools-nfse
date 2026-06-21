"""CLI para emissão de NFS-e na Prefeitura de Campinas."""

from __future__ import annotations

import argparse
import calendar
from datetime import date
from pathlib import Path

from conta_tools_shared.auth.certificate import cnpj_from_certificate, load_pfx_data
from conta_tools_shared.domain.nfse import PrestadorNfse
from conta_tools_shared.logging import formatter as log
from conta_tools_shared.version import handle_version_flags

from conta_tools_nfse.conf import carregar_conf
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

    # --- ultimo-rps ---
    urps = sub.add_parser(
        "ultimo-rps",
        help="Consulta o último RPS emitido por série",
        description=(
            "Consulta o webservice de Campinas e retorna o último número de RPS "
            "emitido para cada série (ex: '1', 'NFSE'). Útil para saber qual número "
            "usar na próxima emissão. Pesquisa mês a mês a partir do mês atual, "
            "retroagindo até encontrar NFS-e."
        ),
    )
    urps.add_argument(
        "--conf",
        required=True,
        type=Path,
        metavar="CONF",
        help="Arquivo .conf do prestador (cert, inscrição municipal, senha, ambiente)",
    )
    urps.add_argument(
        "--meses",
        type=int,
        default=24,
        metavar="N",
        help="Máximo de meses para retroagir (default: 24)",
    )

    # --- emitir ---
    emit = sub.add_parser("emitir", help="Emite as notas a partir de uma planilha")
    emit.add_argument(
        "--planilha",
        required=True,
        type=Path,
        metavar="XLSX",
        help="Planilha Excel com os dados das notas (use 'template' para gerar o modelo)",
    )
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
    if args.cmd == "ultimo-rps":
        return _cmd_ultimo_rps(args)
    if args.cmd == "emitir":
        return _cmd_emitir(args)

    parser.print_help()
    return 1


def _cmd_template(args: argparse.Namespace) -> int:
    criar_template_campinas(args.saida)
    log.log_ok(f"Template gerado: {args.saida}")
    return 0


def _cmd_ultimo_rps(args: argparse.Namespace) -> int:
    try:
        conf = carregar_conf(args.conf)
    except Exception as e:
        log.log_erro(f"Erro ao ler configuração: {e}")
        return 1

    try:
        cert_data = load_pfx_data(conf.cert_path, conf.cert_senha)
    except Exception as e:
        log.log_erro(f"Erro ao carregar certificado: {e}")
        return 1

    prestador_cnpj = cnpj_from_certificate(cert_data)
    if not prestador_cnpj:
        log.log_erro("Não foi possível extrair o CNPJ do certificado.")
        return 1

    prestador = PrestadorNfse(
        cnpj=prestador_cnpj,
        inscricao_municipal=conf.inscricao_municipal,
        cert_path=conf.cert_path,
        cert_senha=conf.cert_senha,
    )

    driver = CampinasDriver(ambiente=conf.ambiente)

    hoje = date.today()
    ano, mes = hoje.year, hoje.month
    resultado: dict[str, tuple[str, str, str]] = {}

    for _ in range(args.meses):
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        data_ini = f"{ano}-{mes:02d}-01"
        data_fim = f"{ano}-{mes:02d}-{ultimo_dia:02d}"
        log.log_info(f"Consultando {mes:02d}/{ano}...")

        try:
            resultado = driver.consultar_nfse_periodo(prestador, data_ini, data_fim)
        except Exception as e:
            log.log_erro(f"Erro na consulta: {e}")
            return 1

        if resultado:
            break

        mes -= 1
        if mes == 0:
            mes = 12
            ano -= 1

    if not resultado:
        log.log_aviso(f"Nenhuma NFS-e encontrada nos últimos {args.meses} meses.")
        return 0

    for serie in sorted(resultado.keys()):
        ultimo_rps, numero_nfse, data_emissao = resultado[serie]
        log.log_ok(
            f"Série {serie!r:10} → último RPS: {ultimo_rps:>8}"
            f"  (NFS-e {numero_nfse} · {data_emissao})"
        )

    return 0


def _cmd_emitir(args: argparse.Namespace) -> int:
    # 1. Carregar configuração
    try:
        conf = carregar_conf(args.conf)
    except Exception as e:
        log.log_erro(f"Erro ao ler configuração: {e}")
        return 1

    if conf.ambiente == "homologacao":
        log.log_aviso("ATENÇÃO: executando em ambiente de HOMOLOGAÇÃO.")

    # 2. Carregar certificado e extrair CNPJ
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

    # 3. Ler planilha
    try:
        pedidos, erros_leitura = ler_planilha_campinas(
            args.planilha,
            prestador_cnpj,
            conf.inscricao_municipal,
            conf.cert_path,
            conf.cert_senha,
            optante_simples=conf.optante_simples,
            serie_rps=conf.serie_rps,
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

    # 4. Emitir
    driver = CampinasDriver(ambiente=conf.ambiente)
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

    # 5. Salvar resultado
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
