"""Leitura e validação da planilha de emissão de NFS-e."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook

from conta_tools_shared.domain.cnpj import only_digits
from conta_tools_shared.domain.nfse import NfseRequest, PrestadorNfse, TomadorNfse

from conta_tools_nfse.excel.columns import COLUNAS_OBRIGATORIAS, COLUNAS_TOMADOR_ID


def ler_planilha_campinas(
    caminho: Path,
    prestador_cnpj: str,
    inscricao_municipal: str,
    cert_path: Path,
    cert_senha: str,
) -> tuple[list[NfseRequest], list[str]]:
    """
    Lê a planilha e retorna (pedidos_válidos, lista_de_erros).

    Erros são por linha e não interrompem o processamento das demais.
    """
    wb = load_workbook(caminho, data_only=True)
    ws = wb.active

    # Mapear cabeçalhos → índice de coluna (1-based)
    cabecalhos_raw = [
        (ws.cell(1, c).value or "").strip().lower()
        for c in range(1, ws.max_column + 1)
    ]
    # Normalizar: remove asteriscos e parênteses do cabeçalho legível
    cabecalhos = [re.sub(r"[*()]|mm/aaaa|dd/mm/aaaa|r\$|s/n|s ou n", "", h).strip() for h in cabecalhos_raw]

    col_map: dict[str, int] = {}
    for idx, h in enumerate(cabecalhos, start=1):
        # Tenta encontrar por nome exato
        for col_name in COLUNAS_OBRIGATORIAS + COLUNAS_TOMADOR_ID + [
            "data_emissao", "tomador_inscricao_municipal", "tomador_email",
            "tomador_logradouro", "tomador_numero", "tomador_complemento",
            "tomador_bairro", "tomador_cep", "tomador_municipio_ibge", "tomador_uf",
            "deducoes", "iss_retido", "optante_simples", "natureza_operacao", "codigo_cnae",
        ]:
            if col_name in h or h in col_name:
                if col_name not in col_map:
                    col_map[col_name] = idx
                break

    # Verificar colunas obrigatórias
    faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in col_map]
    if faltando:
        raise ValueError(f"Colunas obrigatórias não encontradas: {', '.join(faltando)}")

    prestador = PrestadorNfse(
        cnpj=only_digits(prestador_cnpj),
        inscricao_municipal=inscricao_municipal,
        cert_path=cert_path,
        cert_senha=cert_senha,
    )

    pedidos: list[NfseRequest] = []
    erros: list[str] = []

    for row_num in range(2, ws.max_row + 1):
        def cel(col_name: str) -> str:
            if col_name not in col_map:
                return ""
            val = ws.cell(row_num, col_map[col_name]).value
            if val is None:
                return ""
            return str(val).strip()

        def cel_decimal(col_name: str, default: str = "0") -> Decimal:
            v = cel(col_name) or default
            v = v.replace(",", ".")
            try:
                return Decimal(v)
            except InvalidOperation:
                raise ValueError(f"Valor inválido em '{col_name}': {v!r}")

        # Pular linhas completamente vazias
        if not any(
            ws.cell(row_num, col_map[c]).value
            for c in COLUNAS_OBRIGATORIAS
            if c in col_map
        ):
            continue

        erros_linha: list[str] = []

        # Validar campos obrigatórios
        for c in COLUNAS_OBRIGATORIAS:
            if not cel(c):
                erros_linha.append(f"campo obrigatório vazio: {c}")

        # Validar identificação do tomador
        cnpj_tom = only_digits(cel("tomador_cnpj"))
        cpf_tom = only_digits(cel("tomador_cpf"))
        if not cnpj_tom and not cpf_tom:
            erros_linha.append("preencha tomador_cnpj ou tomador_cpf")

        # Validar competência
        competencia_raw = cel("competencia")
        competencia_iso = _parse_competencia(competencia_raw)
        if not competencia_iso:
            erros_linha.append(f"competencia inválida: {competencia_raw!r} (esperado MM/AAAA)")

        if erros_linha:
            erros.append(f"Linha {row_num}: {'; '.join(erros_linha)}")
            continue

        # Parsear data de emissão
        data_emissao_raw = cel("data_emissao")
        data_emissao = _parse_data(data_emissao_raw) or date.today().isoformat()

        try:
            valor = cel_decimal("valor_servico")
            deducoes = cel_decimal("deducoes", "0")
        except ValueError as e:
            erros.append(f"Linha {row_num}: {e}")
            continue

        tomador = TomadorNfse(
            razao_social=cel("tomador_razao_social"),
            cnpj=cnpj_tom,
            cpf=cpf_tom,
            inscricao_municipal=cel("tomador_inscricao_municipal"),
            email=cel("tomador_email"),
            logradouro=cel("tomador_logradouro"),
            numero=cel("tomador_numero"),
            complemento=cel("tomador_complemento"),
            bairro=cel("tomador_bairro"),
            cep=only_digits(cel("tomador_cep")),
            municipio_ibge=cel("tomador_municipio_ibge"),
            uf=cel("tomador_uf"),
        )

        iss_retido_raw = cel("iss_retido").upper()
        optante_raw = cel("optante_simples").upper()
        nat_op_raw = cel("natureza_operacao")

        req = NfseRequest(
            id=str(uuid4()),
            prestador=prestador,
            tomador=tomador,
            discriminacao=cel("discriminacao"),
            valor_servico=valor,
            codigo_servico=cel("codigo_servico"),
            municipio_prestacao="campinas",
            competencia=competencia_iso,
            numero_rps=cel("numero_rps"),
            data_emissao=data_emissao,
            deducoes=deducoes,
            iss_retido=iss_retido_raw == "S",
            optante_simples=optante_raw == "S",
            natureza_operacao=int(nat_op_raw) if nat_op_raw.isdigit() else 1,
            codigo_cnae=cel("codigo_cnae"),
        )
        pedidos.append(req)

    return pedidos, erros


def _parse_competencia(valor: str) -> str:
    """Converte MM/AAAA → AAAA-MM. Retorna '' se inválido."""
    if not valor:
        return ""
    m = re.fullmatch(r"(\d{1,2})[/\-](\d{4})", valor.strip())
    if not m:
        return ""
    mes, ano = int(m.group(1)), int(m.group(2))
    if not (1 <= mes <= 12):
        return ""
    return f"{ano}-{mes:02d}"


def _parse_data(valor: str) -> str:
    """Converte DD/MM/AAAA → AAAA-MM-DD. Retorna '' se inválido."""
    if not valor:
        return ""
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def salvar_resultado(
    caminho_original: Path,
    caminho_saida: Path,
    resultados: list[tuple],
) -> None:
    """
    Acrescenta colunas de resultado (status, numero_nfse, etc.) à planilha original.
    resultados: lista de (NfseRequest, NfseResult|None, erro_str|None)
    """
    from openpyxl.styles import Font, PatternFill

    wb = load_workbook(caminho_original)
    ws = wb.active

    # Encontrar próxima coluna vazia após os dados
    next_col = ws.max_column + 1
    headers = ["status", "numero_nfse", "codigo_verificacao", "link_consulta", "erro"]
    cores = {"EMITIDA": "C6EFCE", "ERRO": "FFC7CE"}

    for i, h in enumerate(headers):
        ws.cell(1, next_col + i, h).font = Font(bold=True)

    for row_offset, (req, result, erro) in enumerate(resultados, start=2):
        status = "EMITIDA" if result else "ERRO"
        cor = cores[status]
        fill = PatternFill("solid", fgColor=cor)
        cel_status = ws.cell(row_offset, next_col, status)
        cel_status.fill = fill
        ws.cell(row_offset, next_col + 1, result.numero_nota if result else "")
        ws.cell(row_offset, next_col + 2, result.codigo_verificacao if result else "")
        ws.cell(row_offset, next_col + 3, result.link_consulta if result else "")
        ws.cell(row_offset, next_col + 4, erro or "")

    wb.save(caminho_saida)
