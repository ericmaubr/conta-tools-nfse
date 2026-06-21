"""Servidor MCP para emissão de NFS-e via linguagem natural.

Ferramentas expostas:
  listar_prestadores   — descobre as empresas emissoras disponíveis
  montar_emissao       — valida os dados e monta resumo para conferência
  confirmar_emissao    — emite a NFS-e após confirmação explícita do usuário

Fluxo obrigatório:
  listar_prestadores → coletar dados → montar_emissao → usuário confirma → confirmar_emissao
"""

from __future__ import annotations

import json
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP

# ------------------------------------------------------------------ #
# Estado de módulo (preenchido por inicializar())                     #
# ------------------------------------------------------------------ #

_api_url: str = ""
_bearer_token: str = ""

mcp = FastMCP(
    "ContaTools NFS-e",
    instructions=(
        "Você é um assistente para emissão de Notas Fiscais de Serviços Eletrônicas (NFS-e). "
        "REGRAS INVIOLÁVEIS:\n"
        "1. Sempre chame listar_prestadores primeiro e apresente a lista ao usuário. "
        "Nunca assuma qual empresa emissora usar sem seleção explícita.\n"
        "2. Nunca infira o tomador por nome. Exija CNPJ ou CPF antes de prosseguir.\n"
        "3. Sempre chame montar_emissao e apresente o resumo completo ao usuário. "
        "Só chame confirmar_emissao após confirmação textual explícita do usuário.\n"
        "4. Nunca altere valores monetários, RPS ou dados do tomador sem nova confirmação."
    ),
)


# ------------------------------------------------------------------ #
# Helper de HTTP                                                       #
# ------------------------------------------------------------------ #


def _api(method: str, path: str, body: dict | None = None) -> dict | list:
    url = f"{_api_url}{path}"
    headers = {"Authorization": f"Bearer {_bearer_token}"}
    try:
        r = requests.request(method, url, json=body, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", "")
        except Exception:
            pass
        raise RuntimeError(detail or str(e)) from e
    except requests.ConnectionError:
        raise RuntimeError(
            f"Não foi possível conectar à API em {_api_url}. "
            "Verifique se o servidor está no ar e se a URL em mcp.conf está correta."
        )


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ------------------------------------------------------------------ #
# Ferramenta 1 — listar_prestadores                                   #
# ------------------------------------------------------------------ #


@mcp.tool()
def listar_prestadores() -> str:
    """Lista as empresas emissoras de NFS-e disponíveis no sistema.

    DEVE ser a primeira ferramenta chamada em qualquer fluxo de emissão.
    Apresente a lista completa ao usuário e aguarde que ele selecione
    explicitamente uma empresa pelo campo 'id'.
    Nunca assuma qual empresa usar sem confirmação explícita do usuário.

    Retorna lista JSON com campos: id (usar em todas as ferramentas), nome.
    """
    try:
        data = _api("GET", "/prestadores")
        if not data:
            return "Nenhuma empresa emissora cadastrada no servidor."
        return _json(data)
    except RuntimeError as e:
        return f"ERRO ao listar prestadores: {e}"


# ------------------------------------------------------------------ #
# Ferramenta 2 — montar_emissao                                       #
# ------------------------------------------------------------------ #


@mcp.tool()
def montar_emissao(
    prestador_id: str,
    tomador_cnpj: str,
    tomador_razao_social: str,
    competencia: str,
    discriminacao: str,
    codigo_servico: str,
    valor_servico: str,
    tomador_cpf: str = "",
    codigo_cnae: str = "",
    iss_retido: bool = False,
    valor_iss: str = "",
    tomador_email: str = "",
    tomador_logradouro: str = "",
    tomador_numero: str = "",
    tomador_complemento: str = "",
    tomador_bairro: str = "",
    tomador_cep: str = "",
    tomador_uf: str = "",
) -> str:
    """Valida os dados da NFS-e e monta resumo para conferência pelo usuário.

    NÃO emite a nota. Após obter o resumo, apresente-o integralmente ao usuário
    e aguarde confirmação explícita antes de chamar confirmar_emissao.

    REGRAS OBRIGATÓRIAS — nunca viole:
    - prestador_id: use exatamente o campo 'id' retornado por listar_prestadores.
      Nunca infira ou abrevie.
    - tomador_cnpj ou tomador_cpf: pelo menos um é obrigatório.
      Se o usuário informou apenas o nome da empresa tomadora, pergunte o CNPJ
      antes de chamar esta ferramenta.
    - tomador_razao_social: use exatamente o nome informado pelo usuário.
    - competencia: formato AAAA-MM (ex: 2026-06).
    - valor_servico: string com ponto decimal (ex: "1500.00").
    - valor_iss: preencha apenas se iss_retido=True e o usuário informou o valor.

    Retorna resumo JSON com numero_rps pré-preenchido (busca automática do próximo RPS).
    Use esse mesmo numero_rps ao chamar confirmar_emissao.
    """
    # Valida prestador_id
    if not prestador_id:
        return "ERRO: prestador_id é obrigatório. Chame listar_prestadores primeiro."

    if not tomador_cnpj and not tomador_cpf:
        return (
            "ERRO: CNPJ ou CPF do tomador é obrigatório. "
            "Pergunte o CNPJ ao usuário antes de prosseguir."
        )

    if not tomador_razao_social.strip():
        return "ERRO: Razão social do tomador é obrigatória."

    if not competencia or len(competencia) != 7 or competencia[4] != "-":
        return f"ERRO: competencia deve estar no formato AAAA-MM. Recebido: {competencia!r}"

    try:
        float(valor_servico.replace(",", "."))
    except (ValueError, AttributeError):
        return f"ERRO: valor_servico inválido: {valor_servico!r}. Use ponto decimal (ex: '1500.00')."

    # Verifica que o prestador existe e obtém nome
    try:
        prestadores = _api("GET", "/prestadores")
    except RuntimeError as e:
        return f"ERRO ao verificar prestadores: {e}"

    prestador_map = {p["id"]: p["nome"] for p in prestadores}
    if prestador_id not in prestador_map:
        ids = list(prestador_map.keys())
        return (
            f"ERRO: prestador_id '{prestador_id}' não existe. "
            f"IDs válidos: {ids}. Chame listar_prestadores para ver as opções."
        )
    nome_prestador = prestador_map[prestador_id]

    # Busca próximo RPS
    try:
        rps_data = _api("GET", f"/prestadores/{prestador_id}/proximo-rps")
        numero_rps = str(rps_data["proximo_rps"])
    except RuntimeError as e:
        return f"ERRO ao buscar próximo RPS: {e}"

    resumo = {
        "prestador_id": prestador_id,
        "prestador_nome": nome_prestador,
        "numero_rps": numero_rps,
        "competencia": competencia,
        "discriminacao": discriminacao,
        "codigo_servico": codigo_servico,
        "codigo_cnae": codigo_cnae,
        "valor_servico": valor_servico.replace(",", "."),
        "iss_retido": iss_retido,
        "valor_iss": (valor_iss.replace(",", ".") if iss_retido and valor_iss else ""),
        "tomador": {
            "razao_social": tomador_razao_social,
            "cnpj": tomador_cnpj,
            "cpf": tomador_cpf,
            "email": tomador_email,
            "logradouro": tomador_logradouro,
            "numero": tomador_numero,
            "complemento": tomador_complemento,
            "bairro": tomador_bairro,
            "cep": tomador_cep,
            "uf": tomador_uf.upper() if tomador_uf else "",
        },
        "_instrucao": (
            "Apresente este resumo ao usuário e aguarde confirmação explícita. "
            "Só chame confirmar_emissao após o usuário confirmar. "
            "Use o numero_rps acima sem alteração."
        ),
    }

    return _json(resumo)


# ------------------------------------------------------------------ #
# Ferramenta 3 — confirmar_emissao                                    #
# ------------------------------------------------------------------ #


@mcp.tool()
def confirmar_emissao(
    prestador_id: str,
    numero_rps: str,
    tomador_cnpj: str,
    tomador_razao_social: str,
    competencia: str,
    discriminacao: str,
    codigo_servico: str,
    valor_servico: str,
    tomador_cpf: str = "",
    codigo_cnae: str = "",
    iss_retido: bool = False,
    valor_iss: str = "",
    tomador_email: str = "",
    tomador_logradouro: str = "",
    tomador_numero: str = "",
    tomador_complemento: str = "",
    tomador_bairro: str = "",
    tomador_cep: str = "",
    tomador_uf: str = "",
) -> str:
    """Emite a NFS-e. Chame SOMENTE após o usuário confirmar explicitamente
    o resumo apresentado por montar_emissao.

    REGRAS OBRIGATÓRIAS:
    - Use exatamente os mesmos dados retornados por montar_emissao,
      incluindo o numero_rps. Não altere nenhum campo sem nova confirmação.
    - Se o servidor retornar rps_ajustado, informe o usuário que o RPS
      foi corrigido automaticamente (número anterior já estava em uso).
    """
    body = {
        "prestador_id": prestador_id,
        "numero_rps": numero_rps,
        "competencia": competencia,
        "discriminacao": discriminacao,
        "codigo_servico": codigo_servico,
        "codigo_cnae": codigo_cnae,
        "valor_servico": valor_servico.replace(",", "."),
        "iss_retido": iss_retido,
        "valor_iss": (valor_iss.replace(",", ".") if iss_retido and valor_iss else None),
        "tomador_razao_social": tomador_razao_social,
        "tomador_cnpj": tomador_cnpj,
        "tomador_cpf": tomador_cpf,
        "tomador_email": tomador_email,
        "tomador_logradouro": tomador_logradouro,
        "tomador_numero": tomador_numero,
        "tomador_complemento": tomador_complemento,
        "tomador_bairro": tomador_bairro,
        "tomador_cep": tomador_cep,
        "tomador_municipio_ibge": "",
        "tomador_uf": tomador_uf.upper() if tomador_uf else "",
    }

    try:
        result = _api("POST", "/nfse", body)
    except RuntimeError as e:
        return f"ERRO na emissão: {e}"

    saida = {
        "status": result.get("status"),
        "numero_nfse": result.get("numero_nfse"),
        "codigo_verificacao": result.get("codigo_verificacao"),
        "link_consulta": result.get("link_consulta"),
        "arquivo": result.get("arquivo"),
    }
    if result.get("rps_ajustado"):
        aj = result["rps_ajustado"]
        saida["aviso_rps"] = (
            f"RPS ajustado automaticamente de {aj['de']} para {aj['para']} "
            "(número anterior já estava em uso). Informe o usuário."
        )

    return _json(saida)


# ------------------------------------------------------------------ #
# Inicialização                                                        #
# ------------------------------------------------------------------ #


def inicializar(api_url: str, bearer_token: str) -> None:
    global _api_url, _bearer_token
    _api_url = api_url.rstrip("/")
    _bearer_token = bearer_token


def run() -> None:
    mcp.run()
